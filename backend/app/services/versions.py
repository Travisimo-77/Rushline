"""Applying plans, checkpoints/recovery, and creating ad variations as separate versions."""
from __future__ import annotations

from .. import db
from ..jobs import enqueue
from ..timeline import OP_KINDS
from . import plans
from .context import Ctx


class InvalidOp(Exception):
    pass


def _validate(op: dict) -> dict:
    k = op.get("kind")
    p = op.get("params")
    if k not in OP_KINDS or not isinstance(p, dict):
        raise InvalidOp(f"invalid op {k}")
    if k in ("remove", "restore"):
        rs = p.get("ranges")
        if not isinstance(rs, list) or not all(isinstance(r, list) and len(r) == 3 and float(r[2]) >= float(r[1]) for r in rs):
            raise InvalidOp("bad ranges")
    return {"kind": k, "params": p, "label": str(op.get("label") or k)[:200]}


def checkpoint(version_id: str, label: str) -> str:
    ops = db.all_("SELECT id, enabled FROM ops WHERE version_id=?", version_id)
    cid = db.new_id("ck_")
    db.insert("checkpoints", {"id": cid, "version_id": version_id, "label": label[:120],
                              "state": {"enabled": [o["id"] for o in ops if o["enabled"]], "all": [o["id"] for o in ops]},
                              "created_at": db.now()})
    return cid


def add_ops(version_id: str, ops: list[dict], source: str = "user", group_label: str | None = None,
            disable: list[str] | None = None, make_checkpoint: bool = False) -> list[str]:
    clean = [_validate(o) for o in ops]
    if make_checkpoint:
        checkpoint(version_id, f"Before: {group_label or 'edit'}")
    gid = db.new_id("grp_") if len(clean) > 1 or disable else None
    ids = []
    with db.transaction() as c:
        row = c.execute("SELECT COALESCE(MAX(seq), 0) AS m FROM ops WHERE version_id=?", (version_id,)).fetchone()
        seq = row["m"]
        for o in clean:
            seq += 1
            oid = db.new_id("op_")
            c.execute("INSERT INTO ops (id, version_id, seq, kind, label, params, source, enabled, group_id, created_at) "
                      "VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (oid, version_id, seq, o["kind"], o["label"], db._encode(o["params"]), source, 1, gid, db.now()))
            ids.append(oid)
        for d in disable or []:
            c.execute("UPDATE ops SET enabled=0 WHERE id=? AND version_id=?", (d, version_id))
        c.execute("UPDATE versions SET updated_at=? WHERE id=?", (db.now(), version_id))
    return ids


def apply_plan(ctx: Ctx, steps: list[dict], title: str, source: str = "ai") -> list[str]:
    ops = [o for s in steps for o in s.get("ops", [])]
    disable = [d for s in steps for d in s.get("disable", [])]
    if not ops and not disable:
        return []
    ids = add_ops(ctx.version["id"], ops, source, title, disable, make_checkpoint=True)
    _side_effects(ctx, ops)
    return ids


def _side_effects(ctx: Ctx, ops: list[dict]) -> None:
    for o in ops:
        if o["kind"] == "settings" and o["params"].get("patch", {}).get("audio", {}).get("enhance"):
            for m in ctx.ready_media:
                if m["has_audio"] and not m["enhanced_path"]:
                    enqueue("enhance_audio", {"media_id": m["id"]}, ctx.user_id)


def restore_checkpoint(version_id: str, checkpoint_id: str) -> None:
    ck = db.one("SELECT * FROM checkpoints WHERE id=? AND version_id=?", checkpoint_id, version_id)
    if not ck:
        raise KeyError("checkpoint")
    checkpoint(version_id, f"Before restoring “{ck['label']}”")
    enabled = set(ck["state"]["enabled"])
    with db.transaction() as c:
        for o in c.execute("SELECT id FROM ops WHERE version_id=?", (version_id,)).fetchall():
            c.execute("UPDATE ops SET enabled=? WHERE id=?", (1 if o["id"] in enabled else 0, o["id"]))


def set_op_enabled(version_id: str, op_id: str, enabled: bool, whole_group: bool = False) -> None:
    op = db.one("SELECT * FROM ops WHERE id=? AND version_id=?", op_id, version_id)
    if not op:
        raise KeyError("op")
    if whole_group and op["group_id"]:
        db.execute("UPDATE ops SET enabled=? WHERE group_id=? AND version_id=?", int(enabled), op["group_id"], version_id)
    else:
        db.execute("UPDATE ops SET enabled=? WHERE id=?", int(enabled), op_id)


def create_version(project_id: str, name: str, copy_from: str | None = None, meta: dict | None = None) -> str:
    vid = db.new_id("ver_")
    db.insert("versions", {"id": vid, "project_id": project_id, "name": name, "meta": meta or {}, "created_at": db.now(),
                           "updated_at": db.now()})
    if copy_from:
        for o in db.all_("SELECT * FROM ops WHERE version_id=? AND enabled=1 ORDER BY seq", copy_from):
            db.insert("ops", {**o, "id": db.new_id("op_"), "version_id": vid, "created_at": db.now()})
    return vid


def create_variations(ctx: Ctx, specs: list[dict]) -> list[dict]:
    pid = ctx.project["id"]
    n0 = (db.one("SELECT COUNT(*) AS n FROM versions WHERE project_id=?", pid) or {"n": 0})["n"]
    out = []
    for i, spec in enumerate(specs):
        vid = create_version(pid, f"Ad {n0 + i}", copy_from=ctx.version["id"], meta={"template": spec["template"], "hook_id": spec.get("hook_id"),
                                                                                       "hook_text": spec.get("hook_text"), "cta_id": spec.get("cta_id"),
                                                                                       "cta_text": spec.get("cta_text")})
        vctx = Ctx(vid, ctx.user_id)
        steps = []
        cur = vctx
        for st in (plans.best_hook_step(cur, spec.get("hook_id")),):
            if st:
                steps.append(st)
                cur = vctx.with_ops([o for s in steps for o in s["ops"]])
        if spec.get("hook_id"):
            st = plans.alternate_hooks_step(cur, spec["hook_id"])
            if st:
                steps.append(st); cur = vctx.with_ops([o for s in steps for o in s["ops"]])
        st = plans.restructure_step(cur, spec["template"], spec.get("hook_id"))
        if st:
            steps.append(st); cur = vctx.with_ops([o for s in steps for o in s["ops"]])
        if spec.get("cta_id"):
            for st in plans.cta_step(cur, spec["cta_id"]):
                steps.append(st); cur = vctx.with_ops([o for s in steps for o in s["ops"]])
        if spec.get("target"):
            st = plans.fit_duration_step(cur, spec["target"])
            if st:
                steps.append(st); cur = vctx.with_ops([o for s in steps for o in s["ops"]])
        if steps:
            apply_plan(vctx, steps, f"Variation: {spec['label']}", source="ai")
        final = Ctx(vid, ctx.user_id)
        name = f"Ad {n0 + i} · {spec['label']} · {final.tl['duration']:.0f}s"
        db.update("versions", "id", vid, {"name": name})
        out.append({"id": vid, "name": name, "duration": final.tl["duration"], "hook": spec.get("hook_text")})
    return out
