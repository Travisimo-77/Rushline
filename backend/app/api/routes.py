"""HTTP API (/api/v1). Thin handlers: authenticate, authorize ownership, delegate to services."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Route

from .. import db, jobs
from ..config import MAX_UPLOAD_BYTES, PLANS, DEFAULT_PLAN, SIGNUPS
from ..media.captions import PRESETS
from ..ai.structure import SECTION_LABELS, SECTIONS
from ..security import hash_password, make_jwt, read_jwt, sign_media, verify_media, verify_password
from ..services import plans, versions
from ..services.context import Ctx, NotFound
from ..services.pipeline import plan_limits
from ..storage import storage

routes: list[Route] = []
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi", ".3gp", ".hevc"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic"}


class HTTPError(Exception):
    def __init__(self, status: int, msg: str):
        self.status, self.msg = status, msg


def api(path: str, methods=("GET",), auth: bool = True):
    def deco(fn):
        async def endpoint(req: Request):
            try:
                user = None
                if auth:
                    h = req.headers.get("authorization", "")
                    uid = read_jwt(h[7:]) if h.lower().startswith("bearer ") else None
                    user = db.one("SELECT * FROM users WHERE id=?", uid) if uid else None
                    if not user:
                        raise HTTPError(401, "Please sign in.")
                body = {}
                if req.method in ("POST", "PATCH", "PUT", "DELETE") and req.headers.get("content-type", "").startswith("application/json"):
                    raw = await req.body()
                    body = json.loads(raw or b"{}")
                res = await fn(req, user, body) if _is_async(fn) else fn(req, user, body)
                if isinstance(res, Response):
                    return res
                return JSONResponse(res)
            except HTTPError as e:
                return JSONResponse({"error": e.msg}, status_code=e.status)
            except NotFound as e:
                return JSONResponse({"error": f"{e} not found"}, status_code=404)
            except (versions.InvalidOp, ValueError, json.JSONDecodeError) as e:
                return JSONResponse({"error": str(e)}, status_code=400)
            except KeyError as e:
                return JSONResponse({"error": f"not found: {e}"}, status_code=404)
        routes.append(Route("/api/v1" + path, endpoint, methods=list(methods)))
        return fn
    return deco


def _is_async(fn) -> bool:
    import inspect
    return inspect.iscoroutinefunction(fn)


def _own_project(user, pid) -> dict:
    p = db.one("SELECT * FROM projects WHERE id=? AND user_id=?", pid, user["id"])
    if not p:
        raise HTTPError(404, "Project not found")
    return p


def _own_version(user, vid) -> dict:
    v = db.one("SELECT v.* FROM versions v JOIN projects p ON p.id=v.project_id WHERE v.id=? AND p.user_id=?", vid, user["id"])
    if not v:
        raise HTTPError(404, "Version not found")
    return v


def _user_out(u):
    return {"id": u["id"], "email": u["email"], "name": u["name"], "plan": u["plan"], "limits": plan_limits(u["id"])}


# ------------------------------------------------------------------ auth
@api("/auth/signup", ["POST"], auth=False)
def signup(req, user, b):
    email = (b.get("email") or "").strip().lower()
    pw = b.get("password") or ""
    if not EMAIL_RE.match(email):
        raise HTTPError(400, "Enter a valid email.")
    if len(pw) < 8:
        raise HTTPError(400, "Password must be at least 8 characters.")
    if db.one("SELECT id FROM users WHERE email=?", email):
        raise HTTPError(409, "An account with this email already exists.")
    uid = db.new_id("usr_")
    if SIGNUPS == "closed" and db.one("SELECT id FROM users LIMIT 1"):
        raise HTTPError(403, "Sign-ups are closed on this Rushline site. Ask the owner for an account.")
    # the first account on a self-hosted install is the owner and gets every feature
    first = not db.one("SELECT id FROM users LIMIT 1")
    db.insert("users", {"id": uid, "email": email, "password_hash": hash_password(pw), "name": (b.get("name") or "").strip()[:80],
                        "plan": "agency" if first else DEFAULT_PLAN, "created_at": db.now()})
    return {"token": make_jwt(uid), "user": _user_out(db.one("SELECT * FROM users WHERE id=?", uid))}


@api("/auth/login", ["POST"], auth=False)
def login(req, user, b):
    u = db.one("SELECT * FROM users WHERE email=?", (b.get("email") or "").strip().lower())
    if not u or not verify_password(b.get("password") or "", u["password_hash"]):
        time.sleep(0.4)
        raise HTTPError(401, "Email or password is incorrect.")
    return {"token": make_jwt(u["id"]), "user": _user_out(u)}


@api("/auth/me")
def me(req, user, b):
    return _user_out(user)


@api("/meta", auth=False)
def meta(req, user, b):
    return {"caption_presets": PRESETS, "sections": SECTIONS, "section_labels": SECTION_LABELS, "plans": PLANS,
            "templates": plans.TEMPLATE_LABEL}


# ------------------------------------------------------------------ dashboard
@api("/home")
def home(req, user, b):
    return {"projects": _projects(user)[:8],
            "products": [_product_out(p) for p in db.all_("SELECT * FROM products WHERE user_id=? ORDER BY updated_at DESC LIMIT 8", user["id"])],
            "exports": _exports(user)[:6], "limits": plan_limits(user["id"])}


def _projects(user):
    rows = db.all_("SELECT * FROM projects WHERE user_id=? ORDER BY updated_at DESC", user["id"])
    out = []
    for p in rows:
        ms = db.all_("SELECT id, status, duration, thumb_path FROM media WHERE project_id=? ORDER BY position", p["id"])
        thumb = next((m for m in ms if m["thumb_path"]), None)
        nver = db.one("SELECT COUNT(*) AS n FROM versions WHERE project_id=?", p["id"])["n"]
        out.append({"id": p["id"], "name": p["name"], "mode": p["mode"], "status": p["status"], "updated_at": p["updated_at"],
                    "media_count": len(ms), "raw_duration": round(sum(m["duration"] or 0 for m in ms), 1), "versions": nver,
                    "processing": sum(1 for m in ms if m["status"] not in ("ready", "failed")),
                    "thumb_url": f"/api/v1/media/{thumb['id']}/thumb?token={sign_media(user['id'], thumb['id'])}" if thumb else None,
                    "active_version_id": p["active_version_id"]})
    return out


# ------------------------------------------------------------------ projects
@api("/projects")
def list_projects(req, user, b):
    return _projects(user)


@api("/projects", ["POST"])
def create_project(req, user, b):
    pid = db.new_id("prj_")
    name = (b.get("name") or "Untitled project").strip()[:120]
    mode = b.get("mode") if b.get("mode") in ("tiktok_shop", "clean") else "tiktok_shop"
    strength = b.get("strength") if b.get("strength") in ("clean", "fast", "viral") else "fast"
    product_id = b.get("product_id")
    if product_id and not db.one("SELECT id FROM products WHERE id=? AND user_id=?", product_id, user["id"]):
        raise HTTPError(400, "Unknown product")
    target = b.get("target_duration")
    settings = {"auto_first_pass": b.get("auto_first_pass", True), "generate_ads": bool(b.get("generate_ads", mode == "tiktok_shop")),
                "ad_count": int(b.get("ad_count") or 3), "sensitivity": b.get("sensitivity") or {}}
    db.insert("projects", {"id": pid, "user_id": user["id"], "name": name, "mode": mode, "product_id": product_id,
                           "target_duration": float(target) if target else None, "strength": strength, "settings": settings,
                           "status": "new", "created_at": db.now(), "updated_at": db.now()})
    vid = versions.create_version(pid, "Main edit")
    db.update("projects", "id", pid, {"active_version_id": vid})
    return {"id": pid, "active_version_id": vid}


@api("/projects/{pid}")
def get_project(req, user, b):
    p = _own_project(user, req.path_params["pid"])
    vs = db.all_("SELECT id, name, meta, created_at, updated_at FROM versions WHERE project_id=? ORDER BY created_at", p["id"])
    js = db.all_("SELECT j.id, j.kind, j.status, j.progress, j.message, j.error, j.payload FROM jobs j WHERE j.user_id=? AND "
                 "j.status IN ('queued','running') ORDER BY created_at", user["id"])
    mids = {m["id"] for m in db.all_("SELECT id FROM media WHERE project_id=?", p["id"])}
    js = [j for j in js if j["payload"].get("media_id") in mids or j["payload"].get("project_id") == p["id"]]
    product = db.one("SELECT * FROM products WHERE id=?", p["product_id"]) if p["product_id"] else None
    return {**{k: p[k] for k in ("id", "name", "mode", "product_id", "target_duration", "strength", "settings", "active_version_id",
                                 "status", "updated_at")},
            "versions": vs, "jobs": [{k: j[k] for k in ("id", "kind", "status", "progress", "message")} for j in js],
            "product": _product_out(product) if product else None}


@api("/projects/{pid}", ["PATCH"])
def patch_project(req, user, b):
    p = _own_project(user, req.path_params["pid"])
    f = {}
    for k in ("name", "mode", "strength", "product_id", "active_version_id"):
        if k in b:
            f[k] = b[k]
    if "target_duration" in b:
        f["target_duration"] = float(b["target_duration"]) if b["target_duration"] else None
    if "settings" in b and isinstance(b["settings"], dict):
        f["settings"] = {**(p["settings"] or {}), **b["settings"]}
    if f.get("product_id") and not db.one("SELECT id FROM products WHERE id=? AND user_id=?", f["product_id"], user["id"]):
        raise HTTPError(400, "Unknown product")
    if f.get("active_version_id"):
        _own_version(user, f["active_version_id"])
    f["updated_at"] = db.now()
    db.update("projects", "id", p["id"], f)
    if "product_id" in b and b["product_id"] != p["product_id"]:
        jobs.enqueue("rescan", {"project_id": p["id"]}, user["id"])
    return {"ok": True}


@api("/projects/{pid}", ["DELETE"])
def delete_project(req, user, b):
    """Deletes the project, its versions/edits and exports. Uploaded media is deleted too unless keep_media=1."""
    p = _own_project(user, req.path_params["pid"])
    keep = req.query_params.get("keep_media") == "1"
    for m in db.all_("SELECT * FROM media WHERE project_id=?", p["id"]):
        if keep:
            db.update("media", "id", m["id"], {"project_id": None})
        else:
            _delete_media(user, m)
    for v in db.all_("SELECT id FROM versions WHERE project_id=?", p["id"]):
        db.execute("DELETE FROM ops WHERE version_id=?", v["id"])
        db.execute("DELETE FROM checkpoints WHERE version_id=?", v["id"])
    db.execute("DELETE FROM versions WHERE project_id=?", p["id"])
    for e in db.all_("SELECT * FROM exports WHERE project_id=?", p["id"]):
        if e["output_path"]:
            storage.abs(e["output_path"]).unlink(missing_ok=True)
    db.execute("DELETE FROM exports WHERE project_id=?", p["id"])
    db.execute("DELETE FROM projects WHERE id=?", p["id"])
    return {"ok": True}


@api("/projects/{pid}/upload", ["POST", "PUT"])
async def upload(req, user, b):
    p = _own_project(user, req.path_params["pid"])
    filename = Path(req.query_params.get("filename") or "clip.mp4").name[:200]
    ext = Path(filename).suffix.lower() or ".mp4"
    if ext not in VIDEO_EXT:
        raise HTTPError(415, f"Unsupported file type {ext}. Upload a video (mp4, mov, m4v, webm).")
    length = int(req.headers.get("content-length") or 0)
    if length > MAX_UPLOAD_BYTES:
        raise HTTPError(413, "File too large.")
    mid = db.new_id("med_")
    d = storage.media_dir(user["id"], mid)
    dest = d / f"original{ext}"
    size = 0
    tmp = dest.with_suffix(ext + ".part")
    with open(tmp, "wb") as f:
        async for chunk in req.stream():
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                f.close(); tmp.unlink(missing_ok=True)
                raise HTTPError(413, "File too large.")
            f.write(chunk)
    if size == 0:
        tmp.unlink(missing_ok=True)
        raise HTTPError(400, "Empty upload.")
    tmp.rename(dest)
    dest.chmod(0o440)
    pos = (db.one("SELECT COALESCE(MAX(position), -1) AS m FROM media WHERE project_id=?", p["id"]) or {"m": -1})["m"] + 1
    db.insert("media", {"id": mid, "user_id": user["id"], "project_id": p["id"], "kind": "video", "filename": filename,
                        "original_path": storage.rel(dest), "status": "uploaded", "position": pos, "created_at": db.now()})
    jid = jobs.enqueue("ingest", {"media_id": mid}, user["id"])
    db.update("projects", "id", p["id"], {"status": "processing", "updated_at": db.now()})
    return {"media_id": mid, "job_id": jid, "bytes": size}


@api("/projects/{pid}/media/order", ["POST"])
def reorder_media(req, user, b):
    p = _own_project(user, req.path_params["pid"])
    for n, mid in enumerate(b.get("media_ids", [])):
        db.execute("UPDATE media SET position=? WHERE id=? AND project_id=?", n, mid, p["id"])
    return {"ok": True}


# ------------------------------------------------------------------ versions / timeline
@api("/versions/{vid}")
def get_version(req, user, b):
    _own_version(user, req.path_params["vid"])
    return Ctx(req.path_params["vid"], user["id"]).view()


@api("/versions/{vid}/ops", ["POST"])
def post_ops(req, user, b):
    v = _own_version(user, req.path_params["vid"])
    ops = b.get("ops") or ([b["op"]] if b.get("op") else [])
    if not ops:
        raise HTTPError(400, "No ops")
    ids = versions.add_ops(v["id"], ops, "user", b.get("label"), make_checkpoint=bool(b.get("checkpoint")))
    db.update("projects", "id", v["project_id"], {"updated_at": db.now()})
    ctx = Ctx(v["id"], user["id"])
    versions._side_effects(ctx, ops)
    return {"op_ids": ids, "view": ctx.view()}


@api("/versions/{vid}/ops/{oid}", ["PATCH"])
def patch_op(req, user, b):
    v = _own_version(user, req.path_params["vid"])
    versions.set_op_enabled(v["id"], req.path_params["oid"], bool(b.get("enabled")), bool(b.get("group")))
    return {"view": Ctx(v["id"], user["id"]).view()}


@api("/versions/{vid}/undo", ["POST"])
def undo(req, user, b):
    v = _own_version(user, req.path_params["vid"])
    last = db.one("SELECT * FROM ops WHERE version_id=? AND enabled=1 ORDER BY seq DESC LIMIT 1", v["id"])
    if last:
        versions.set_op_enabled(v["id"], last["id"], False, whole_group=True)
    return {"undone": last["label"] if last else None, "view": Ctx(v["id"], user["id"]).view()}


@api("/versions/{vid}/redo", ["POST"])
def redo(req, user, b):
    v = _own_version(user, req.path_params["vid"])
    # most recently disabled op that has no enabled op after it
    last_enabled = db.one("SELECT COALESCE(MAX(seq),0) AS s FROM ops WHERE version_id=? AND enabled=1", v["id"])["s"]
    nxt = db.one("SELECT * FROM ops WHERE version_id=? AND enabled=0 AND seq>? ORDER BY seq LIMIT 1", v["id"], last_enabled)
    if nxt:
        versions.set_op_enabled(v["id"], nxt["id"], True, whole_group=True)
    return {"redone": nxt["label"] if nxt else None, "view": Ctx(v["id"], user["id"]).view()}


@api("/versions/{vid}/checkpoints", ["POST"])
def make_checkpoint(req, user, b):
    v = _own_version(user, req.path_params["vid"])
    return {"id": versions.checkpoint(v["id"], b.get("label") or "Manual checkpoint")}


@api("/versions/{vid}/checkpoints/{cid}/restore", ["POST"])
def restore_ck(req, user, b):
    v = _own_version(user, req.path_params["vid"])
    versions.restore_checkpoint(v["id"], req.path_params["cid"])
    return {"view": Ctx(v["id"], user["id"]).view()}


@api("/versions/{vid}/reset", ["POST"])
def reset_version(req, user, b):
    """RESET AI EDIT: disables every AI op (kept in history, restorable via checkpoint)."""
    v = _own_version(user, req.path_params["vid"])
    versions.checkpoint(v["id"], "Before reset")
    q = "UPDATE ops SET enabled=0 WHERE version_id=?" + ("" if b.get("all") else " AND source IN ('ai','assistant')")
    db.execute(q, v["id"])
    return {"view": Ctx(v["id"], user["id"]).view()}


@api("/versions/{vid}/plan", ["POST"])
def make_plan(req, user, b):
    v = _own_version(user, req.path_params["vid"])
    ctx = Ctx(v["id"], user["id"])
    action = b.get("action") or "assistant"
    return plans.build(ctx, action, b.get("args") or ({"text": b.get("text", "")} if action == "assistant" else {}))


@api("/versions/{vid}/apply", ["POST"])
def apply(req, user, b):
    v = _own_version(user, req.path_params["vid"])
    ctx = Ctx(v["id"], user["id"])
    steps = b.get("steps") or []
    ids = versions.apply_plan(ctx, steps, b.get("title") or "AI plan", "assistant" if b.get("from_assistant") else "ai")
    created = []
    if b.get("variations"):
        created = versions.create_variations(ctx, b["variations"])
    db.update("projects", "id", v["project_id"], {"updated_at": db.now()})
    return {"op_ids": ids, "versions": created, "view": Ctx(v["id"], user["id"]).view()}


@api("/versions/{vid}/preview", ["POST"])
def start_preview(req, user, b):
    v = _own_version(user, req.path_params["vid"])
    ctx = Ctx(v["id"], user["id"])
    info = ctx.preview_info()
    if not info["url"] and not info["job"]:
        if not ctx.tl["clips"]:
            raise HTTPError(400, "Nothing on the timeline yet.")
        jobs.enqueue("preview", {"version_id": v["id"], "hash": ctx.preview_hash}, user["id"])
        info = ctx.preview_info()
    return info


@api("/versions/{vid}/preview/file", auth=False)
def preview_file(req, user, b):
    vid, h = req.path_params["vid"], req.query_params.get("h", "")
    uid = verify_media(req.query_params.get("token", ""), f"preview:{vid}:{h}")
    if not uid or not re.fullmatch(r"[0-9a-f]{16}", h):
        raise HTTPError(403, "Link expired — reload the page.")
    path = storage.user_dir(uid) / "previews" / f"{vid}_{h}.mp4"
    if not path.exists():
        raise HTTPError(404, "Preview not ready")
    return FileResponse(path, media_type="video/mp4", headers={"Cache-Control": "private, max-age=86400"})


@api("/versions/{vid}/qc", ["POST"])
def version_qc(req, user, b):
    from ..media import qc
    v = _own_version(user, req.path_params["vid"])
    ctx = Ctx(v["id"], user["id"])
    words = [{"media_id": mid, **w} for mid, ws in ctx.words_by_media.items() for w in ws]
    return qc.pre_export(ctx.tl, ctx.media_map, words, ctx.captions, ctx.settings, b.get("settings") or {}, ctx.plan, ctx.issues,
                         ctx.project.get("target_duration"))


@api("/versions/{vid}", ["PATCH"])
def rename_version(req, user, b):
    v = _own_version(user, req.path_params["vid"])
    if b.get("name"):
        db.update("versions", "id", v["id"], {"name": b["name"][:120]})
    return {"ok": True}


@api("/versions/{vid}", ["DELETE"])
def delete_version(req, user, b):
    v = _own_version(user, req.path_params["vid"])
    p = db.one("SELECT * FROM projects WHERE id=?", v["project_id"])
    if p["active_version_id"] == v["id"]:
        other = db.one("SELECT id FROM versions WHERE project_id=? AND id<>? ORDER BY created_at", p["id"], v["id"])
        if not other:
            raise HTTPError(400, "A project needs at least one version.")
        db.update("projects", "id", p["id"], {"active_version_id": other["id"]})
    db.execute("DELETE FROM ops WHERE version_id=?", v["id"])
    db.execute("DELETE FROM checkpoints WHERE version_id=?", v["id"])
    db.execute("DELETE FROM versions WHERE id=?", v["id"])
    return {"ok": True}


@api("/versions/{vid}/duplicate", ["POST"])
def duplicate_version(req, user, b):
    v = _own_version(user, req.path_params["vid"])
    nid = versions.create_version(v["project_id"], (b.get("name") or v["name"] + " copy")[:120], copy_from=v["id"], meta=v["meta"])
    return {"id": nid}


# ------------------------------------------------------------------ exports
@api("/versions/{vid}/exports", ["POST"])
def create_export(req, user, b):
    v = _own_version(user, req.path_params["vid"])
    s = b.get("settings") or {}
    settings = {"aspect": s.get("aspect", "9:16") if s.get("aspect") in ("9:16", "1:1", "16:9") else "9:16",
                "resolution": s.get("resolution", "1080p") if s.get("resolution") in ("720p", "1080p", "1440p", "4k") else "1080p",
                "fps": s.get("fps") if s.get("fps") in (24, 30, 60, "source") else 30,
                "quality": s.get("quality") if s.get("quality") in ("high", "balanced", "small") else "balanced"}
    limits = plan_limits(user["id"])
    from ..media.render import output_size
    W, H = output_size(settings["aspect"], settings["resolution"])
    if min(W, H) > limits["max_height"]:
        raise HTTPError(402, f"{settings['resolution']} export requires a higher plan.")
    eid = db.new_id("exp_")
    db.insert("exports", {"id": eid, "user_id": user["id"], "project_id": v["project_id"], "version_id": v["id"], "settings": settings,
                          "status": "queued", "name": v["name"], "created_at": db.now()})
    jid = jobs.enqueue("render", {"export_id": eid}, user["id"])
    db.update("exports", "id", eid, {"job_id": jid})
    return {"id": eid, "job_id": jid}


def _exports(user):
    rows = db.all_("SELECT e.*, p.name AS project_name FROM exports e LEFT JOIN projects p ON p.id=e.project_id WHERE e.user_id=? "
                   "ORDER BY e.created_at DESC LIMIT 100", user["id"])
    out = []
    for e in rows:
        j = db.one("SELECT progress, message, error FROM jobs WHERE id=?", e["job_id"]) if e["job_id"] else None
        out.append({"id": e["id"], "name": e["name"], "project_name": e["project_name"], "project_id": e["project_id"],
                    "version_id": e["version_id"], "settings": e["settings"], "status": e["status"], "qc": e["qc"],
                    "created_at": e["created_at"], "progress": (j or {}).get("progress", 0), "error": (j or {}).get("error"),
                    "download_url": f"/api/v1/exports/{e['id']}/download?token={sign_media(user['id'], e['id'])}" if e["status"] == "done" else None})
    return out


@api("/exports")
def list_exports(req, user, b):
    return _exports(user)


@api("/exports/{eid}", ["DELETE"])
def delete_export(req, user, b):
    e = db.one("SELECT * FROM exports WHERE id=? AND user_id=?", req.path_params["eid"], user["id"])
    if not e:
        raise HTTPError(404, "Export not found")
    if e["output_path"]:
        storage.abs(e["output_path"]).unlink(missing_ok=True)
    db.execute("DELETE FROM exports WHERE id=?", e["id"])
    return {"ok": True}


@api("/jobs/{jid}")
def get_job(req, user, b):
    j = db.one("SELECT id, kind, status, progress, message, error FROM jobs WHERE id=? AND user_id=?", req.path_params["jid"], user["id"])
    if not j:
        raise HTTPError(404, "Job not found")
    return j


# ------------------------------------------------------------------ products
PRODUCT_FIELDS = ["category", "price", "discount", "shipping", "url", "cta", "features", "benefits", "audience", "approved_claims",
                  "avoid_claims", "notes", "brand_requirements", "desired_length", "description", "photos", "claim_sources"]
LIST_FIELDS = {"features", "benefits", "approved_claims", "avoid_claims"}


def _product_out(p):
    if not p:
        return None
    d = p["data"] or {}
    photos = [{"path": ph, "url": f"/api/v1/products/{p['id']}/photo?path={ph}&token={sign_media(p['user_id'], ph)}"} for ph in d.get("photos", [])]
    broll = []
    for m in db.all_("SELECT id, filename, duration, status, thumb_path, info, error FROM media WHERE user_id=? AND kind='broll' ORDER BY created_at",
                     p["user_id"]):
        if (m["info"] or {}).get("product_id") == p["id"]:
            broll.append({"id": m["id"], "label": (m["info"] or {}).get("label") or m["filename"], "duration": m["duration"],
                          "status": m["status"], "error": m["error"],
                          "thumb_url": f"/api/v1/media/{m['id']}/thumb?token={sign_media(p['user_id'], m['id'])}" if m["thumb_path"] else None})
    return {"id": p["id"], "name": p["name"], **{k: d.get(k) for k in PRODUCT_FIELDS if k != "photos"}, "photos": photos, "broll": broll,
            "updated_at": p["updated_at"],
            "project_count": db.one("SELECT COUNT(*) AS n FROM projects WHERE product_id=?", p["id"])["n"]}


def _product_data(b, old=None):
    d = dict(old or {})
    for k in PRODUCT_FIELDS:
        if k in b and k != "photos":
            v = b[k]
            if k in LIST_FIELDS:
                v = [str(x).strip()[:300] for x in (v if isinstance(v, list) else str(v).split("\n")) if str(x).strip()][:40]
            elif isinstance(v, str):
                v = v.strip()[:2000]
            d[k] = v
    return d


@api("/products")
def list_products(req, user, b):
    return [_product_out(p) for p in db.all_("SELECT * FROM products WHERE user_id=? ORDER BY updated_at DESC", user["id"])]


@api("/products", ["POST"])
def create_product(req, user, b):
    name = (b.get("name") or "").strip()
    if not name:
        raise HTTPError(400, "Product name is required.")
    pid = db.new_id("prd_")
    db.insert("products", {"id": pid, "user_id": user["id"], "name": name[:120], "data": _product_data(b), "created_at": db.now(),
                           "updated_at": db.now()})
    return _product_out(db.one("SELECT * FROM products WHERE id=?", pid))


def _own_product(user, pid):
    p = db.one("SELECT * FROM products WHERE id=? AND user_id=?", pid, user["id"])
    if not p:
        raise HTTPError(404, "Product not found")
    return p


@api("/products/{pid}")
def get_product(req, user, b):
    return _product_out(_own_product(user, req.path_params["pid"]))


@api("/products/{pid}", ["PATCH"])
def patch_product(req, user, b):
    p = _own_product(user, req.path_params["pid"])
    f = {"data": _product_data(b, p["data"]), "updated_at": db.now()}
    if b.get("name"):
        f["name"] = b["name"].strip()[:120]
    db.update("products", "id", p["id"], f)
    return _product_out(db.one("SELECT * FROM products WHERE id=?", p["id"]))


@api("/products/{pid}", ["DELETE"])
def delete_product(req, user, b):
    p = _own_product(user, req.path_params["pid"])
    db.execute("UPDATE projects SET product_id=NULL WHERE product_id=?", p["id"])
    storage.delete_tree(storage.user_dir(user["id"]) / "products" / p["id"])
    db.execute("DELETE FROM products WHERE id=?", p["id"])
    return {"ok": True}


@api("/products/{pid}/photos", ["POST"])
async def upload_photo(req, user, b):
    p = _own_product(user, req.path_params["pid"])
    ext = Path(req.query_params.get("filename") or "photo.jpg").suffix.lower()
    if ext not in IMAGE_EXT:
        raise HTTPError(415, "Upload a JPG, PNG or WebP image.")
    data = await req.body()
    if not data or len(data) > 25 * 1024 * 1024:
        raise HTTPError(400, "Image empty or too large (25 MB max).")
    d = storage.product_dir(user["id"], p["id"])
    dest = d / f"{db.new_id('ph_')}{ext}"
    dest.write_bytes(data)
    if ext == ".heic":  # normalise iPhone HEIC → JPG for the detector
        from ..media.ffmpeg import run
        jpg = dest.with_suffix(".jpg")
        try:
            run(["-i", str(dest), str(jpg)])
            dest.unlink()
            dest = jpg
        except Exception:
            pass
    data_ = p["data"] or {}
    data_["photos"] = (data_.get("photos") or []) + [storage.rel(dest)]
    db.update("products", "id", p["id"], {"data": data_, "updated_at": db.now()})
    for pr in db.all_("SELECT id FROM projects WHERE product_id=?", p["id"]):
        jobs.enqueue("rescan", {"project_id": pr["id"]}, user["id"])
    return _product_out(db.one("SELECT * FROM products WHERE id=?", p["id"]))


@api("/products/{pid}/broll", ["POST", "PUT"])
async def upload_broll(req, user, b):
    """Product B-roll clip (close-ups, packaging, texture, results). Label it so Rushline can match it to what you say."""
    p = _own_product(user, req.path_params["pid"])
    filename = Path(req.query_params.get("filename") or "broll.mp4").name[:200]
    ext = Path(filename).suffix.lower() or ".mp4"
    if ext not in VIDEO_EXT:
        raise HTTPError(415, "Upload a video clip (mp4, mov).")
    mid = db.new_id("med_")
    d = storage.media_dir(user["id"], mid)
    dest = d / f"original{ext}"
    tmp = dest.with_suffix(ext + ".part")
    size = 0
    with open(tmp, "wb") as f:
        async for chunk in req.stream():
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                f.close(); tmp.unlink(missing_ok=True)
                raise HTTPError(413, "File too large.")
            f.write(chunk)
    if size == 0:
        tmp.unlink(missing_ok=True)
        raise HTTPError(400, "Empty upload.")
    tmp.rename(dest)
    label = (req.query_params.get("label") or Path(filename).stem.replace("_", " ").replace("-", " "))[:80]
    db.insert("media", {"id": mid, "user_id": user["id"], "project_id": None, "kind": "broll", "filename": filename,
                        "original_path": storage.rel(dest), "status": "uploaded", "info": {"product_id": p["id"], "label": label},
                        "position": 0, "created_at": db.now()})
    jobs.enqueue("ingest", {"media_id": mid}, user["id"])
    return _product_out(db.one("SELECT * FROM products WHERE id=?", p["id"]))


@api("/media/{mid}/label", ["PATCH"])
def label_media(req, user, b):
    m = db.one("SELECT * FROM media WHERE id=? AND user_id=?", req.path_params["mid"], user["id"])
    if not m:
        raise HTTPError(404, "Media not found")
    info = {**(m["info"] or {}), "label": str(b.get("label") or "")[:80]}
    db.update("media", "id", m["id"], {"info": info})
    return {"ok": True}


@api("/products/{pid}/photos", ["DELETE"])
def delete_photo(req, user, b):
    p = _own_product(user, req.path_params["pid"])
    path = req.query_params.get("path")
    data_ = p["data"] or {}
    if path in (data_.get("photos") or []):
        storage.abs(path).unlink(missing_ok=True)
        data_["photos"].remove(path)
        db.update("products", "id", p["id"], {"data": data_, "updated_at": db.now()})
    return _product_out(db.one("SELECT * FROM products WHERE id=?", p["id"]))


@api("/products/{pid}/photo", auth=False)
def product_photo(req, user, b):
    path = req.query_params.get("path", "")
    uid = verify_media(req.query_params.get("token", ""), path)
    p = db.one("SELECT * FROM products WHERE id=? AND user_id=?", req.path_params["pid"], uid) if uid else None
    if not p or path not in ((p["data"] or {}).get("photos") or []):
        raise HTTPError(403, "Forbidden")
    return FileResponse(storage.abs(path), headers={"Cache-Control": "private, max-age=3600"})


# ------------------------------------------------------------------ media
def _delete_media(user, m):
    storage.delete_tree(storage.user_dir(user["id"]) / "media" / m["id"])
    db.execute("DELETE FROM transcripts WHERE media_id=?", m["id"])
    db.execute("DELETE FROM media WHERE id=?", m["id"])


@api("/media")
def list_media(req, user, b):
    rows = db.all_("SELECT m.id, m.filename, m.duration, m.width, m.height, m.status, m.error, m.project_id, m.created_at, m.thumb_path, "
                   "p.name AS project_name, m.info FROM media m LEFT JOIN projects p ON p.id=m.project_id WHERE m.user_id=? "
                   "ORDER BY m.created_at DESC", user["id"])
    return [{**{k: r[k] for k in ("id", "filename", "duration", "width", "height", "status", "error", "project_id", "project_name", "created_at")},
             "size": (r["info"] or {}).get("size"),
             "thumb_url": f"/api/v1/media/{r['id']}/thumb?token={sign_media(user['id'], r['id'])}" if r["thumb_path"] else None} for r in rows]


@api("/media/{mid}", ["DELETE"])
def delete_media(req, user, b):
    m = db.one("SELECT * FROM media WHERE id=? AND user_id=?", req.path_params["mid"], user["id"])
    if not m:
        raise HTTPError(404, "Media not found")
    _delete_media(user, m)
    return {"ok": True}


@api("/media/{mid}/retry", ["POST"])
def retry_media(req, user, b):
    m = db.one("SELECT * FROM media WHERE id=? AND user_id=?", req.path_params["mid"], user["id"])
    if not m:
        raise HTTPError(404, "Media not found")
    db.update("media", "id", m["id"], {"status": "uploaded", "error": None})
    if m["project_id"]:
        db.update("projects", "id", m["project_id"], {"status": "processing"})
    return {"job_id": jobs.enqueue("ingest", {"media_id": m["id"]}, user["id"])}


@api("/media/{mid}/{variant}", auth=False)
def stream_media(req, user, b):
    mid, variant = req.path_params["mid"], req.path_params["variant"]
    uid = verify_media(req.query_params.get("token", ""), mid)
    m = db.one("SELECT * FROM media WHERE id=? AND user_id=?", mid, uid) if uid else None
    if not m:
        raise HTTPError(403, "Link expired — reload the page.")
    col = {"proxy": "proxy_path", "enhanced": "enhanced_path", "thumb": "thumb_path", "original": "original_path"}.get(variant)
    if not col or not m[col]:
        raise HTTPError(404, "Not available")
    path = storage.abs(m[col])
    headers = {"Cache-Control": "private, max-age=3600"}
    if variant == "original":
        headers["Content-Disposition"] = f'attachment; filename="{m["filename"]}"'
    return FileResponse(path, headers=headers, media_type="image/jpeg" if variant == "thumb" else "video/mp4")


@api("/exports/{eid}/download", auth=False)
def download_export(req, user, b):
    eid = req.path_params["eid"]
    uid = verify_media(req.query_params.get("token", ""), eid)
    e = db.one("SELECT * FROM exports WHERE id=? AND user_id=?", eid, uid) if uid else None
    if not e or e["status"] != "done":
        raise HTTPError(403, "Link expired — reload the page.")
    safe = re.sub(r"[^A-Za-z0-9 _.-]+", "", (e["name"] or "rushline")).strip()[:60] or "rushline"
    disp = "inline" if req.query_params.get("inline") else "attachment"
    return FileResponse(storage.abs(e["output_path"]), media_type="video/mp4",
                        headers={"Content-Disposition": f'{disp}; filename="{safe}.mp4"', "Cache-Control": "private"})


# ------------------------------------------------------------------ performance learning
def _perf_out(r):
    return {k: r[k] for k in ("id", "project_id", "version_id", "export_id", "title", "url", "posted_at", "metrics", "features", "created_at")}


@api("/performance")
def list_performance(req, user, b):
    from ..services import analytics
    rows = db.all_("SELECT * FROM performance WHERE user_id=? ORDER BY created_at DESC", user["id"])
    return {"entries": [_perf_out(r) for r in rows], "insights": analytics.insights(rows),
            "metrics": {k: v[0] for k, v in analytics.METRICS.items()}}


def _snapshot_for(user, version_id):
    from ..services import analytics
    if not version_id:
        return {}
    _own_version(user, version_id)
    return analytics.snapshot(Ctx(version_id, user["id"]))


@api("/performance", ["POST"])
def add_performance(req, user, b):
    from ..services import analytics
    version_id, project_id, export_id, title = b.get("version_id"), b.get("project_id"), b.get("export_id"), b.get("title")
    if export_id:
        e = db.one("SELECT * FROM exports WHERE id=? AND user_id=?", export_id, user["id"])
        if not e:
            raise HTTPError(404, "Export not found")
        version_id, project_id, title = e["version_id"], e["project_id"], title or e["name"]
    metrics = analytics.clean_metrics(b.get("metrics") or {})
    if not metrics:
        raise HTTPError(400, "Enter at least one number (views, clicks, orders…).")
    pid = db.new_id("perf_")
    db.insert("performance", {"id": pid, "user_id": user["id"], "project_id": project_id, "version_id": version_id, "export_id": export_id,
                              "title": (title or "Untitled video")[:200], "url": (b.get("url") or "")[:500], "posted_at": (b.get("posted_at") or "")[:40],
                              "metrics": metrics, "features": _snapshot_for(user, version_id) if version_id else {}, "created_at": db.now()})
    return _perf_out(db.one("SELECT * FROM performance WHERE id=?", pid))


@api("/performance/{id}", ["PATCH"])
def patch_performance(req, user, b):
    from ..services import analytics
    r = db.one("SELECT * FROM performance WHERE id=? AND user_id=?", req.path_params["id"], user["id"])
    if not r:
        raise HTTPError(404, "Not found")
    f = {}
    if "metrics" in b:
        f["metrics"] = {**(r["metrics"] or {}), **analytics.clean_metrics(b["metrics"])}
    for k in ("title", "url", "posted_at"):
        if k in b:
            f[k] = str(b[k] or "")[:500]
    if b.get("version_id"):
        f["version_id"] = b["version_id"]
        f["features"] = _snapshot_for(user, b["version_id"])
        f["project_id"] = db.one("SELECT project_id FROM versions WHERE id=?", b["version_id"])["project_id"]
    db.update("performance", "id", r["id"], f)
    return _perf_out(db.one("SELECT * FROM performance WHERE id=?", r["id"]))


@api("/performance/{id}", ["DELETE"])
def delete_performance(req, user, b):
    db.execute("DELETE FROM performance WHERE id=? AND user_id=?", req.path_params["id"], user["id"])
    return {"ok": True}


@api("/performance/import", ["POST"])
async def import_performance(req, user, b):
    from ..services import analytics
    raw = (await req.body()).decode("utf-8-sig", errors="replace")
    rows = analytics.parse_csv(raw)
    if not rows:
        raise HTTPError(400, "Couldn't find any metric columns (views, likes, orders, GMV…) in that file.")
    for r in rows[:500]:
        db.insert("performance", {"id": db.new_id("perf_"), "user_id": user["id"], "title": r.get("title") or "Imported video",
                                  "url": r.get("url", ""), "posted_at": r.get("posted_at", ""), "metrics": r["metrics"], "features": {},
                                  "created_at": db.now()})
    return {"imported": min(len(rows), 500)}


# ------------------------------------------------------------------ account
@api("/account", ["PATCH"])
def patch_account(req, user, b):
    f = {}
    if "name" in b:
        f["name"] = str(b["name"])[:80]
    if b.get("new_password"):
        if not verify_password(b.get("password") or "", user["password_hash"]):
            raise HTTPError(403, "Current password is incorrect.")
        if len(b["new_password"]) < 8:
            raise HTTPError(400, "Password must be at least 8 characters.")
        f["password_hash"] = hash_password(b["new_password"])
    db.update("users", "id", user["id"], f)
    return _user_out(db.one("SELECT * FROM users WHERE id=?", user["id"]))


@api("/account", ["DELETE"])
def delete_account(req, user, b):
    if not verify_password(b.get("password") or "", user["password_hash"]):
        raise HTTPError(403, "Password is incorrect.")
    uid = user["id"]
    for v in db.all_("SELECT v.id FROM versions v JOIN projects p ON p.id=v.project_id WHERE p.user_id=?", uid):
        db.execute("DELETE FROM ops WHERE version_id=?", v["id"])
        db.execute("DELETE FROM checkpoints WHERE version_id=?", v["id"])
        db.execute("DELETE FROM versions WHERE id=?", v["id"])
    for m in db.all_("SELECT id FROM media WHERE user_id=?", uid):
        db.execute("DELETE FROM transcripts WHERE media_id=?", m["id"])
    for t in ("media", "projects", "products", "exports", "jobs", "usage", "performance"):
        db.execute(f"DELETE FROM {t} WHERE user_id=?", uid)
    db.execute("DELETE FROM users WHERE id=?", uid)
    storage.delete_tree(storage.user_dir(uid))
    return {"ok": True}
