"""Background job handlers: ingest → proxy → audio → transcribe → visual/product analysis → AI first pass; render; enhance."""
from __future__ import annotations

import time
from pathlib import Path

from .. import db, jobs
from ..ai import llm
from ..ai.transcribe import TranscriptionUnavailable, transcribe
from ..config import PLANS
from ..media import analysis as an
from ..media import proxy as px
from ..media import qc
from ..media.ffmpeg import MediaError, probe
from ..media.render import render
from ..storage import storage
from . import plans, versions
from .context import Ctx


def _media(mid: str) -> dict:
    m = db.one("SELECT * FROM media WHERE id=?", mid)
    if not m:
        raise jobs.PermanentError("media deleted")
    return m


def _usage(user_id: str, seconds: float = 0, exports: int = 0) -> None:
    period = time.strftime("%Y-%m")
    db.execute("INSERT INTO usage (user_id, period, processing_seconds, exports) VALUES (?,?,?,?) "
               "ON CONFLICT(user_id, period) DO UPDATE SET processing_seconds=processing_seconds+excluded.processing_seconds, "
               "exports=exports+excluded.exports", user_id, period, seconds, exports)


def ingest(job: dict) -> dict:
    m = _media(job["payload"]["media_id"])
    src = storage.abs(m["original_path"])
    d = src.parent
    try:
        info = probe(src)
    except MediaError as e:
        raise jobs.PermanentError(str(e))
    if not info["has_video"]:
        raise jobs.PermanentError("This file has no video track.")
    if info["duration"] <= 0:
        raise jobs.PermanentError("Could not read the duration of this file.")
    db.update("media", "id", m["id"], {"duration": info["duration"], "width": info.get("width"), "height": info.get("height"),
                                        "fps": info.get("fps"), "has_audio": int(info["has_audio"]), "info": {**(m["info"] or {}), **info},
                                        "status": "processing"})
    proxy = d / "proxy.mp4"
    px.make_proxy(src, proxy, info, progress=lambda p: jobs.progress(job["id"], 0.05 + p * 0.6, "Creating edit proxy"))
    px.make_thumb(proxy, d / "thumb.jpg", info["duration"])
    wav = d / "audio16k.wav"
    if info["has_audio"]:
        px.make_audio_wav(src, wav, info["duration"])
    else:
        px.make_silent_wav(wav, info["duration"])
    jobs.progress(job["id"], 0.8, "Analyzing audio")
    audio = an.audio_analysis(wav)
    db.update("media", "id", m["id"], {"proxy_path": storage.rel(proxy), "thumb_path": storage.rel(d / "thumb.jpg"),
                                        "audio_path": storage.rel(wav), "analysis": audio, "status": "transcribing"})
    _usage(m["user_id"], seconds=info["duration"])
    if m["kind"] == "broll":
        db.update("media", "id", m["id"], {"status": "ready"})
        return {"duration": info["duration"], "broll": True}
    jobs.enqueue("transcribe", {"media_id": m["id"]}, m["user_id"])
    return {"duration": info["duration"]}


def _prompt_terms(m: dict) -> str:
    p = db.one("SELECT pr.name, pr.data FROM projects pj JOIN products pr ON pr.id=pj.product_id WHERE pj.id=?", m["project_id"])
    if not p:
        return ""
    d = p["data"] or {}
    return (p["name"] + ". " + ", ".join((d.get("features") or [])[:5]))[:400]


def transcribe_job(job: dict) -> dict:
    m = _media(job["payload"]["media_id"])
    wav = storage.abs(m["audio_path"])
    jobs.progress(job["id"], 0.1, "Transcribing speech")
    analysis = m["analysis"] or {}
    try:
        words, lang, provider = transcribe(wav, wav.parent, _prompt_terms(m))
    except TranscriptionUnavailable as e:
        words, lang, provider = [], None, "none"
        analysis["warning"] = str(e)
    db.execute("INSERT OR REPLACE INTO transcripts (media_id, provider, language, words, created_at) VALUES (?,?,?,?,?)",
               m["id"], provider, lang, words, db.now())
    db.update("media", "id", m["id"], {"status": "analyzing", "analysis": analysis})
    jobs.enqueue("analyze", {"media_id": m["id"]}, m["user_id"])
    return {"words": len(words), "provider": provider}


