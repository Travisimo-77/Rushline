"""Non-destructive edit model.

A version's timeline is never stored — it is *derived* by replaying its enabled ops, in sequence, over the
immutable source media + transcript. Ops are expressed in *source time* (media_id + seconds), so any single op
can be disabled (undone) at any point in history and the rest still replay correctly.

Op vocabulary
-------------
remove        {ranges:[[media_id,s,e],...]}                 hide source ranges (dead space, fillers, retakes, manual)
restore       {ranges:[[media_id,s,e],...]}                 un-hide source ranges
order         {unit_ids:[...]}                               reorder units (AI restructure / drag)
move          {unit_id, after:unit_id|null}                  move one unit
split         {media_id, t}                                  split the unit containing t
duplicate     {unit_id}                                      insert a copy of a unit after it
drop          {unit_id}                                      remove a unit instance from the sequence
props         {unit_id, props:{speed,volume,zoom,rotate,pan_x,pan_y,mute,brightness,contrast,saturation}}
settings      {patch:{captions:{...}, audio:{...}, color:{...}, output:{...}}}
caption_text  {key, text}                                    override caption text for a word
product_tag   {media_id, s, e, visible}                      manual product-visibility tag
text_overlay  {id, media_id, t, dur, text, y, style}         text overlay anchored to source time
broll         {id, media_id, t, dur, source:{type,media_id|path}, src_in}   picture overlay (product B-roll) anchored
                                                             to source time; the main audio keeps playing underneath
"""
from __future__ import annotations

import copy
from typing import Any

from .ai.text import build_sentences, word_key

OP_KINDS = {"remove", "restore", "order", "move", "split", "duplicate", "drop", "props", "settings", "caption_text",
            "product_tag", "text_overlay", "remove_overlay", "broll", "remove_broll"}

DEFAULT_SETTINGS: dict[str, Any] = {
    "captions": {
        "enabled": False, "preset": "tiktok",  # off by default; creators turn them on in Style or via "Add captions" "font": "Poppins", "size": 6.2, "y": 62, "color": "#FFFFFF",
        "highlight": "#FFD84D", "outline": 7, "shadow": 2, "background": False, "bg_color": "#000000B0",
        "uppercase": False, "words_per_line": 3, "mode": "phrase", "animation": "pop", "weight": 800, "emphasis": True,
    },
    "audio": {"enhance": False, "denoise": 0.6, "normalize": True, "target_lufs": -14, "voice": True},
    "color": {"brightness": 0.0, "contrast": 1.0, "saturation": 1.0, "temperature": 0, "sharpen": 0.0},
    "output": {"aspect": "9:16"},
    "video": {"soft_cuts": True, "smooth_cuts": False, "smooth_zoom": 1.08},
}


def smooth_cuts(clips: list[dict], zoom: float = 1.08) -> list[dict]:
    """Hide jump cuts: when two consecutive clips come from the same shot with footage removed between them,
    alternate framing (100% ↔ ~108%) so the cut reads as an intentional edit instead of a glitchy skip."""
    out, alt = [], False
    prev = None
    for c in clips:
        # only real jumps (≥0.8 s of footage skipped) get the punch-in; tightened pauses stay on the same framing
        if prev is not None and prev["media_id"] == c["media_id"] and abs(c["s"] - prev["e"]) >= 0.8:
            alt = not alt
        elif prev is not None and prev["media_id"] != c["media_id"]:
            alt = False
        base = float(c["props"].get("zoom", 1.0) or 1.0)
        out.append(dict(c, props={**c["props"], "zoom": round(base * zoom, 3)}) if alt else c)
        prev = c
    return out


def deep_merge(a: dict, b: dict) -> dict:
    out = copy.deepcopy(a)
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


class Intervals:
    """Tagged interval set per media. Each piece remembers which op produced it."""

    def __init__(self):
        self.d: dict[str, list[list]] = {}

    def add(self, media_id: str, s: float, e: float, tag: str):
        if e - s <= 1e-4:
            return
        self.subtract(media_id, s, e)
        self.d.setdefault(media_id, []).append([s, e, tag])
        self.d[media_id].sort(key=lambda x: x[0])

    def subtract(self, media_id: str, s: float, e: float):
        out = []
        for a, b, tag in self.d.get(media_id, []):
            if b <= s or a >= e:
                out.append([a, b, tag]); continue
            if a < s:
                out.append([a, s, tag])
            if b > e:
                out.append([e, b, tag])
        self.d[media_id] = out

    def get(self, media_id: str) -> list[list]:
        return self.d.get(media_id, [])

    def covering(self, media_id: str, s: float, e: float) -> str | None:
        mid = (s + e) / 2
        for a, b, tag in self.get(media_id):
            if a <= mid <= b:
                return tag
        return None


