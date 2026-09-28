"""Audio + visual analysis: silence spans, loudness/clipping, blank frames, motion, color stats, product sightings."""
from __future__ import annotations

import subprocess
import wave
from pathlib import Path

import numpy as np


# ---------------------------------------------------------------- audio
def audio_analysis(wav: Path) -> dict:
    with wave.open(str(wav)) as w:
        sr = w.getframerate()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    if data.size == 0:
        return {"silences": [], "peak_db": -120, "rms_db": -120, "clip_ratio": 0, "noise_floor_db": -120, "envelope": []}
    hop = int(sr * 0.01)
    n = data.size // hop
    frames = data[: n * hop].reshape(n, hop)
    rms = np.sqrt(np.mean(frames ** 2, axis=1) + 1e-12)
    db = 20 * np.log10(rms + 1e-9)
    floor = float(np.percentile(db, 10))
    speech_level = float(np.percentile(db, 90))
    thr = max(min(floor + 12, speech_level - 18), -55)
    quiet = db < thr
    silences = []
    start = None
    for i, q in enumerate(quiet):
        if q and start is None:
            start = i
        elif not q and start is not None:
            if i - start >= 20:
                silences.append([round(start * 0.01, 2), round(i * 0.01, 2)])
            start = None
    if start is not None and n - start >= 20:
        silences.append([round(start * 0.01, 2), round(n * 0.01, 2)])
    peak = float(np.max(np.abs(data)))
    # 10 Hz envelope for waveform drawing on the timeline
    step = 10
    env = [round(float(x), 3) for x in np.clip((db[: (n // step) * step].reshape(-1, step).max(axis=1) + 60) / 60, 0, 1)]
    return {"silences": silences, "gaps": speech_gaps(wav), "soft_gaps": speech_gaps(wav, strict=True), "threshold_db": round(thr, 1), "noise_floor_db": round(floor, 1),
            "peak_db": round(20 * np.log10(peak + 1e-9), 2), "rms_db": round(float(20 * np.log10(np.sqrt(np.mean(data ** 2)) + 1e-9)), 1),
            "clip_ratio": round(float(np.mean(np.abs(data) > 0.99)), 5), "envelope": env}


def speech_gaps(wav: Path, min_len: float = 0.04, strict: bool = False) -> list[list[float]]:
    """Low-energy gaps between speech at 10 ms resolution — the only places a cut can land without clipping a word.
    Threshold adapts to the recording: digital silence (noise-gated iPhone audio) is ignored when estimating the floor."""
    with wave.open(str(wav)) as w:
        sr = w.getframerate()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    hop = int(sr * 0.01)
    n = data.size // hop
    if n == 0:
        return []
    db = 20 * np.log10(np.sqrt(np.mean(data[: n * hop].reshape(n, hop) ** 2, axis=1)) + 1e-9)
    real = db[db > -90]
    if real.size < 10:
        return [[0.0, round(n * 0.01, 2)]]
    floor, loud = float(np.percentile(real, 10)), float(np.percentile(real, 90))
    thr = min(floor + max(6.0, 0.3 * (loud - floor)), loud - 12)
    if strict:  # breaths / mouth noise count as "not speech": used to start clips exactly on the word
        thr = max(thr, loud - 35)
    # light smoothing so a single quiet frame inside a word doesn't count as a gap
    sm = np.convolve(db, np.ones(3) / 3, mode="same")
    quiet = sm < thr
    gaps, start = [], None
    for i, q in enumerate(quiet):
        if q and start is None:
            start = i
        elif not q and start is not None:
            if (i - start) * 0.01 >= min_len:
                gaps.append([round(start * 0.01, 2), round(i * 0.01, 2)])
            start = None
    if start is not None:
        gaps.append([round(start * 0.01, 2), round(n * 0.01, 2)])
    return gaps


# ---------------------------------------------------------------- visual
def _frames(src: Path, fps: float, width: int, duration: float):
    """Yield (t, BGR frame) sampled at `fps` using a single ffmpeg decode (streams; constant memory)."""
    import cv2  # noqa: F401  (ensures availability)
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                            "-of", "csv=p=0", str(src)], capture_output=True, text=True)
    w0, h0 = [int(x) for x in probe.stdout.strip().split(",")[:2]]
    h = int(round(h0 * width / w0 / 2) * 2)
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(src), "-vf", f"fps={fps},scale={width}:{h}", "-f", "rawvideo",
                          "-pix_fmt", "bgr24", "pipe:1"], stdout=subprocess.PIPE)
    size = width * h * 3
    i = 0
    try:
        while True:
            buf = p.stdout.read(size)  # type: ignore[union-attr]
            if len(buf) < size:
                break
            yield i / fps, np.frombuffer(buf, np.uint8).reshape(h, width, 3)
            i += 1
    finally:
        p.kill()


class ProductMatcher:
    """ORB keypoint matching against product photos (heuristic, offline, no model download).
    Swap for a CLIP / detector provider later with the same `match(frame) -> (hit, score, area)` contract."""

    def __init__(self, photo_paths: list[Path]):
        import cv2
        self.cv2 = cv2
        self.orb = cv2.ORB_create(nfeatures=1000)
        self.refs = []
        for pth in photo_paths:
            img = cv2.imread(str(pth), cv2.IMREAD_GRAYSCALE)
            if img is None:
                continue
            scale = 480 / max(img.shape)
            img = cv2.resize(img, None, fx=scale, fy=scale) if scale < 1 else img
            kp, des = self.orb.detectAndCompute(img, None)
            if des is not None and len(kp) >= 20:
                self.refs.append((kp, des, img.shape))
        self.bf = cv2.BFMatcher(cv2.NORM_HAMMING)

    def match(self, frame) -> tuple[bool, float, float]:
        cv2 = self.cv2
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        kp, des = self.orb.detectAndCompute(gray, None)
        if des is None or len(kp) < 15:
            return False, 0.0, 0.0
        best = (False, 0.0, 0.0)
        for rkp, rdes, rshape in self.refs:
            pairs = self.bf.knnMatch(rdes, des, k=2)
            good = [m for m, *rest in pairs if rest and m.distance < 0.75 * rest[0].distance]
            if len(good) < 12:
                continue
            src = np.float32([rkp[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
            dst = np.float32([kp[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
            H, mask = cv2.findHomography(src, dst, cv2.RANSAC, 6.0)
            inliers = int(mask.sum()) if mask is not None else 0
            if H is None or inliers < 10:
                continue
            hh, ww = rshape
            corners = cv2.perspectiveTransform(np.float32([[0, 0], [ww, 0], [ww, hh], [0, hh]]).reshape(-1, 1, 2), H)
            area = abs(cv2.contourArea(corners)) / (gray.shape[0] * gray.shape[1])
            if 0.005 < area < 1.5:
                score = min(1.0, inliers / 40)
                if score > best[1]:
                    best = (True, round(score, 2), round(min(area, 1.0), 3))
        return best


def visual_analysis(src: Path, duration: float, product_photos: list[Path] | None = None, progress=None) -> dict:
    import cv2
    fps = 2.0 if duration < 1200 else 1.0
    matcher = ProductMatcher(product_photos) if product_photos else None
    if matcher and not matcher.refs:
        matcher = None
    prev = None
    motion, blank, hits, lum, sat = [], [], [], [], []
    blank_start = None
    for t, f in _frames(src, fps, 320 if not matcher else 480, duration):
        small = cv2.resize(f, (160, int(160 * f.shape[0] / f.shape[1])))
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).astype(np.float32)
        m = float(np.mean(np.abs(gray - prev)) / 255) if prev is not None else 0.0
        prev = gray
        motion.append([round(t, 2), round(m, 4)])
        mean, std = float(gray.mean()), float(gray.std())
        is_blank = (mean < 22 and std < 12) or std < 4
        if is_blank and blank_start is None:
            blank_start = t
        elif not is_blank and blank_start is not None:
            blank.append([round(blank_start, 2), round(t, 2)])
            blank_start = None
        hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
        lum.append(mean)
        sat.append(float(hsv[..., 1].mean()))
        if matcher:
            hit, score, area = matcher.match(f)
            if hit:
                hits.append([round(t, 2), score, area])
        if progress and duration:
            progress(min(0.99, t / duration))
    if blank_start is not None:
        blank.append([round(blank_start, 2), round(duration, 2)])
    return {"motion": motion, "blank": blank, "product_hits": hits, "sample_fps": fps,
            "luma_mean": round(float(np.mean(lum)) if lum else 0, 1), "luma_p5": round(float(np.percentile(lum, 5)) if lum else 0, 1),
            "sat_mean": round(float(np.mean(sat)) if sat else 0, 1), "product_scanned": bool(matcher)}


def auto_color(analyses: list[dict]) -> dict:
    """Gentle one-tap enhance from measured stats; bounded so footage never looks over-processed."""
    lum = [a.get("luma_mean", 110) for a in analyses if a.get("luma_mean")]
    sat = [a.get("sat_mean", 90) for a in analyses if a.get("sat_mean")]
    L = sum(lum) / len(lum) if lum else 115
    S = sum(sat) / len(sat) if sat else 90
    brightness = max(-0.06, min(0.08, (118 - L) / 255 * 0.6))
    saturation = max(0.95, min(1.18, 1 + (95 - S) / 400))
    return {"brightness": round(brightness, 3), "contrast": 1.05, "saturation": round(saturation, 3), "temperature": 0, "sharpen": 0.3}
