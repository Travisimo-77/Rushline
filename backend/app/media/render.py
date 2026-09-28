"""Final render: derived timeline → one ffmpeg graph over the ORIGINAL media.

Reliability measures:
- accurate per-clip input seeks; every clip's video is cloned/trimmed and its audio padded/trimmed to the exact
  same duration → no cumulative A/V drift, no dropped clips;
- 8 ms fades at each audio cut → no clicks/pops;
- constant output frame rate (iPhone VFR sources normalised);
- HDR sources tone-mapped to SDR; rotation handled by ffmpeg autorotate;
- long timelines rendered in chunks then joined (bounded memory / process size);
- output written to *.part and only renamed after post-render QC passes.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from .captions import to_ass
from .ffmpeg import MediaError, filter_path, filter_script_args, run, tonemap_chain
from .proxy import audio_chain

FONTS_DIR = Path(__file__).resolve().parent.parent.parent / "fonts"
CHUNK = 40

RES = {"540p": 540, "720p": 720, "1080p": 1080, "1440p": 1440, "4k": 2160}
QUALITY = {"high": ("slow", 18), "balanced": ("medium", 20), "small": ("veryfast", 26), "preview": ("ultrafast", 27)}


def output_size(aspect: str, res: str) -> tuple[int, int]:
    short = RES.get(res, 1080)
    if aspect == "1:1":
        return short, short
    if aspect == "16:9":
        return int(short * 16 / 9) // 2 * 2, short
    return short, int(short * 16 / 9) // 2 * 2  # 9:16


def _atempo(speed: float) -> list[str]:
    out = []
    s = speed
    while s > 2.0:
        out.append("atempo=2.0"); s /= 2.0
    while s < 0.5:
        out.append("atempo=0.5"); s /= 0.5
    if abs(s - 1.0) > 1e-3:
        out.append(f"atempo={s:.4f}")
    return out


def _video_filter(i: int, clip: dict, media: dict, W: int, H: int, fps: int, color: dict) -> str:
    p = clip.get("props", {})
    speed = float(clip.get("speed", 1.0))
    dur = clip["_dur"] if "_dur" in clip else (clip["e"] - clip["s"] + clip.get("_eb", 0) + clip.get("_ea", 0)) / speed
    zoom = max(1.0, float(p.get("zoom", 1.0)))
    px, py = float(p.get("pan_x", 0)), float(p.get("pan_y", 0))
    chain = ["setpts=PTS-STARTPTS"]
    if media.get("info", {}).get("hdr"):
        chain.append(tonemap_chain())
    rot = int(p.get("rotate", 0)) % 360
    if rot == 90:
        chain.append("transpose=1")
    elif rot == 180:
        chain.append("transpose=1,transpose=1")
    elif rot == 270:
        chain.append("transpose=2")
    zw, zh = int(W * zoom) // 2 * 2, int(H * zoom) // 2 * 2
    chain.append(f"scale={zw}:{zh}:force_original_aspect_ratio=increase:flags=lanczos")
    chain.append(f"crop={W}:{H}:(iw-{W})/2*(1+{px:.3f}):(ih-{H})/2*(1+{py:.3f})")
    chain.append("setsar=1")
    b = float(color.get("brightness", 0)) + float(p.get("brightness", 0))
    c = float(color.get("contrast", 1)) * float(p.get("contrast", 1))
    s = float(color.get("saturation", 1)) * float(p.get("saturation", 1))
    if abs(b) > 1e-3 or abs(c - 1) > 1e-3 or abs(s - 1) > 1e-3:
        chain.append(f"eq=brightness={b:.3f}:contrast={c:.3f}:saturation={s:.3f}")
    temp = float(color.get("temperature", 0))
    if abs(temp) > 0.5:
        chain.append(f"colortemperature=temperature={int(6500 - temp * 25)}:mix=0.6")
    sharp = float(color.get("sharpen", 0))
    if sharp > 0.01:
        chain.append(f"unsharp=5:5:{min(sharp, 1.5):.2f}:5:5:0")
    if abs(speed - 1) > 1e-3:
        chain.append(f"setpts=PTS/{speed:.4f}")
    chain += [f"fps={fps}", "format=yuv420p", "tpad=stop_mode=clone:stop_duration=0.25", f"trim=duration={dur:.4f}",
              "setpts=PTS-STARTPTS", f"settb=1/{fps}", f"fps={fps}"]
    return f"[{i}:v]" + ",".join(chain) + f"[v{i}]"


def _audio_filter(i: int, ain: str, clip: dict) -> str:
    """Audio is always the clip's core (no dissolve handles): speech butts up word-to-word at full level."""
    p = clip.get("props", {})
    speed = float(clip.get("speed", 1.0))
    eb, ea = clip.get("_eb", 0), clip.get("_ea", 0)
    dur = (clip["_dur"] - eb - ea) if "_dur" in clip else (clip["e"] - clip["s"]) / speed
    vol = 0.0 if p.get("mute") else float(p.get("volume", 1.0))
    chain = ["asetpts=PTS-STARTPTS", "aresample=48000", "aformat=sample_fmts=fltp:channel_layouts=stereo"]
    if eb:
        chain.append(f"atrim=start={eb * speed:.4f}")  # skip the video-only handle
        chain.append("asetpts=PTS-STARTPTS")
    chain += _atempo(speed)
    if abs(vol - 1) > 1e-3:
        chain.append(f"volume={vol:.3f}")
    fade = min(0.006, dur / 6)  # 6 ms: click-free but inaudible
    chain += [f"afade=t=in:d={fade:.3f}", "apad", f"atrim=duration={dur:.4f}",
              f"afade=t=out:st={max(dur - fade, 0):.4f}:d={fade:.3f}", "asetpts=PTS-STARTPTS"]
    return f"[{ain}]" + ",".join(chain) + f"[a{i}]"