def base_units(media: list[dict], words_by_media: dict[str, list[dict]]) -> list[dict]:
    units = []
    for m in media:
        if m.get("kind", "video") != "video" or not m.get("duration"):
            continue
        for sent in build_sentences(m["id"], words_by_media.get(m["id"], []), float(m["duration"])):
            units.append({"id": sent["id"], "media_id": m["id"], "s": sent["s"], "e": sent["e"], "props": {},
                          "origin": sent["id"]})
    return units


def replay(media: list[dict], words_by_media: dict[str, list[dict]], ops: list[dict]) -> dict:
    units = base_units(media, words_by_media)
    removed = Intervals()
    settings = copy.deepcopy(DEFAULT_SETTINGS)
    caption_over: dict[str, str] = {}
    tags = Intervals()
    untag = Intervals()
    overlays: dict[str, dict] = {}
    brolls: dict[str, dict] = {}
    skipped: list[str] = []
    dup_n = 0

    def find(uid):
        for i, u in enumerate(units):
            if u["id"] == uid:
                return i
        return -1

    for op in ops:
        if not op.get("enabled", 1):
            continue
        k, p, oid = op["kind"], op["params"], op["id"]
        try:
            if k == "remove":
                for mid, s, e in p["ranges"]:
                    removed.add(mid, float(s), float(e), oid)
            elif k == "restore":
                for mid, s, e in p["ranges"]:
                    removed.subtract(mid, float(s), float(e))
            elif k == "order":
                idx = {uid: n for n, uid in enumerate(p["unit_ids"])}
                known = [u for u in units if u["id"] in idx]
                known.sort(key=lambda u: idx[u["id"]])
                # units not named in the op (e.g. created by a later split) stay glued to their predecessor
                glue: dict[str | None, list] = {}
                last = None
                for u in units:
                    if u["id"] in idx:
                        last = u["id"]
                    else:
                        glue.setdefault(last, []).append(u)
                result = list(glue.get(None, []))
                for u in known:
                    result.append(u)
                    result.extend(glue.get(u["id"], []))
                units = result
            elif k == "move":
                i = find(p["unit_id"])
                if i < 0:
                    skipped.append(oid); continue
                u = units.pop(i)
                if p.get("after") is None:
                    units.insert(0, u)
                else:
                    j = find(p["after"])
                    units.insert(j + 1 if j >= 0 else len(units), u)
            elif k == "split":
                mid_, t = p["media_id"], float(p["t"])
                for i, u in enumerate(units):
                    if u["media_id"] == mid_ and u["s"] + 0.02 < t < u["e"] - 0.02:
                        right = dict(u, s=t, id=f"{mid_}@{int(round(t * 1000))}" + ("+" + u["id"].split("+")[1] if "+" in u["id"] else ""),
                                     props=dict(u["props"]))
                        units[i] = dict(u, e=t)
                        units.insert(i + 1, right)
                        break
                else:
                    skipped.append(oid)
            elif k == "duplicate":
                i = find(p["unit_id"])
                if i < 0:
                    skipped.append(oid); continue
                dup_n += 1
                units.insert(i + 1, dict(units[i], id=f"{units[i]['id'].split('+')[0]}+{dup_n}", props=dict(units[i]["props"])))
            elif k == "drop":
                i = find(p["unit_id"])
                if i < 0:
                    skipped.append(oid); continue
                units.pop(i)
            elif k == "props":
                i = find(p["unit_id"])
                if i < 0:
                    skipped.append(oid); continue
                units[i] = dict(units[i], props={**units[i]["props"], **p["props"]})
            elif k == "settings":
                settings = deep_merge(settings, p["patch"])
            elif k == "caption_text":
                caption_over[p["key"]] = p["text"]
            elif k == "product_tag":
                if p.get("visible", True):
                    tags.add(p["media_id"], float(p["s"]), float(p["e"]), oid)
                    untag.subtract(p["media_id"], float(p["s"]), float(p["e"]))
                else:
                    untag.add(p["media_id"], float(p["s"]), float(p["e"]), oid)
                    tags.subtract(p["media_id"], float(p["s"]), float(p["e"]))
            elif k == "text_overlay":
                overlays[p["id"]] = dict(p)
            elif k == "remove_overlay":
                overlays.pop(p["id"], None)
            elif k == "broll":
                brolls[p["id"]] = dict(p)
            elif k == "remove_broll":
                brolls.pop(p["id"], None)
        except (KeyError, TypeError, ValueError):
            skipped.append(oid)

    # materialize clips: unit range minus removed ranges
    clips = []
    t = 0.0
    for u in units:
        pieces = [[u["s"], u["e"]]]
        for a, b, _ in removed.get(u["media_id"]):
            nxt = []
            for s, e in pieces:
                if b <= s or a >= e:
                    nxt.append([s, e]); continue
                if a > s:
                    nxt.append([s, a])
                if b < e:
                    nxt.append([b, e])
            pieces = nxt
        speed = float(u["props"].get("speed", 1.0) or 1.0)
        for n, (s, e) in enumerate(pieces):
            if e - s < 0.04:
                continue
            dur = (e - s) / speed
            clips.append({"id": f"{u['id']}#{n}", "unit_id": u["id"], "origin": u["origin"], "media_id": u["media_id"],
                          "s": round(s, 3), "e": round(e, 3), "t0": round(t, 3), "t1": round(t + dur, 3),
                          "speed": speed, "props": u["props"]})
            t += dur
    return {"units": units, "clips": clips, "duration": round(t, 3), "removed": removed, "settings": settings,
            "caption_over": caption_over, "tags": tags, "untags": untag, "overlays": list(overlays.values()),
            "brolls": list(brolls.values()),
            "skipped": skipped}


