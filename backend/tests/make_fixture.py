"""Builds synthetic 'messy raw footage' with a known word-level transcript (sidecar), so the whole pipeline can be
tested without a speech model: setup dead space, 3 hook attempts, a false start, a spoken mistake, fillers, a stutter,
a duplicate CTA, and a product that is visible only during the demo + in a separate B-roll clip."""
from __future__ import annotations

import json
import math
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

SR = 48000

SCRIPT_A = [
    ("PAUSE", 1.8),
    ("So um I thought this clay was completely overhyped until I tried it.", None),
    ("PAUSE", 1.2),
    ("If your hair keeps going flat by noon, this might be why.", None),
    ("PAUSE", 0.9),
    ("There's no way this is still this cheap.", None),
    ("PAUSE", 1.5),
    ("My hair always ends up flat and greasy by lunch.", None),
    ("PAUSE", 0.8),
    ("This is the CS Theory", None),
    ("PAUSE", 0.7),
    ("Wait let me redo that.", None),
    ("PAUSE", 1.0),
    ("This is the CS Theory hair clay.", None),
    ("PAUSE", 0.5),
    ("It adds texture without leaving my hair shiny.", None),
    ("PAUSE", 0.6),
    ("Watch, I'm going to put it in right now.", "PRODUCT"),
    ("PAUSE", 1.6),
    ("It it comes with uh like a matte finish that lasts all day.", "PRODUCT"),
    ("PAUSE", 0.7),
    ("It's only $14 right now with 20% off.", None),
    ("PAUSE", 0.9),
    ("Tap the orange cart to grab yours.", None),
    ("PAUSE", 0.8),
    ("Tap the orange cart to grab yours before it's gone.", None),
    ("PAUSE", 1.4),
]


def product_image(path: Path) -> None:
    rng = np.random.default_rng(7)
    W, H = 600, 600
    img = Image.new("RGB", (W, H), (30, 30, 34))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([60, 120, 540, 520], 40, fill=(212, 178, 120))
    d.rectangle([60, 60, 540, 150], fill=(40, 40, 40))
    try:
        f = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 56)
        f2 = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 30)
    except OSError:
        f = f2 = ImageFont.load_default()
    d.text((100, 200), "CS THEORY", fill=(25, 25, 25), font=f)
    d.text((100, 280), "matte hair clay", fill=(25, 25, 25), font=f2)
    d.text((100, 330), "strong hold / 85g", fill=(25, 25, 25), font=f2)
    for _ in range(260):  # texture → plenty of ORB keypoints
        x, y = rng.integers(80, 520), rng.integers(390, 500)
        r = int(rng.integers(3, 9))
        d.ellipse([x - r, y - r, x + r, y + r], fill=tuple(int(c) for c in rng.integers(0, 255, 3)))
    img.save(path, quality=95)


def synth(script, out_wav: Path):
    words, spans = [], []
    t = 0.0
    chunks = []
    rng = np.random.default_rng(1)
    for text, tag in script:
        if text == "PAUSE":
            n = int(tag * SR)
            chunks.append(rng.normal(0, 0.0015, n).astype(np.float32))  # room tone
            t += tag
            continue
        start_sentence = t
        for k, w in enumerate(text.split()):
            dur = 0.11 + 0.055 * len(w.strip(".,!?"))
            n = int(dur * SR)
            tt = np.arange(n) / SR
            f0 = 150 + 40 * math.sin(len(words) * 1.3)
            sig = sum(np.sin(2 * np.pi * f0 * h * tt) / h for h in range(1, 6))
            env = np.minimum(1, np.minimum(tt / 0.02, (dur - tt) / 0.03))
            chunks.append((0.25 * sig * env).astype(np.float32))
            words.append({"t": w, "s": round(t, 3), "e": round(t + dur, 3), "p": 0.95})
            t += dur
            gap = 0.06
            chunks.append(rng.normal(0, 0.0015, int(gap * SR)).astype(np.float32))
            t += gap
        if tag == "PRODUCT":
            spans.append((start_sentence, t + 0.3))
    audio = np.concatenate(chunks)
    pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(out_wav), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(pcm.tobytes())
    return words, spans, t


def make_video(out: Path, wav: Path, duration: float, product: Path, spans, size=(1080, 1920)):
    W, H = size
    enable = "+".join(f"between(t,{a:.2f},{b:.2f})" for a, b in spans) or "0"
    fc = (f"[1:v]scale={int(W * 0.55)}:-1[p];"
          f"[0:v][p]overlay=x=(W-w)/2:y=H*0.45:enable='{enable}'[v]")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=s={W}x{H}:r=30:d={duration:.2f}",
                    "-loop", "1", "-i", str(product), "-i", str(wav), "-filter_complex", fc, "-map", "[v]", "-map", "2:a",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
                    "-t", f"{duration:.2f}", str(out)], check=True)


def build(outdir: Path) -> dict:
    outdir.mkdir(parents=True, exist_ok=True)
    prod = outdir / "product.jpg"
    product_image(prod)
    wav = outdir / "a.wav"
    words, spans, dur = synth(SCRIPT_A, wav)
    make_video(outdir / "raw_take.mp4", wav, dur, prod, spans)
    (outdir / "raw_take.words.json").write_text(json.dumps({"language": "en", "words": words}))
    # B-roll: 4 s product close-up, no speech
    broll_wav = outdir / "b.wav"
    synth([("PAUSE", 4.0)], broll_wav)
    make_video(outdir / "broll.mp4", broll_wav, 4.0, prod, [(0, 4.0)], size=(1080, 1920))
    (outdir / "broll.words.json").write_text(json.dumps({"language": "en", "words": []}))
    return {"dir": str(outdir), "duration": dur, "words": len(words), "product_spans": spans}


if __name__ == "__main__":
    print(build(Path(sys.argv[1] if len(sys.argv) > 1 else "fixtures")))
