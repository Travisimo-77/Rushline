"""Growth features built on the derived timeline: product B-roll, on-screen text hooks, retention map, ad pieces."""
from __future__ import annotations

import math
import re

from .. import db
from ..ai.text import clean_display, ntokens, tokens
from ..security import sign_media
from ..storage import storage
from ..timeline import src_to_timeline

# ---------------------------------------------------------------------------------------------------- B-roll library


def broll_library(ctx) -> list[dict]:
    """Product B-roll: labelled clips uploaded to the product + the product photos (used as still shots)."""
    if not ctx.product:
        return []
    out = []
    for m in db.all_("SELECT * FROM media WHERE user_id=? AND kind='broll' ORDER BY created_at", ctx.user_id):
        info = m["info"] or {}
        if info.get("product_id") != ctx.product["id"]:
            continue
        tok = sign_media(ctx.user_id, m["id"])
        out.append({"id": m["id"], "type": "video", "label": info.get("label") or m["filename"], "duration": m["duration"],
                    "status": m["status"], "abs": str(storage.abs(m["original_path"])),
                    "proxy_abs": str(storage.abs(m["proxy_path"])) if m["proxy_path"] else None,
                    "thumb_url": f"/api/v1/media/{m['id']}/thumb?token={tok}" if m["thumb_path"] else None})
    for ph in ((ctx.product.get("data") or {}).get("photos") or []):
        out.append({"id": "photo:" + ph, "type": "image", "label": "product photo", "duration": None, "status": "ready",
                    "abs": str(storage.abs(ph)), "proxy_abs": str(storage.abs(ph)),
                    "thumb_url": f"/api/v1/products/{ctx.product['id']}/photo?path={ph}&token={sign_media(ctx.user_id, ph)}"})
    return [b for b in out if b["status"] == "ready"]


def brolls_on_timeline(ctx) -> list[dict]:
    lib = {b["id"]: b for b in ctx.broll_library}
    out = []
    for b in ctx.tl["brolls"]:
        t0 = src_to_timeline(ctx.tl["clips"], b["media_id"], float(b["t"]))
        src = lib.get(b.get("source_id"))
        if t0 is None or not src:
            continue
        t1 = min(t0 + float(b.get("dur", 2)), ctx.tl["duration"])
        if t1 - t0 < 0.3:
            continue
        out.append({"id": b["id"], "t0": round(t0, 3), "t1": round(t1, 3), "label": src["label"], "type": src["type"],
                    "thumb_url": src["thumb_url"], "source_id": src["id"], "src_in": float(b.get("src_in", 0)),
                    "abs": src["abs"], "proxy_abs": src["proxy_abs"]})
    return out


def _match_score(label: str, text: str) -> float:
    lt, tt = set(ntokens(label)), set(ntokens(text))
    lt -= {"the", "a", "of", "and", "my", "product", "clip", "shot", "video", "mp4", "mov", "img"}
    return len(lt & tt) / max(len(lt), 1) if lt else 0.0


def broll_suggestions(ctx, max_items: int | None = None, at: float | None = None) -> list[dict]:
    """Pick moments where product footage supports what's being said (features, benefits, demos, product lines)
    and the product isn't already on screen. Matches labels to the spoken words; otherwise rotates the library."""
    lib = [b for b in ctx.broll_library]
    if not lib:
        return []
    used = [(b["t0"], b["t1"]) for b in ctx.brolls]
    vis = ctx.visibility["segments"]
    rows = ctx.unit_rows
    if at is not None:
        rows = [u for u in rows if u["t0"] - 0.05 <= at < u["t1"]] or rows[:0]
    cands = []
    for u in rows:
        if not u.get("speech") or u["t1"] - u["t0"] < 1.4:
            continue
        if at is None and (u["section"] not in ("feature", "benefit", "demonstration", "product_intro", "social_proof", "solution", "other")
                           or u is ctx.unit_rows[0]):
            continue
        t0 = u["t0"] + 0.35 if at is None else max(u["t0"], at)
        dur = min(2.6, u["t1"] - t0 - 0.1)
        if dur < 1.0:
            continue
        if any(a < t0 + dur and b > t0 for a, b in used) or any(a <= t0 and b >= t0 + dur for a, b in vis):
            continue
        best = max(lib, key=lambda b: _match_score(b["label"], u["text"]))
        score = _match_score(best["label"], u["text"])
        cands.append({"unit": u, "t0": t0, "dur": dur, "source": best, "score": score})
    cands.sort(key=lambda c: (-c["score"], c["t0"]))
    limit = max_items or max(1, math.ceil(ctx.tl["duration"] / 9))
    chosen, rot = [], 0
    for c in cands:
        if len(chosen) >= limit:
            break
        if any(abs(c["t0"] - x["t0"]) < 4 for x in chosen):
            continue
        if c["score"] == 0:  # no label match → rotate through the library for variety
            c["source"] = lib[rot % len(lib)]; rot += 1
        chosen.append(c)
    out = []
    for c in sorted(chosen, key=lambda c: c["t0"]):
        clip = next((k for k in ctx.tl["clips"] if k["t0"] <= c["t0"] < k["t1"]), None)
        if not clip:
            continue
        src_t = clip["s"] + (c["t0"] - clip["t0"]) * clip["speed"]
        s = c["source"]
        src_in = 0.0
        if s["type"] == "video" and s.get("duration"):
            src_in = max(0.0, min(float(s["duration"]) - c["dur"], float(s["duration"]) * 0.2))
        out.append({"id": f"br{int(c['t0'] * 1000)}", "media_id": clip["media_id"], "t": round(src_t, 3), "dur": round(c["dur"], 2),
                    "source_id": s["id"], "src_in": round(src_in, 2), "label": s["label"], "t0": round(c["t0"], 2),
                    "text": c["unit"]["text"][:60]})
    return out


