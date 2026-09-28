"""Safe ffmpeg/ffprobe invocation (argument arrays only, timeouts, progress parsing) + probing."""
from __future__ import annotations

import functools
import json
import subprocess
from pathlib import Path
from typing import Callable


class MediaError(Exception):
    pass


def run(args: list[str], timeout: float = 3600, progress: Callable[[float], None] | None = None,
        total: float | None = None) -> str:
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-v", "error"]
    if progress and total:
        cmd += ["-progress", "pipe:1", "-nostats"]
    cmd += args
    if not (progress and total):
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if r.returncode != 0:
            raise MediaError(r.stderr.strip()[-1500:] or "ffmpeg failed")
        return r.stderr
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        for line in p.stdout:  # type: ignore[union-attr]
            if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
                try:
                    us = int(line.split("=")[1])
                    progress(min(0.999, us / 1e6 / total))
                except ValueError:
                    pass
        p.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        p.kill()
        raise MediaError("ffmpeg timed out")
    err = p.stderr.read() if p.stderr else ""
    if p.returncode != 0:
        raise MediaError(err.strip()[-1500:] or "ffmpeg failed")
    return err


def run_capture_stderr(args: list[str], timeout: float = 3600) -> str:
    """For analysis filters that log to stderr (silencedetect, blackdetect, volumedetect)."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-v", "info"] + args, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise MediaError(r.stderr.strip()[-1500:])
    return r.stderr


def probe(path: Path) -> dict:
    r = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
                       capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise MediaError("Not a readable media file: " + r.stderr.strip()[-300:])
    data = json.loads(r.stdout)
    v = next((s for s in data.get("streams", []) if s.get("codec_type") == "video" and s.get("disposition", {}).get("attached_pic") != 1), None)
    a = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
    fmt = data.get("format", {})
    duration = float(fmt.get("duration") or (v or {}).get("duration") or (a or {}).get("duration") or 0)
    info = {"duration": duration, "has_video": v is not None, "has_audio": a is not None, "format": fmt.get("format_name"),
            "size": int(fmt.get("size") or 0), "bitrate": int(fmt.get("bit_rate") or 0)}
    if v:
        w, h = int(v.get("width", 0)), int(v.get("height", 0))
        rot = 0
        for sd in v.get("side_data_list", []) or []:
            if "rotation" in sd:
                rot = int(float(sd["rotation"]))
        rot = int(v.get("tags", {}).get("rotate", rot))
        if abs(rot) % 180 == 90:
            w, h = h, w  # display dimensions (ffmpeg autorotates on decode)
        num, den = (v.get("avg_frame_rate") or "30/1").split("/")
        fps = float(num) / float(den) if float(den or 0) else 30.0
        rnum, rden = (v.get("r_frame_rate") or "30/1").split("/")
        rfps = float(rnum) / float(rden) if float(rden or 0) else fps
        info.update({"width": w, "height": h, "fps": round(fps, 3), "vfr": abs(fps - rfps) > 0.5, "rotation": rot,
                     "vcodec": v.get("codec_name"), "pix_fmt": v.get("pix_fmt"),
                     "hdr": v.get("color_transfer") in ("smpte2084", "arib-std-b67"),
                     "color_transfer": v.get("color_transfer")})
    if a:
        info.update({"acodec": a.get("codec_name"), "sample_rate": int(a.get("sample_rate") or 0), "channels": a.get("channels")})
    return info


@functools.lru_cache(maxsize=None)
def has_filter(name: str) -> bool:
    r = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True)
    return f" {name} " in r.stdout


def tonemap_chain() -> str:
    """HDR (HLG/PQ, e.g. iPhone Dolby Vision) → SDR BT.709 so proxies/exports don't look washed out."""
    if has_filter("zscale") and has_filter("tonemap"):
        return ("zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=hable:desat=0,"
                "zscale=t=bt709:m=bt709:r=tv,format=yuv420p")
    return "format=yuv420p"


@functools.lru_cache(maxsize=None)
def ffmpeg_major() -> int:
    """Major version (ffmpeg 7+ replaced -filter_complex_script with -/filter_complex)."""
    import re
    try:
        out = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True).stdout
        m = re.search(r"version n?(\d+)\.", out)
        return int(m.group(1)) if m else 99  # git/nightly builds: assume modern
    except Exception:
        return 99


def filter_script_args(path: str) -> list[str]:
    return ["-/filter_complex", path] if ffmpeg_major() >= 7 else ["-filter_complex_script", path]


def filter_path(p) -> str:
    """Path usable inside a filter argument on every OS (Windows drive colons must be escaped)."""
    s = str(p).replace("\\", "/").replace(":", "\\:")
    return f"'{s}'"