def _broll_chain(brolls, base: str, start_idx: int, W: int, H: int, fps: int):
    """Product B-roll as picture overlays on top of the edit (main audio keeps playing underneath).
    Each shot fades in/out over 0.12 s; stills get a gentle push-in so they don't look frozen."""
    args, filters = [], []
    idx = start_idx
    for j, b in enumerate(brolls or []):
        dur = max(0.3, float(b["t1"]) - float(b["t0"]))
        if b["type"] == "image":
            args += ["-loop", "1", "-t", f"{dur + 0.2:.3f}", "-i", b["path"]]
            zoom = f",scale={int(W * 1.08) // 2 * 2}:-2,crop={W}:{H}:(iw-{W})/2*(1-t/{dur:.3f}):(ih-{H})/2*(1-t/{dur:.3f})"
            pre = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}{zoom}"
        else:
            args += ["-ss", f"{float(b.get('src_in', 0)):.3f}", "-t", f"{dur + 0.2:.3f}", "-i", b["path"]]
            pre = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}"
        fd = min(0.12, dur / 4)
        filters.append(f"[{idx}:v]{pre},setsar=1,fps={fps},trim=duration={dur:.4f},setpts=PTS-STARTPTS,format=yuva420p,"
                       f"fade=t=in:st=0:d={fd:.3f}:alpha=1,fade=t=out:st={dur - fd:.3f}:d={fd:.3f}:alpha=1,"
                       f"setpts=PTS+{float(b['t0']):.4f}/TB[bv{j}]")
        filters.append(f"[{base}][bv{j}]overlay=0:0:enable='between(t,{float(b['t0']):.3f},{float(b['t1']):.3f})':eof_action=pass,"
                       f"format=yuv420p[vb{j}]")
        base = f"vb{j}"
        idx += 1
    return args, filters, base


SOFT = 0.05  # seconds of handle taken from each side of a jump cut → ~0.1 s picture dissolve, total length unchanged


def _plan_soft(clips: list[dict], media_map: dict, soft: bool) -> list[dict]:
    """Decide which joins get a quick dissolve and borrow handle footage from the removed part (usually silence),
    so the video keeps exactly the same length and the audio/captions stay in sync."""
    out = [dict(c, _eb=0.0, _ea=0.0) for c in clips]
    if not soft:
        return out
    for k in range(1, len(out)):
        a, b = out[k - 1], out[k]
        jump = a["media_id"] == b["media_id"] and abs(b["s"] - a["e"]) > 0.04
        if not jump or a.get("speed", 1) != 1 or b.get("speed", 1) != 1:
            continue
        dur_media = float(media_map[a["media_id"]].get("duration") or a["e"])
        ea = min(SOFT, dur_media - a["e"], (a["e"] - a["s"]) / 3)
        eb = min(SOFT, b["s"], (b["e"] - b["s"]) / 3)
        if ea + eb >= 0.06:
            a["_ea"], b["_eb"] = round(ea, 4), round(eb, 4)
    return out