# ---------------------------------------------------------------------------------------------------- text hook

MAX_HOOK_WORDS = 12
LEADING = {"so", "and", "okay", "ok", "um", "uh", "like", "well", "yeah", "alright", "now"}
BREAKS = {"until", "because", "but", "which", "so", "and"}


def _short(text: str) -> str:
    """Tighten a spoken hook into on-screen text without changing its meaning."""
    t = clean_display(text).strip().rstrip(".!")
    parts = re.split(r"(?<=[.!?])\s", t)
    words: list[str] = []
    for part in parts:  # join very short punchy sentences ("Don't. Get. These.") until there's a real line
        words += part.split()
        if len(words) >= 4:
            break
    while words and words[0].lower().strip(",") in LEADING:
        words.pop(0)
    if len(words) > MAX_HOOK_WORDS:
        cut = next((i for i in range(len(words) - 1, 3, -1) if words[i].lower() in BREAKS and i <= MAX_HOOK_WORDS), None)
        words = words[:cut] if cut else words[:MAX_HOOK_WORDS]
    out = " ".join(words).strip(" ,")
    return out[:1].upper() + out[1:]


def text_hook_ideas(ctx) -> list[dict]:
    """On-screen text for the first seconds — built only from the creator's own recorded hook lines and facts in the
    product profile (price, discount, benefits), so it never promises something that isn't true."""
    ideas: list[dict] = []
    seen = set()

    def add(text, source):
        k = text.lower()
        if text and k not in seen and len(text) <= 60:
            seen.add(k)
            ideas.append({"text": text, "source": source})

    for h in ctx.hooks[:3]:
        add(_short(h["text"]), "your hook")
    d = (ctx.product or {}).get("data") or {}
    name = (ctx.product or {}).get("name", "")
    price = str(d.get("price") or "").replace("$", "").strip()
    if price:
        add(f"Only ${price}?!", "product price")
    if d.get("discount"):
        add(f"{d['discount']} right now", "product discount")
    for b in (d.get("benefits") or [])[:2]:
        add(b[:1].upper() + b[1:], "product benefit")
    if name:
        add(f"Honest {name} review", "product name")
    if d.get("audience"):
        add(f"For {d['audience']}", "target audience")
    return ideas[:7]


# ---------------------------------------------------------------------------------------------------- retention map


