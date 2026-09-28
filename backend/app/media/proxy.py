"""Proxy generation: lightweight, iPhone-Safari-friendly H.264 copies for smooth editing.

Originals are never touched and are what the renderer uses for final export.
"""
from __future__ import annotations

from pathlib import Path

from .. import config
from .ffmpeg import run, tonemap_chain


def make_proxy(src: Path, dst: Path, info: dict, progress=None) -> None:
    w, h = info.get("width") or 1080, info.get("height") or 1920
    short = config.PROXY_SHORT_SIDE
    if min(w, h) > short:
        scale = f"scale=-2:{short}" if h <= w else f"scale={short}:-2"
    else:
        scale = "scale=trunc(iw/2)*2:trunc(ih/2)*2"
    vf = []
    if info.get("hdr"):
        vf.append(tonemap_chain())
    vf += [scale, f"fps={config.PROXY_FPS}", "format=yuv420p"]
    tmp = dst.with_name(dst.stem + ".part.mp4")
    args = ["-i", str(src), "-map", "0:v:0"]
    if info.get("has_audio"):
        args += ["-map", "0:a:0"]
    args += ["-vf", ",".join(vf), "-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-profile:v", "high",
             "-g", str(config.PROXY_FPS // 2), "-keyint_min", str(config.PROXY_FPS // 2), "-sc_threshold", "0",
             "-movflags", "+faststart", "-map_metadata", "-1"]
    if info.get("has_audio"):
        args += ["-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2", "-af", "aresample=async=1:first_pts=0"]
    args += [str(tmp)]
    run(args, progress=progress, total=info.get("duration"))
    tmp.replace(dst)


def make_audio_wav(src: Path, dst: Path, duration: float) -> None:
    tmp = dst.with_name(dst.stem + ".part.wav")
    run(["-i", str(src), "-map", "0:a:0", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(tmp)])
    tmp.replace(dst)


def make_silent_wav(dst: Path, duration: float) -> None:
    run(["-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono", "-t", f"{max(duration, 0.1)}", "-c:a", "pcm_s16le", str(dst)])


def make_thumb(src: Path, dst: Path, duration: float) -> None:
    t = min(1.0, max(duration / 3, 0))
    run(["-ss", f"{t}", "-i", str(src), "-frames:v", "1", "-vf", "scale=360:-2", "-q:v", "4", str(dst)])


ENHANCE_CHAIN = ("highpass=f=80,lowpass=f=14000,afftdn=nr={nr}:nf=-40:tn=1,"
                 "acompressor=threshold=-20dB:ratio=3:attack=5:release=120:makeup=2,"
                 "loudnorm=I={lufs}:TP=-1.5:LRA=11,alimiter=limit=0.89")


def audio_chain(audio: dict) -> str:
    if not audio.get("enhance"):
        return "alimiter=limit=0.95" if audio.get("normalize", True) else "anull"
    nr = int(6 + 18 * float(audio.get("denoise", 0.6)))
    return ENHANCE_CHAIN.format(nr=nr, lufs=int(audio.get("target_lufs", -14)))


def make_enhanced_proxy(proxy: Path, dst: Path, audio: dict) -> None:
    """Proxy video stream copied + enhanced audio: lets the creator A/B original vs enhanced audio instantly."""
    tmp = dst.with_name(dst.stem + ".part.mp4")
    run(["-i", str(proxy), "-map", "0:v:0", "-map", "0:a:0", "-c:v", "copy", "-af", audio_chain({**audio, "enhance": True}),
         "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-movflags", "+faststart", str(tmp)])
    tmp.replace(dst)