def src_to_timeline(clips: list[dict], media_id: str, t: float) -> float | None:
    for c in clips:
        if c["media_id"] == media_id and c["s"] <= t < c["e"]:
            return c["t0"] + (t - c["s"]) / c["speed"]
    return None


def map_range(clips: list[dict], media_id: str, s: float, e: float) -> list[tuple[float, float]]:
    """Project a source range onto the edited timeline (may yield several pieces)."""
    out = []
    for c in clips:
        if c["media_id"] != media_id:
            continue
        a, b = max(s, c["s"]), min(e, c["e"])
        if b > a:
            out.append((c["t0"] + (a - c["s"]) / c["speed"], c["t0"] + (b - c["s"]) / c["speed"]))
    return out


def word_states(clips: list[dict], words_by_media: dict[str, list[dict]], removed: Intervals) -> list[dict]:
    """Every transcript word with kept/removed status and (if kept) its first timeline position."""
    out = []
    by_media: dict[str, list[dict]] = {}
    for c in clips:
        by_media.setdefault(c["media_id"], []).append(c)
    for mid, words in words_by_media.items():
        cl = by_media.get(mid, [])
        for w in words:
            m = (w["s"] + w["e"]) / 2
            tpos = None
            for c in cl:
                if c["s"] <= m < c["e"]:
                    tpos = c["t0"] + (w["s"] - c["s"]) / c["speed"]
                    break
            out.append({"key": word_key(mid, w["i"]), "media_id": mid, "i": w["i"], "t": w["t"], "s": w["s"], "e": w["e"],
                        "kept": tpos is not None, "tl": None if tpos is None else round(max(tpos, 0), 3),
                        "by": None if tpos is not None else removed.covering(mid, w["s"], w["e"]),
                        "filler": bool(w.get("filler")), "p": w.get("p")})
    return out


def caption_words(clips: list[dict], words_by_media: dict[str, list[dict]], caption_over: dict[str, str]) -> list[dict]:
    """Kept words in timeline order with timeline timings (duplicates appear once per clip)."""
    out = []
    for c in clips:
        for w in words_by_media.get(c["media_id"], []):
            m = (w["s"] + w["e"]) / 2
            if c["s"] <= m < c["e"]:
                key = word_key(c["media_id"], w["i"])
                text = caption_over.get(key, w["t"]).strip()
                if not text:
                    continue
                s = c["t0"] + (max(w["s"], c["s"]) - c["s"]) / c["speed"]
                e = c["t0"] + (min(w["e"], c["e"]) - c["s"]) / c["speed"]
                out.append({"key": key, "text": text, "t0": round(s, 3), "t1": round(max(e, s + 0.05), 3), "clip": c["id"]})
    return out