def _render_segment(clips, media_map, W, H, fps, color, out: Path, vcodec_args, acodec_args, post_v=None, post_a=None,
                    progress=None, total=None, soft: bool = False, brolls=None):
    clips = _plan_soft(clips, media_map, soft)
    # Frame-exact durations: video can only change on frame boundaries, so every clip (and every dissolve handle)
    # is snapped to whole frames using cumulative rounding — audio is trimmed to the identical length, so tiny
    # rounding errors can never add up into audio/video drift across many cuts.
    T = 0.0
    for c in clips:
        core = (c["e"] - c["s"]) / float(c.get("speed", 1))
        f0 = round(T * fps)
        T += core
        c["_eb"] = round(c["_eb"] * fps) / fps
        c["_ea"] = round(c["_ea"] * fps) / fps
        c["_dur"] = (round(T * fps) - f0) / fps + c["_eb"] + c["_ea"]
    args: list[str] = []
    filters = []
    n_inputs = 0
    for clip in clips:
        m = media_map[clip["media_id"]]
        s0 = clip["s"] - clip["_eb"]
        length = clip["_dur"] * float(clip.get("speed", 1))
        args += ["-ss", f"{s0:.4f}", "-t", f"{length + 0.05:.4f}", "-i", m["abs_original"]]
        n_inputs += 1
    silent_inputs = {}
    for idx, clip in enumerate(clips):
        m = media_map[clip["media_id"]]
        if not m.get("has_audio"):
            dur = clip["_dur"] + 0.1
            args += ["-f", "lavfi", "-t", f"{dur:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
            silent_inputs[idx] = n_inputs
            n_inputs += 1
    for idx, clip in enumerate(clips):
        m = media_map[clip["media_id"]]
        filters.append(_video_filter(idx, clip, m, W, H, fps, color))
        ain = f"{silent_inputs[idx]}:a" if idx in silent_inputs else f"{idx}:a:0"
        filters.append(_audio_filter(idx, ain, clip))
    if not any(c["_eb"] for c in clips):
        cat = "".join(f"[v{i}][a{i}]" for i in range(len(clips)))
        filters.append(f"{cat}concat=n={len(clips)}:v=1:a=1[vc][ac]")
    else:
        # chain joins one by one: dissolve (xfade + acrossfade) on jump cuts, straight concat elsewhere
        vcur, acur = "v0", "a0"
        length = clips[0]["_dur"]
        for k in range(1, len(clips)):
            c = clips[k]
            ck = c["_dur"]
            d = clips[k - 1]["_ea"] + c["_eb"]
            vn, an = f"vx{k}", f"ax{k}"
            if c["_eb"]:
                filters.append(f"[{vcur}][v{k}]xfade=transition=fade:duration={d:.4f}:offset={length - d:.4f}[{vn}]")
                filters.append(f"[{acur}][a{k}]concat=n=2:v=0:a=1[{an}]")
                length += ck - d
            else:
                filters.append(f"[{vcur}][v{k}]concat=n=2:v=1:a=0,fps={fps},settb=1/{fps}[{vn}]")
                filters.append(f"[{acur}][a{k}]concat=n=2:v=0:a=1[{an}]")
                length += ck
            vcur, acur = vn, an
        filters.append(f"[{vcur}]null[vc]")
        filters.append(f"[{acur}]anull[ac]")
    vlabel, alabel = "vc", "ac"
    if brolls:
        n_in = len(clips) + len(silent_inputs)
        b_args, b_filters, vlabel = _broll_chain(brolls, "vc", n_in, W, H, fps)
        args += b_args
        filters += b_filters
    if post_v:
        filters.append(f"[{vlabel}]{post_v}[vo]"); vlabel = "vo"
    # the master audio chain (denoise / loudness / limiter) can add a few ms of latency: pin the final
    # audio to exactly the video length so the file can never drift out of sync
    total_out = sum(c["_dur"] - c["_eb"] - c["_ea"] for c in clips)
    filters.append(f"[ac]{(post_a + ',') if post_a else ''}apad,atrim=duration={total_out:.4f},asetpts=PTS-STARTPTS[ao]")
    alabel = "ao"
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as fg:
        fg.write(";\n".join(filters))
        graph = fg.name
    try:
        run(args + filter_script_args(graph) + ["-map", f"[{vlabel}]", "-map", f"[{alabel}]"] + vcodec_args + acodec_args
            + [str(out)], progress=progress, total=total, timeout=6 * 3600)
    finally:
        os.unlink(graph)


def render(timeline: dict, media_map: dict, settings: dict, export: dict, caption_lines: list[dict], overlays: list[dict],
           out: Path, watermark: bool = False, progress=None, brolls: list[dict] | None = None) -> dict:
    clips = timeline["clips"]
    if not clips:
        raise MediaError("Timeline is empty")
    W, H = output_size(export.get("aspect", "9:16"), export.get("resolution", "1080p"))
    fps = int(export.get("fps") or 30)
    if export.get("fps") == "source":
        fps = int(round(max((media_map[c["media_id"]].get("fps") or 30) for c in clips)))
        fps = min(max(fps, 24), 60)
    preset, crf = QUALITY.get(export.get("quality", "balanced"), QUALITY["balanced"])
    vargs = ["-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-profile:v", "high", "-pix_fmt", "yuv420p",
             "-r", str(fps), "-g", str(fps * 2), "-movflags", "+faststart", "-map_metadata", "-1"]
    aargs = ["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]
    color = settings.get("color", {})
    tmpdir = Path(tempfile.mkdtemp(prefix="rl_render_"))
    ass_path = tmpdir / "captions.ass"
    style = settings.get("captions", {})
    ass_path.write_text(to_ass(caption_lines, style, W, H, overlays, watermark), encoding="utf-8")
    needs_ass = (style.get("enabled", True) and caption_lines) or overlays or watermark
    post_v = f"ass=filename={filter_path(ass_path)}:fontsdir={filter_path(FONTS_DIR)}" if needs_ass else None
    soft = bool(settings.get("video", {}).get("soft_cuts", True))
    post_a = audio_chain(settings.get("audio", {}))
    part = out.with_name(out.stem + ".part.mp4")
    total = timeline["duration"]
    try:
        if len(clips) <= CHUNK:
            _render_segment(clips, media_map, W, H, fps, color, part, vargs, aargs, post_v, post_a, progress, total, soft=soft,
                            brolls=brolls)
        else:
            # chunked: near-lossless intermediates, then one final pass for captions + master audio
            seg_files = []
            done = 0.0
            for k in range(0, len(clips), CHUNK):
                chunk = clips[k:k + CHUNK]
                seg = tmpdir / f"seg{k:05d}.mkv"
                cdur = sum((c["e"] - c["s"]) / c.get("speed", 1) for c in chunk)
                _render_segment(chunk, media_map, W, H, fps, color, seg,
                                ["-c:v", "libx264", "-preset", "veryfast", "-crf", "12", "-pix_fmt", "yuv420p", "-r", str(fps)],
                                ["-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2"],
                                progress=(lambda p, d=done, cd=cdur: progress and progress(0.7 * (d + p * cd) / total)), total=cdur)
                done += cdur
                seg_files.append(seg)
            lst = tmpdir / "list.txt"
            lst.write_text("".join(f"file '{str(f).replace(chr(92), '/')}'\n" for f in seg_files))
            b_args, b_filters, vlab = _broll_chain(brolls, "0:v", 1, W, H, fps)
            fc = b_filters + ([f"[{vlab}]{post_v}[vo]"] if post_v else [f"[{vlab}]null[vo]"]) + [f"[0:a]{post_a}[ao]"]
            with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, dir=tmpdir) as fg:
                fg.write(";\n".join(fc))
            run(["-f", "concat", "-safe", "0", "-i", str(lst)] + b_args + filter_script_args(fg.name) + ["-map", "[vo]", "-map", "[ao]"]
                + vargs + aargs + [str(part)],
                progress=(lambda p: progress and progress(0.7 + 0.3 * p)), total=total, timeout=6 * 3600)
        return {"part": part, "width": W, "height": H, "fps": fps, "expected_duration": total}
    finally:
        for f in tmpdir.iterdir():
            f.unlink(missing_ok=True)
        tmpdir.rmdir()
