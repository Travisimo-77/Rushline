"""Quality checks before and after rendering."""
from __future__ import annotations

import os
import re
import subprocess
import json
from pathlib import Path

from .ffmpeg import run_capture_stderr
from .render import output_size

# TikTok-style overlay regions in % of a 9:16 frame (approximate; UI differs by device/app version)
SAFE_ZONES = {"top": 11, "bottom": 22, "right": 15, "left": 4}


def pre_export(tl: dict, media_map: dict, words: list[dict], lines: list[dict], settings: dict, export: dict,
               plan: dict, issues: list[dict], target: float | None) -> dict:
    items = []

    def add(level, code, msg, t=None):
        items.append({"level": level, "code": code, "message": msg, "t": t})

    clips = tl["clips"]
    if not clips:
        add("fail", "empty", "Timeline is empty.")
    W, H = output_size(export.get("aspect", "9:16"), export.get("resolution", "1080p"))
    if max(W, H) > plan.get("max_height", 1080) * 16 / 9 + 1 or min(W, H) > plan.get("max_height", 1080):
        add("fail", "plan_resolution", f"{export.get('resolution')} export isn't included in your plan.")
    seen_missing = set()
    for c in clips:
        m = media_map.get(c["media_id"])
        if not m or not os.path.exists(m["abs_original"]):
            if c["media_id"] not in seen_missing:
                add("fail", "missing_media", "A source clip is missing from storage.", c["t0"])
                seen_missing.add(c["media_id"])
            continue
        if c["e"] > (m.get("duration") or 0) + 0.06:
            add("fail", "out_of_range", "A clip extends past the end of its source file.", c["t0"])
        if c["t1"] - c["t0"] < 0.15:
            add("warn", "flash_clip", f"Very short clip ({(c['t1'] - c['t0']) * 1000:.0f} ms) may look like a glitch.", c["t0"])
        for a, b in (m.get("analysis") or {}).get("blank", []):
            if a < c["e"] and b > c["s"] and min(b, c["e"]) - max(a, c["s"]) > 0.3:
                add("warn", "black_frames", "Black or covered-lens frames are included.", c["t0"]); break
    # cut-off speech: a cut lands inside a word
    by_media: dict[str, list] = {}
    for w in words:
        by_media.setdefault(w["media_id"], []).append(w)
    cut_warn = 0
    for c in clips:
        for edge in (c["s"], c["e"]):
            for w in by_media.get(c["media_id"], []):
                if w["s"] + 0.04 < edge < w["e"] - 0.04:
                    cut_warn += 1
                    if cut_warn <= 5:
                        add("warn", "cut_word", f"A cut lands inside the word “{w['t'].strip()}”.", c["t0"])
                    break
    for mid in {c["media_id"] for c in clips}:
        m = media_map.get(mid) or {}
        h = min(m.get("width") or 0, m.get("height") or 0)
        if h and h < min(W, H) * 0.7:
            add("warn", "low_res", f"{m.get('filename', 'A clip')} is {h}p — it will be upscaled.")
        mw, mh = m.get("width") or 0, m.get("height") or 0
        if mw and mh and (mw > mh) != (W > H) and mw != mh:
            add("info", "aspect", f"{m.get('filename', 'A clip')} is {'landscape' if mw > mh else 'portrait'}; it will be center-cropped.")
        an = m.get("analysis") or {}
        if an.get("peak_db", -99) > -0.3 and an.get("clip_ratio", 0) > 0.0005:
            add("warn", "audio_clipping", f"Audio in {m.get('filename', 'a clip')} is clipping; the limiter will tame peaks but distortion may remain.")
        if not m.get("has_audio"):
            add("info", "no_audio", f"{m.get('filename', 'A clip')} has no audio track (silence will be used).")
    cap = settings.get("captions", {})
    if cap.get("enabled", True):
        if not lines and words:
            add("warn", "no_captions", "Captions are on but no spoken words are on the timeline.")
        y = float(cap.get("y", 62))
        if export.get("aspect", "9:16") == "9:16":
            if y > 100 - SAFE_ZONES["bottom"] - 3:
                add("warn", "safe_zone", "Captions may be hidden behind the caption/description and shop buttons.")
            if y < SAFE_ZONES["top"] + 3:
                add("warn", "safe_zone_top", "Captions may collide with the top navigation.")
        for ln in lines:
            if ln["t1"] <= ln["t0"]:
                add("fail", "caption_timing", "A caption has invalid timing.", ln["t0"]); break
            if sum(len(w["text"]) + 1 for w in ln["words"]) > 26:
                add("info", "caption_long", "A caption line is long and may wrap to 2 lines.", ln["t0"]); break
    for i in issues[:8]:
        add("warn", "compliance", f"{i['issue']}: “{i['match']}” — {i['suggestion']}", i.get("t0"))
    if target and tl["duration"] > target * 1.25:
        add("info", "duration", f"Video is {tl['duration']:.1f}s (target {target:.0f}s).")
    status = "fail" if any(i["level"] == "fail" for i in items) else "warn" if any(i["level"] == "warn" for i in items) else "pass"
    return {"status": status, "items": items, "output": {"width": W, "height": H}}