def retention(ctx) -> dict:
    """Heuristic attention curve for the edited video (NOT a performance prediction) plus fixable warnings."""
    D = ctx.tl["duration"]
    if D <= 0:
        return {"curve": [], "warnings": []}
    step = 0.5
    n = int(D / step) + 1
    clips = ctx.tl["clips"]
    visual_events = [0.0]
    for a, b in zip(clips, clips[1:]):
        if a["media_id"] != b["media_id"] or abs(b["s"] - a["e"]) > 0.25 or a["props"].get("zoom") != b["props"].get("zoom"):
            visual_events.append(b["t0"])
    for br in ctx.brolls:
        visual_events += [br["t0"], br["t1"]]
    for o in ctx.overlays_tl:
        visual_events.append(o["t0"])
    visual_events.sort()
    prod = list(ctx.visibility["segments"]) + [[b["t0"], b["t1"]] for b in ctx.brolls]
    words = [w for w in ctx.view_words if w["kept"] and w["tl"] is not None]
    rows = ctx.unit_rows

    curve, v = [], 100.0
    last_vis_i = 0
    prod_seen = -1.0
    warn_static, warn_noprod, warn_slow = [], [], []
    for i in range(n):
        t = i * step
        while last_vis_i + 1 < len(visual_events) and visual_events[last_vis_i + 1] <= t:
            last_vis_i += 1
        since_vis = t - visual_events[last_vis_i]
        if any(a <= t <= b for a, b in prod):
            prod_seen = t
        since_prod = t - prod_seen if prod_seen >= 0 else t
        wps = sum(1 for w in words if t - 1.5 <= w["tl"] < t + 1.5) / 3.0
        drop = 0.35
        if t < 3 and rows and rows[0]["section"] != "hook":
            drop += 2.5
        if since_vis > 4:
            drop += 0.5 + 0.25 * (since_vis - 4); warn_static.append(t)
        if since_prod > 8 and (ctx.visibility["tracked"] or ctx.broll_library):
            drop += 0.4; warn_noprod.append(t)
        if 0.3 < wps < 1.7 and t > 2:
            drop += 0.8; warn_slow.append(t)
        v = max(5.0, v - drop * step * 2)
        curve.append([round(t, 2), round(v, 1)])

    def spans(ts, min_len):
        out, start, prev = [], None, None
        for t in ts:
            if start is None:
                start = prev = t
            elif t - prev > step + 1e-6:
                if prev - start + step >= min_len:
                    out.append([start, prev + step])
                start = t
            prev = t
        if start is not None and prev - start + step >= min_len:
            out.append([start, prev + step])
        return out

    warnings = []
    for a, b in spans(warn_static, 1.5):
        warnings.append({"kind": "static", "t0": a - 4, "t1": b, "message": f"No visual change for {b - a + 4:.0f}s",
                         "fix": {"action": "punch_in", "args": {"t": round(a, 2)}, "label": "Add zoom"}})
    for a, b in spans(warn_noprod, 1.0):
        fix = {"action": "add_broll", "args": {"at": round(a, 2)}, "label": "Show product here"} if ctx.broll_library else None
        warnings.append({"kind": "no_product", "t0": a - 8, "t1": b, "message": f"Product off-screen for {b - a + 8:.0f}s",
                         "fix": fix, "hint": None if fix else "Add product B-roll in Products to fix this in one tap"})
    for a, b in spans(warn_slow, 2.5):
        warnings.append({"kind": "slow", "t0": a, "t1": b, "message": "Slow pacing",
                         "fix": {"action": "tighten", "args": {"t0": round(a, 2), "t1": round(b, 2)}, "label": "Tighten"}})
    if rows:
        h = rows[0]
        if h["section"] == "hook" and h["t1"] - h["t0"] > 3.5:
            warnings.append({"kind": "long_hook", "t0": h["t0"], "t1": h["t1"], "message": "Hook takes too long to reach the point",
                             "fix": {"action": "find_best_hook", "args": {}, "label": "Try a tighter hook"}})
        elif h["section"] != "hook":
            warnings.append({"kind": "no_hook", "t0": 0, "t1": min(3, D), "message": "No clear hook in the first 3 seconds",
                             "fix": {"action": "find_best_hook", "args": {}, "label": "Use best hook"}})
        if not ctx.overlays_tl or min(o["t0"] for o in ctx.overlays_tl) > 1:
            warnings.append({"kind": "no_text_hook", "t0": 0, "t1": min(2.5, D), "message": "No on-screen text hook",
                             "fix": {"action": "add_text_hook", "args": {}, "label": "Add text hook"}})
        ctas = [u for u in rows if u["section"] == "cta"]
        if ctas and sum(u["t1"] - u["t0"] for u in ctas) > 5:
            warnings.append({"kind": "long_cta", "t0": ctas[0]["t0"], "t1": ctas[-1]["t1"], "message": "CTA takes too long",
                             "fix": {"action": "shorten_cta", "args": {}, "label": "Shorten CTA"}})
    for w in warnings:
        w["t0"], w["t1"] = round(max(0.0, w["t0"]), 2), round(min(D, w["t1"]), 2)
    warnings.sort(key=lambda w: w["t0"])
    return {"curve": curve, "warnings": warnings}


# ---------------------------------------------------------------------------------------------------- ad pieces


def ad_pieces(ctx) -> dict:
    """Recorded building blocks for batch ads: distinct hooks and distinct CTAs (retakes of the same line collapse)."""
    hooks = [h for h in ctx.hooks if h["score"] >= 40]
    ctas, seen = [], []
    for s in ctx.labelled:
        if s.get("section") != "cta" or not s.get("speech"):
            continue
        toks = set(tokens(s["text"]))
        if any(len(toks & o) / max(len(toks | o), 1) > 0.6 for o in seen):
            continue  # a retake of a CTA we already have
        seen.append(toks)
        ctas.append({"id": s["id"], "text": clean_display(s["text"]), "duration": round(s["we"] - s["ws"], 2)})
    return {"hooks": [{"id": h["id"], "text": h["text"], "categories": h["categories"], "score": h["score"]} for h in hooks],
            "ctas": ctas}