def _product_photos(project_id: str | None) -> list[Path]:
    if not project_id:
        return []
    p = db.one("SELECT pr.data FROM projects pj JOIN products pr ON pr.id=pj.product_id WHERE pj.id=?", project_id)
    if not p:
        return []
    return [storage.abs(ph) for ph in (p["data"] or {}).get("photos", []) if storage.abs(ph).exists()]


def analyze(job: dict) -> dict:
    m = _media(job["payload"]["media_id"])
    src = storage.abs(m["proxy_path"])
    photos = _product_photos(m["project_id"])
    vis = an.visual_analysis(src, float(m["duration"]), photos, progress=lambda p: jobs.progress(job["id"], p * 0.95, "Scanning footage"))
    analysis = {**(m["analysis"] or {}), **vis}
    db.update("media", "id", m["id"], {"analysis": analysis, "status": "ready"})
    if m["project_id"]:
        maybe_first_pass(m["project_id"])
    return {"product_hits": len(vis["product_hits"])}


def maybe_first_pass(project_id: str) -> None:
    p = db.one("SELECT * FROM projects WHERE id=?", project_id)
    if not p:
        return
    pending = db.one("SELECT COUNT(*) AS n FROM media WHERE project_id=? AND status NOT IN ('ready','failed')", project_id)["n"]
    if pending:
        return
    settings = p["settings"] or {}
    if p["status"] != "processing":
        return
    db.update("projects", "id", project_id, {"status": "ready", "updated_at": db.now()})
    if not settings.get("auto_first_pass", True):
        return
    vid = p["active_version_id"]
    ctx = Ctx(vid, p["user_id"])
    if llm.available():
        labels = llm.refine_sections(ctx.labelled, ctx.product)
        if labels:
            db.update("projects", "id", project_id, {"settings": {**settings, "llm_sections": labels}})
            ctx = Ctx(vid, p["user_id"])
    # The main edit only gets non-structural cleanup (safe, reviewable in history). Structural changes
    # (restructure / trimming to length) go into separate ad versions, or are offered as recommendations.
    first = plans.build(ctx, "ai_edit", {"strength": p["strength"]})
    versions.apply_plan(ctx, first["steps"], "AI first pass (cleanup)", "ai")
    if settings.get("generate_ads"):
        ctx = Ctx(vid, p["user_id"])
        specs = plans.variation_specs(ctx, int(settings.get("ad_count", 3)))
        versions.create_variations(ctx, specs)


def rescan(job: dict) -> dict:
    """Re-run product/visual analysis after product photos change."""
    ms = db.all_("SELECT id FROM media WHERE project_id=? AND status='ready'", job["payload"]["project_id"])
    for m in ms:
        jobs.enqueue("analyze", {"media_id": m["id"]}, job["user_id"])
    return {"media": len(ms)}


def enhance_audio(job: dict) -> dict:
    m = _media(job["payload"]["media_id"])
    if not m["has_audio"]:
        return {}
    proxy = storage.abs(m["proxy_path"])
    dst = proxy.parent / "proxy_enhanced.mp4"
    px.make_enhanced_proxy(proxy, dst, {"denoise": 0.6, "target_lufs": -14})
    db.update("media", "id", m["id"], {"enhanced_path": storage.rel(dst)})
    return {}