def _streams(path: Path) -> dict:
    r = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)],
                       capture_output=True, text=True)
    return json.loads(r.stdout or "{}")


def post_render(path: Path, expected: float, W: int, H: int, fps: int) -> dict:
    items = []
    d = _streams(path)
    v = next((s for s in d.get("streams", []) if s["codec_type"] == "video"), None)
    a = next((s for s in d.get("streams", []) if s["codec_type"] == "audio"), None)
    if not v:
        items.append({"level": "fail", "code": "no_video", "message": "Rendered file has no video stream."})
    if not a:
        items.append({"level": "fail", "code": "no_audio", "message": "Rendered file has no audio stream."})
    dur = float(d.get("format", {}).get("duration", 0))
    tol = 0.1 + 2.0 / fps
    if abs(dur - expected) > max(tol, expected * 0.01):
        items.append({"level": "fail", "code": "duration", "message": f"Duration {dur:.2f}s differs from expected {expected:.2f}s."})
    if v and a:
        vd, ad = float(v.get("duration", dur)), float(a.get("duration", dur))
        if abs(vd - ad) > 0.1:
            items.append({"level": "fail", "code": "av_sync", "message": f"Audio/video length mismatch ({abs(vd - ad) * 1000:.0f} ms)."})
        else:
            items.append({"level": "pass", "code": "av_sync", "message": f"Audio/video aligned (Δ {abs(vd - ad) * 1000:.0f} ms)."})
    if v and (int(v.get("width", 0)), int(v.get("height", 0))) != (W, H):
        items.append({"level": "fail", "code": "resolution", "message": f"Output is {v.get('width')}×{v.get('height')}, expected {W}×{H}."})
    try:
        log = run_capture_stderr(["-i", str(path), "-vf", "blackdetect=d=0.5:pix_th=0.08,freezedetect=n=0.0008:d=2.5",
                                  "-af", "volumedetect", "-f", "null", "-"], timeout=1800)
        for m in re.finditer(r"black_start:([\d.]+) black_end:([\d.]+)", log):
            items.append({"level": "warn", "code": "black", "message": f"Black frames {float(m.group(1)):.1f}–{float(m.group(2)):.1f}s.",
                          "t": float(m.group(1))})
        for m in re.finditer(r"freeze_start: ([\d.]+)", log):
            items.append({"level": "warn", "code": "frozen", "message": f"Frozen picture near {float(m.group(1)):.1f}s.", "t": float(m.group(1))})
        mv = re.search(r"max_volume: ([-\d.]+) dB", log)
        if mv and float(mv.group(1)) > -0.05:
            items.append({"level": "warn", "code": "peak", "message": "Audio peaks at 0 dBFS."})
        mean = re.search(r"mean_volume: ([-\d.]+) dB", log)
        if mean and float(mean.group(1)) < -45:
            items.append({"level": "warn", "code": "quiet", "message": "Audio is very quiet or missing."})
    except Exception as e:  # analysis failure shouldn't fail an otherwise-good render
        items.append({"level": "info", "code": "scan_skipped", "message": f"Frame scan skipped: {e}"[:200]})
    status = "fail" if any(i["level"] == "fail" for i in items) else "warn" if any(i["level"] == "warn" for i in items) else "pass"
    return {"status": status, "items": items, "duration": dur}
