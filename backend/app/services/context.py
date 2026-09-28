"""Loads everything needed to reason about one version, and builds the editor view (timeline + AI insights)."""
from __future__ import annotations

from functools import cached_property

from .. import db
from ..ai import compliance, structure
from ..ai.text import build_sentences, filler_indices, norm, tokens
from ..config import PLANS
from ..media.captions import PRESETS, layout
from ..security import sign_media
from ..storage import storage
from ..timeline import caption_words, map_range, replay, word_states


class NotFound(Exception):
    pass


class Ctx:
    def __init__(self, version_id: str, user_id: str, extra_ops: list[dict] | None = None, disabled: set | None = None):
        v = db.one("SELECT * FROM versions WHERE id=?", version_id)
        if not v:
            raise NotFound("version")
        p = db.one("SELECT * FROM projects WHERE id=? AND user_id=?", v["project_id"], user_id)
        if not p:
            raise NotFound("project")
        self.user_id = user_id
        self.version = v
        self.project = p
        self.product = db.one("SELECT * FROM products WHERE id=? AND user_id=?", p["product_id"], user_id) if p["product_id"] else None
        self.media = db.all_("SELECT * FROM media WHERE project_id=? AND user_id=? ORDER BY position, created_at", p["id"], user_id)
        self.media_map = {m["id"]: m for m in self.media}
        for m in self.media:
            m["abs_original"] = str(storage.abs(m["original_path"]))
        self.words_by_media: dict[str, list[dict]] = {}
        ids = [m["id"] for m in self.media]
        if ids:
            for t in db.all_(f"SELECT media_id, words FROM transcripts WHERE media_id IN ({db.placeholders(ids)})", *ids):
                self.words_by_media[t["media_id"]] = t["words"]
        for mid in ids:
            self.words_by_media.setdefault(mid, [])
        self.analysis = {m["id"]: m["analysis"] or {} for m in self.media}
        for m in self.media:  # older uploads: compute speech gaps once from the stored audio
            an = self.analysis[m["id"]]
            if m["status"] == "ready" and ("gaps" not in an or "soft_gaps" not in an) and m.get("audio_path"):
                try:
                    from ..media.analysis import speech_gaps
                    an["gaps"] = speech_gaps(storage.abs(m["audio_path"]))
                    an["soft_gaps"] = speech_gaps(storage.abs(m["audio_path"]), strict=True)
                    db.update("media", "id", m["id"], {"analysis": an})
                except Exception:
                    an["gaps"] = []
        from ..ai.align import align_words
        from ..ai.text import refine_words
        for mid in ids:
            an = self.analysis.get(mid, {})
            dur = float(self.media_map[mid].get("duration") or 0)
            if an.get("gaps") and dur:
                # re-time ASR words against the real audio so cuts never land inside a word
                # (strict gaps: clicks/breaths aren't candidate word positions)
                self.words_by_media[mid] = align_words(self.words_by_media[mid], an.get("soft_gaps") or an["gaps"], dur)
            else:
                self.words_by_media[mid] = refine_words(self.words_by_media[mid], an.get("silences", []))
        self._mark_fillers()
        self.ops = db.all_("SELECT * FROM ops WHERE version_id=? ORDER BY seq", version_id)
        if disabled:
            for o in self.ops:
                if o["id"] in disabled:
                    o["enabled"] = 0
        self.extra = []
        for n, o in enumerate(extra_ops or []):
            self.extra.append({"id": f"plan_{n}", "kind": o["kind"], "params": o["params"], "enabled": 1, "label": o.get("label", "")})
        self.ready_media = [m for m in self.media if m["status"] == "ready"]
        self.tl = replay(self.ready_media, self.words_by_media, self.ops + self.extra)
        vset = self.tl["settings"].get("video", {})
        if vset.get("smooth_cuts", False):
            from ..timeline import smooth_cuts
            self.tl["clips"] = smooth_cuts(self.tl["clips"], float(vset.get("smooth_zoom", 1.08)))

    def with_ops(self, extra: list[dict], disabled: set | None = None) -> "Ctx":
        return Ctx(self.version["id"], self.user_id, [*[{"kind": o["kind"], "params": o["params"]} for o in self.extra], *extra],
                   disabled)

    def _mark_fillers(self):
        for mid, words in self.words_by_media.items():
            idx = {i for g in filler_indices(words, aggressive=False, remove_like=True) for i in g}
            for n, w in enumerate(words):
                w["filler"] = n in idx

    @property
    def settings(self) -> dict:
        return self.tl["settings"]

    @property
    def plan(self) -> dict:
        u = db.one("SELECT plan FROM users WHERE id=?", self.user_id)
        return PLANS.get((u or {}).get("plan", "creator"), PLANS["creator"])

    # ---------------------------------------------------------------- analysis
    @cached_property
    def sentences(self) -> list[dict]:
        out = []
        for m in self.ready_media:
            ss = build_sentences(m["id"], self.words_by_media.get(m["id"], []), float(m["duration"] or 0))
            for k, s in enumerate(ss):
                s["first_in_media"] = k == 0 or (k == 1 and not ss[0]["speech"])
            out += ss
        return out

    @cached_property
    def product_intervals(self) -> dict[str, list[tuple[float, float, float]]]:
        """media_id → [(s, e, area)] where the product is visible (detector hits + manual tags − manual untags)."""
        out: dict[str, list] = {}
        for m in self.ready_media:
            an = self.analysis.get(m["id"], {})
            half = 0.5 / float(an.get("sample_fps", 2) or 2) + 0.05
            iv = []
            for t, score, area in an.get("product_hits", []):
                s, e = max(0, t - half), t + half
                if iv and s <= iv[-1][1] + 0.3:
                    iv[-1] = [iv[-1][0], e, max(iv[-1][2], area)]
                else:
                    iv.append([s, e, area])
            for a, b, _ in self.tl["tags"].get(m["id"]):
                iv.append([a, b, 0.0])
            iv.sort()
            for a, b, _ in self.tl["untags"].get(m["id"]):
                nxt = []
                for s, e, ar in iv:
                    if e <= a or s >= b:
                        nxt.append([s, e, ar]); continue
                    if s < a:
                        nxt.append([s, a, ar])
                    if e > b:
                        nxt.append([b, e, ar])
                iv = nxt
            out[m["id"]] = [tuple(x) for x in iv]
        return out

    def sentence_visible(self, s: dict) -> bool:
        return any(a < s["e"] and b > s["s"] and min(b, s["e"]) - max(a, s["s"]) > 0.4
                   for a, b, _ in self.product_intervals.get(s["media_id"], []))

    @cached_property
    def labelled(self) -> list[dict]:
        vis = {s["id"]: self.sentence_visible(s) for s in self.sentences}
        lab = structure.classify(self.sentences, self.product, vis)
        overrides = (self.project.get("settings") or {}).get("section_overrides", {})
        llm_labels = (self.project.get("settings") or {}).get("llm_sections", {})
        for s in lab:
            s["visible"] = vis.get(s["id"], False)
            if s["id"] in llm_labels:
                s["section"] = llm_labels[s["id"]]
            if s["id"] in overrides:
                s["section"] = overrides[s["id"]]
                s["confidence"] = 1.0
        return lab

    @cached_property
    def label_by_id(self) -> dict[str, dict]:
        return {s["id"]: s for s in self.labelled}

    @cached_property
    def unit_rows(self) -> list[dict]:
        """Kept units in timeline order with timeline span, section and kept text."""
        rows: dict[str, dict] = {}
        order = []
        for c in self.tl["clips"]:
            r = rows.get(c["unit_id"])
            if r is None:
                lab = self.label_by_id.get(c["origin"], {})
                r = rows[c["unit_id"]] = {"unit_id": c["unit_id"], "origin": c["origin"], "media_id": c["media_id"],
                                          "t0": c["t0"], "t1": c["t1"], "s": c["s"], "e": c["e"],
                                          "section": lab.get("section", "other"), "hook": lab.get("hook"),
                                          "speech": lab.get("speech", True), "visible": lab.get("visible", False), "words": []}
                order.append(c["unit_id"])
            r["t1"] = c["t1"]
            r["e"] = max(r["e"], c["e"])
            for w in self.words_by_media.get(c["media_id"], []):
                if c["s"] <= (w["s"] + w["e"]) / 2 < c["e"]:
                    r["words"].append(w["t"].strip())
        out = []
        for uid in order:
            r = rows[uid]
            r["text"] = " ".join(r.pop("words"))
            out.append(r)
        return out

    @cached_property
    def captions(self) -> list[dict]:
        style = self.caption_style
        cw = caption_words(self.tl["clips"], self.words_by_media, self.tl["caption_over"])
        flagged = set()
        issue_texts = [i["text"] for i in self.issues]
        if issue_texts:
            for u in self.unit_rows:
                if u["text"] in issue_texts:
                    for w in cw:
                        if u["t0"] <= w["t0"] < u["t1"]:
                            flagged.add(w["key"])
        return layout(cw, style, flagged)

    @property
    def caption_style(self) -> dict:
        cap = dict(self.settings.get("captions", {}))
        preset = PRESETS.get(cap.get("preset", "tiktok"), {})
        # preset supplies defaults; explicit user overrides (stored under 'custom') win
        return {**cap, **{k: v for k, v in preset.items() if k != "label"}, **cap.get("custom", {})}

    @cached_property
    def issues(self) -> list[dict]:
        items = [{"text": u["text"], "t0": u["t0"], "where": "speech", "ref": u["unit_id"]} for u in self.unit_rows if u["text"]]
        items += [{"text": o.get("text", ""), "t0": o.get("t0"), "where": "text", "ref": o["id"]} for o in self.overlays_tl]
        return compliance.scan(items, self.product)

    # ---------------------------------------------------------------- growth features
    @cached_property
    def overlays_tl(self) -> list[dict]:
        return self._overlays_on_timeline()

    @cached_property
    def view_words(self) -> list[dict]:
        return word_states(self.tl["clips"], self.words_by_media, self.tl["removed"])

    @cached_property
    def broll_library(self) -> list[dict]:
        from .features import broll_library
        return broll_library(self)

    @cached_property
    def brolls(self) -> list[dict]:
        from .features import brolls_on_timeline
        return brolls_on_timeline(self)

    @cached_property
    def retention(self) -> dict:
        from .features import retention
        return retention(self)

    @cached_property
    def pieces(self) -> dict:
        from .features import ad_pieces
        return ad_pieces(self)

    @cached_property
    def text_hook_ideas(self) -> list[dict]:
        from .features import text_hook_ideas
        return text_hook_ideas(self)

    @cached_property
    def visibility(self) -> dict:
        has_data = any(self.analysis.get(m["id"], {}).get("product_scanned") for m in self.ready_media) or \
            any(self.tl["tags"].get(m["id"]) for m in self.ready_media)
        segs = []
        close = 0
        for mid, ivs in self.product_intervals.items():
            for s, e, area in ivs:
                for a, b in map_range(self.tl["clips"], mid, s, e):
                    segs.append([a, b])
                    if area >= 0.2:
                        close += 1
        from .features import brolls_on_timeline
        for b in brolls_on_timeline(self):
            segs.append([b["t0"], b["t1"]])
        has_data = has_data or bool(segs)
        segs.sort()
        merged: list[list[float]] = []
        for a, b in segs:
            if merged and a <= merged[-1][1] + 0.05:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        D = self.tl["duration"]
        total = sum(b - a for a, b in merged)
        gaps = []
        prev = 0.0
        for a, b in merged:
            gaps.append(a - prev); prev = b
        gaps.append(D - prev)
        mentions = []
        if self.product:
            name = [t for t in tokens(self.product["name"]) if len(t) > 2][:2]
            for u in self.unit_rows:
                if name and any(t in tokens(u["text"]) for t in name):
                    mentions.append(round(u["t0"], 2))
        return {"tracked": has_data, "segments": [[round(a, 2), round(b, 2)] for a, b in merged],
                "first": round(merged[0][0], 2) if merged else None, "total": round(total, 2),
                "percent": round(100 * total / D, 1) if D else 0, "longest_gap": round(max(gaps), 2) if merged else round(D, 2),
                "closeups": close, "mentions": mentions}

    @cached_property
    def hooks(self) -> list[dict]:
        cands = structure.find_hooks(self.labelled)
        first = self.unit_rows[0]["origin"] if self.unit_rows else None
        kept = {u["origin"] for u in self.unit_rows}
        for c in cands:
            c["in_use"] = c["id"] == first
            c["kept"] = c["id"] in kept
        return cands

    def diagnostics(self) -> list[dict]:
        return structure.diagnostics(self.unit_rows, self.tl["duration"], self.project.get("target_duration"),
                                     self.visibility if self.visibility["tracked"] else None)

    # ---------------------------------------------------------------- view
    def view(self) -> dict:
        tl = self.tl
        media = []
        for m in self.media:
            tok = sign_media(self.user_id, m["id"])
            an = m["analysis"] or {}
            media.append({k: m[k] for k in ("id", "filename", "duration", "width", "height", "fps", "has_audio", "status", "error", "kind")}
                         | {"proxy_url": f"/api/v1/media/{m['id']}/proxy?token={tok}" if m["proxy_path"] else None,
                            "enhanced_url": f"/api/v1/media/{m['id']}/enhanced?token={tok}" if m["enhanced_path"] else None,
                            "thumb_url": f"/api/v1/media/{m['id']}/thumb?token={tok}" if m["thumb_path"] else None,
                            "original_url": f"/api/v1/media/{m['id']}/original?token={tok}",
                            "envelope": an.get("envelope", []), "warning": an.get("warning"),
                            "product_scanned": an.get("product_scanned", False)})
        clips = []
        for c in tl["clips"]:
            lab = self.label_by_id.get(c["origin"], {})
            clips.append({**c, "section": lab.get("section", "other")})
        sections = []
        for u in self.unit_rows:
            if sections and sections[-1]["section"] == u["section"]:
                sections[-1]["t1"] = u["t1"]
                sections[-1]["units"].append(u["unit_id"])
            else:
                sections.append({"section": u["section"], "label": structure.SECTION_LABELS.get(u["section"], u["section"]),
                                 "t0": u["t0"], "t1": u["t1"], "units": [u["unit_id"]]})
        present = {s["section"] for s in sections}
        ops = [{k: o[k] for k in ("id", "seq", "kind", "label", "source", "enabled", "group_id", "created_at")} | {"params": o["params"]}
               for o in self.ops]
        return {
            "version": {k: self.version[k] for k in ("id", "name", "meta", "project_id")},
            "media": media,
            "timeline": {"clips": clips, "duration": tl["duration"], "units": [
                {"id": u["id"], "media_id": u["media_id"], "s": u["s"], "e": u["e"], "origin": u["origin"]} for u in tl["units"]]},
            "words": self.view_words,
            "sentences": [{k: s.get(k) for k in ("id", "media_id", "s", "e", "ws", "we", "text", "section", "confidence", "visible", "speech")}
                          | {"hook_score": (s.get("hook") or {}).get("score", 0)} for s in self.labelled],
            "captions": self.captions, "caption_style": self.caption_style, "settings": self.settings,
            "overlays": self.overlays_tl,
            "sections": sections, "missing_sections": [s for s in ("hook", "problem", "product_intro", "benefit", "demonstration", "cta")
                                                       if s not in present],
            "hooks": self.hooks, "diagnostics": self.diagnostics(), "visibility": self.visibility, "compliance": self.issues,
            "history": ops, "checkpoints": db.all_("SELECT id,label,created_at FROM checkpoints WHERE version_id=? ORDER BY created_at DESC LIMIT 30",
                                                   self.version["id"]),
            "skipped_ops": tl["skipped"],
            "preview": self.preview_info(),
            "brolls": [{k: b[k] for k in ("id", "t0", "t1", "label", "type", "thumb_url", "source_id")} for b in self.brolls],
            "broll_library": [{k: b[k] for k in ("id", "type", "label", "duration", "thumb_url")} for b in self.broll_library],
            "text_hook_ideas": self.text_hook_ideas,
            "retention": self.retention,
            "pieces": self.pieces,
            "shop_safe": compliance.summary(self.issues),
            "learned": self.learned,
        }

    @cached_property
    def learned(self) -> list[dict]:
        try:
            from .analytics import insights_for_user
            return insights_for_user(self.user_id)[:4]
        except Exception:
            return []

    @cached_property
    def preview_hash(self) -> str:
        """Fingerprint of everything that changes the rendered picture/sound (cuts, clip props, captions, style)."""
        import hashlib
        import json as _json
        key = {"clips": [[c["media_id"], c["s"], c["e"], c["speed"], c["props"]] for c in self.tl["clips"]],
               "settings": self.settings, "captions": self.captions if self.caption_style.get("enabled", True) else [],
               "style": self.caption_style, "overlays": self.overlays_tl,
               "brolls": [[b["source_id"], b["t0"], b["t1"], b["src_in"]] for b in self.brolls], "v": 4}
        return hashlib.sha1(_json.dumps(key, sort_keys=True, default=str).encode()).hexdigest()[:16]

    def preview_path(self):
        d = storage.user_dir(self.user_id) / "previews"
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{self.version['id']}_{self.preview_hash}.mp4"

    def preview_info(self) -> dict:
        p = self.preview_path()
        url = None
        if p.exists():
            res = f"preview:{self.version['id']}:{self.preview_hash}"
            url = f"/api/v1/versions/{self.version['id']}/preview/file?h={self.preview_hash}&token={sign_media(self.user_id, res)}"
        job = db.one("SELECT id, status, progress FROM jobs WHERE kind='preview' AND status IN ('queued','running') AND payload LIKE ? "
                     "ORDER BY created_at DESC LIMIT 1", f'%"{self.preview_hash}"%')
        return {"hash": self.preview_hash, "url": url, "job": job}

    def _overlays_on_timeline(self) -> list[dict]:
        out = []
        for o in self.tl["overlays"]:
            pieces = map_range(self.tl["clips"], o["media_id"], float(o["t"]), float(o["t"]) + float(o.get("dur", 2)))
            if pieces:
                out.append({**o, "t0": round(pieces[0][0], 3), "t1": round(pieces[-1][1], 3)})
        return out

    def source_sentence_text(self, sid: str) -> str:
        return self.label_by_id.get(sid, {}).get("text", "")


def norm_text(t: str) -> str:
    return norm(t)