def render_job(job: dict) -> dict:
    ex = db.one("SELECT * FROM exports WHERE id=?", job["payload"]["export_id"])
    if not ex:
        raise jobs.PermanentError("export deleted")
    db.update("exports", "id", ex["id"], {"status": "rendering"})
    ctx = Ctx(ex["version_id"], ex["user_id"])
    settings = ex["settings"]
    words = [{"media_id": mid, **w} for mid, ws in ctx.words_by_media.items() for w in ws]
    pre = qc.pre_export(ctx.tl, ctx.media_map, words, ctx.captions, ctx.settings, settings, ctx.plan, ctx.issues,
                        ctx.project.get("target_duration"))
    if pre["status"] == "fail":
        db.update("exports", "id", ex["id"], {"status": "failed", "qc": {"pre": pre}})
        raise jobs.PermanentError("Pre-export quality check failed")
    out = storage.export_path(ex["user_id"], ex["id"])
    brolls = [{"t0": b["t0"], "t1": b["t1"], "type": b["type"], "path": b["abs"], "src_in": b["src_in"]} for b in ctx.brolls]
    for b in brolls:
        if not Path(b["path"]).exists():
            raise jobs.PermanentError("A B-roll clip used in this edit was deleted.")
    res = render(ctx.tl, ctx.media_map, ctx.settings, settings, ctx.captions,
                 ctx.overlays_tl, out, watermark=ctx.plan.get("watermark", False),
                 progress=lambda p: jobs.progress(job["id"], p * 0.92, "Rendering"), brolls=brolls)
    jobs.progress(job["id"], 0.95, "Checking output")
    post = qc.post_render(res["part"], res["expected_duration"], res["width"], res["height"], res["fps"])
    if post["status"] == "fail":
        res["part"].unlink(missing_ok=True)
        db.update("exports", "id", ex["id"], {"status": "failed", "qc": {"pre": pre, "post": post}})
        raise jobs.PermanentError("Rendered file failed verification: " + "; ".join(i["message"] for i in post["items"] if i["level"] == "fail"))
    res["part"].replace(out)
    db.update("exports", "id", ex["id"], {"status": "done", "output_path": storage.rel(out), "qc": {"pre": pre, "post": post}})
    _usage(ex["user_id"], exports=1)
    return {"duration": post["duration"]}


def preview_job(job: dict) -> dict:
    """Fast 540p render of the current edit from the proxies, so the creator can watch exactly what the export
    will look like (seamless cuts, captions, audio) without the live player jumping between clips."""
    pl = job["payload"]
    ctx = Ctx(pl["version_id"], job["user_id"])
    if ctx.preview_hash != pl["hash"]:
        return {"stale": True}  # the edit changed while queued; a newer preview job will be requested
    out = ctx.preview_path()
    if out.exists():
        return {"cached": True}
    media_map = {}
    for mid, m in ctx.media_map.items():
        if not m.get("proxy_path"):
            raise jobs.PermanentError("Preview needs processed footage")
        mm = dict(m)
        mm["abs_original"] = str(storage.abs(m["proxy_path"]))
        mm["info"] = {**(m.get("info") or {}), "hdr": False}  # proxies are already SDR
        media_map[mid] = mm
    for old in out.parent.glob(f"{ctx.version['id']}_*.mp4"):
        old.unlink(missing_ok=True)  # keep only the newest preview per version
    res = render(ctx.tl, media_map, ctx.settings, {"aspect": ctx.settings.get("output", {}).get("aspect", "9:16"), "resolution": "540p",
                                                   "fps": 30, "quality": "preview"},
                 ctx.captions, ctx.overlays_tl, out, watermark=False,
                 progress=lambda p: jobs.progress(job["id"], p, "Rendering preview"),
                 brolls=[{"t0": b["t0"], "t1": b["t1"], "type": b["type"], "path": b["proxy_abs"] or b["abs"], "src_in": b["src_in"]}
                         for b in ctx.brolls])
    res["part"].replace(out)
    return {"path": storage.rel(out)}


HANDLERS = {"ingest": ingest, "transcribe": transcribe_job, "analyze": analyze, "rescan": rescan, "enhance_audio": enhance_audio,
            "render": render_job, "preview": preview_job}


def on_failed(job: dict, error: str) -> None:
    p = job["payload"]
    if "media_id" in p:
        db.update("media", "id", p["media_id"], {"status": "failed", "error": error[:500]})
        m = db.one("SELECT project_id FROM media WHERE id=?", p["media_id"])
        if m and m["project_id"]:
            maybe_first_pass(m["project_id"])
    if "export_id" in p:
        ex = db.one("SELECT status FROM exports WHERE id=?", p["export_id"])
        if ex and ex["status"] != "failed":
            db.update("exports", "id", p["export_id"], {"status": "failed"})


def plan_limits(user_id: str) -> dict:
    u = db.one("SELECT plan FROM users WHERE id=?", user_id)
    plan = PLANS.get((u or {}).get("plan", "creator"), PLANS["creator"])
    use = db.one("SELECT * FROM usage WHERE user_id=? AND period=?", user_id, time.strftime("%Y-%m")) or {"processing_seconds": 0, "exports": 0}
    return {"plan": (u or {}).get("plan"), **plan, "used_minutes": round(use["processing_seconds"] / 60, 1), "exports": use["exports"]}
