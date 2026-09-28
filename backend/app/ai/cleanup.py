"""Footage cleanup: dead space, fillers, stutters, mistakes/restarts, retakes, empty footage.

Every function returns *proposed ops* (source-time ranges) — nothing is deleted. Cuts are always snapped to word
boundaries with guard bands so the beginning/end of words is never clipped.
"""
from __future__ import annotations

from difflib import SequenceMatcher

from .text import build_sentences, filler_indices, norm, ntokens, restart_spans, stutter_indices, tokens

GUARD_BEFORE = 0.08   # keep this much audio before a word onset (breath/attack)
GUARD_AFTER = 0.13    # keep this much after a word ends (release / decay) — ASR end times run early

STRENGTHS = {
    "clean": {"min_pause": 0.15, "keep_pause": 0.07, "min_pause_in": 0.35, "keep_in": 0.07, "fillers": True, "like": False, "aggressive": False,
              "stutters": True, "retakes": True, "retake_sensitivity": 0.45, "lead": 0.25, "tail": 0.4,
              "min_clip": 0.5, "zoom_every": 0, "caption_preset": "clean"},
    "fast": {"min_pause": 0.15, "keep_pause": 0.05, "min_pause_in": 0.25, "keep_in": 0.05, "fillers": True, "like": True, "aggressive": False,
             "stutters": True, "retakes": True, "retake_sensitivity": 0.55, "lead": 0.12, "tail": 0.25,
             "min_clip": 0.45, "zoom_every": 0, "caption_preset": "tiktok"},
    "viral": {"min_pause": 0.12, "keep_pause": 0.04, "min_pause_in": 0.2, "keep_in": 0.04, "fillers": True, "like": True, "aggressive": True,
              "stutters": True, "retakes": True, "retake_sensitivity": 0.62, "lead": 0.06, "tail": 0.18,
              "min_clip": 0.35, "zoom_every": 0, "caption_preset": "high_energy"},
}

META_PHRASES = ["let me try that again", "let me redo", "let me do that again", "start over", "start again", "take two",
                "one more time", "i messed up", "messed that up", "mess that up", "i'll redo", "redo that", "hold on",
                "wait wait", "oops", "sorry let me", "okay again", "ok again", "cut that", "let me restart", "scratch that",
                "hang on", "from the top", "i said that wrong", "that was bad"]


def params_for(strength: str, overrides: dict | None = None) -> dict:
    p = dict(STRENGTHS.get(strength, STRENGTHS["fast"]))
    for k, v in (overrides or {}).items():
        if k in p and v is not None:
            p[k] = type(p[k])(v) if not isinstance(p[k], bool) else bool(v)
    return p


def _silent_fraction(silences: list[list[float]], s: float, e: float) -> float:
    if e <= s:
        return 1.0
    cov = sum(max(0.0, min(e, b) - max(s, a)) for a, b in silences)
    return cov / (e - s)


def dead_space(media: dict, words: list[dict], analysis: dict, p: dict) -> list[list]:
    """Pauses, lead-in setup footage, tail, and black/covered-lens spans."""
    mid, dur = media["id"], float(media["duration"] or 0)
    out: list[list] = []
    silences = analysis.get("silences", [])
    motion = analysis.get("motion", [])  # [[t, score]]

    def busy(s, e):  # visible action (e.g. a silent product demo) — don't treat as dead space
        vals = [m for t, m in motion if s <= t <= e]
        return bool(vals) and sum(vals) / len(vals) > 0.09

    if words:
        first, last = words[0], words[-1]
        if first["s"] - p["lead"] > 0.3:
            end = first["s"] - max(p["lead"], GUARD_BEFORE)
            if not busy(0, end) or end > 4:
                out.append([mid, 0.0, round(end, 3)])
        if dur - (last["e"] + p["tail"]) > 0.3:
            out.append([mid, round(last["e"] + max(p["tail"], GUARD_AFTER), 3), dur])
        for a, b in zip(words, words[1:]):
            gap = b["s"] - a["e"]
            if gap <= p["min_pause"]:
                continue
            half = p["keep_pause"] / 2
            s, e = a["e"] + max(GUARD_AFTER, half), b["s"] - max(GUARD_BEFORE, half)
            if e - s < 0.08:
                continue
            if silences and _silent_fraction(silences, s, e) < 0.5 and busy(s, e):
                continue  # something audible + visible is happening: likely a demo moment
            out.append([mid, round(s, 3), round(e, 3)])
    for a, b in analysis.get("blank", []):  # black frames / lens covered AND quiet
        if b - a >= 0.5 and (not silences or _silent_fraction(silences, a, b) > 0.7):
            out.append([mid, round(a, 3), round(b, 3)])
    if dur < 0.6:
        out.append([mid, 0.0, dur])  # accidental tap-record
    return out


def dead_space_audio(media: dict, words: list[dict], gaps: list[list[float]], p: dict) -> list[list]:
    """Pauses measured from the audio itself (not ASR timestamps, which drift by 100-300 ms).
    Between sentences: tighten pauses longer than min_pause down to keep_pause.
    Inside a sentence: only very long pauses are touched, so phrasing stays natural."""
    mid, dur = media["id"], float(media["duration"] or 0)
    out: list[list] = []
    if not gaps:
        return out
    speech_start = gaps[0][1] if gaps[0][0] <= 0.02 else 0.0
    speech_end = gaps[-1][0] if gaps[-1][1] >= dur - 0.05 else dur
    if words:  # setup mumbles / camera handling before the first real word and after the last one
        speech_start = max(speech_start, words[0]["s"])
        speech_end = min(speech_end, words[-1]["e"])
    lead, tail = 0.04, 0.2  # open the instant the first word starts; end just after the last one
    if speech_start - lead > 0.25:
        out.append([mid, 0.0, round(speech_start - lead, 3)])
    if speech_end + tail < dur - 0.25:
        out.append([mid, round(speech_end + tail, 3), dur])
    for a, b in gaps:
        if a <= 0.02 or b >= dur - 0.05:
            continue
        before = [w for w in words if w["s"] < a + 0.05]
        last = before[-1] if before else None
        sentence_end = last is None or last["t"].rstrip().endswith((".", "?", "!")) or (b - a) >= 1.2
        min_p, keep = (p["min_pause"], p["keep_pause"]) if sentence_end else (p["min_pause_in"], p["keep_in"])
        if b - a <= min_p:
            continue
        # cut out the moment the voice stops (short release so the last sound isn't clipped)
        # and cut in right as the next word starts
        s_, e_ = a + max(0.03, keep), b - 0.03
        if e_ - s_ >= 0.06:
            out.append([mid, round(s_, 3), round(e_, 3)])
    # stray sounds between phrases (breaths, lip smacks, "mm") that contain no words: cut them with the pause
    # around them instead of leaving a flash-frame clip
    from .align import voiced_regions
    for a, b in voiced_regions(gaps, dur):
        if b - a >= 0.8 or a < speech_start or b > speech_end:
            continue
        if not any(a - 0.02 <= (w["s"] + w["e"]) / 2 <= b + 0.02 for w in words):
            out.append([mid, round(a - 0.02, 3), round(b + 0.02, 3)])
    return out


def snap_to_gaps(ranges: list[list], gaps_by_media: dict[str, list], tol: float = 0.35,
                 words_by_media: dict[str, list] | None = None) -> tuple[list[list], int]:
    """Move both edges of every cut into real silence so no syllable is clipped. Cuts that can't land in
    silence are dropped (keeping a tiny imperfection beats chopping a word). Returns (ranges, dropped)."""
    out, dropped = [], 0
    for mid, a, b in ranges:
        gaps = gaps_by_media.get(mid)
        if not gaps:
            out.append([mid, a, b]); continue
        ga = [g for g in gaps if g[1] >= a - tol and g[0] <= a + 0.15]
        gb = [g for g in gaps if g[1] >= b - 0.2 and g[0] <= b + tol]
        if not ga or not gb:
            dropped += 1; continue
        g1 = min(ga, key=lambda g: abs(g[1] - a) if g[0] <= a else abs(g[0] - a))
        g2 = min(gb, key=lambda g: abs(g[1] - b))
        if words_by_media is not None and not (g2[0] - 0.03 <= b <= g2[1] + 0.03):
            # the kept take starts mid-phrase: if only a word or two separates us from the next silence,
            # cut through to it rather than leave a stranded fragment ("…if you the | best part")
            fwd = [g for g in gaps if b - 0.05 <= g[0] <= b + 0.8]
            ws = words_by_media.get(mid, [])
            if fwd and sum(1 for w in ws if b - 0.02 <= (w["s"] + w["e"]) / 2 <= fwd[0][0]) <= 3:
                g2 = fwd[0]
                b = g2[1]
        a2 = a if g1[0] + 0.05 <= a <= g1[1] - 0.03 else g1[0] + min(0.06, (g1[1] - g1[0]) / 2)
        b2 = b if g2[0] + 0.03 <= b <= g2[1] - 0.04 else g2[1] - min(0.04, (g2[1] - g2[0]) / 2)
        if b2 - a2 < 0.06:
            dropped += 1; continue
        out.append([mid, round(a2, 3), round(b2, 3)])
    return out, dropped


def _word_range(words, idxs):
    i0, i1 = idxs[0], idxs[-1]
    prev_e = words[i0 - 1]["e"] if i0 > 0 else words[i0]["s"] - 0.2
    next_s = words[i1 + 1]["s"] if i1 + 1 < len(words) else words[i1]["e"] + 0.2
    s = max(words[i0]["s"] - 0.04, prev_e + 0.03)
    e = min(words[i1]["e"] + 0.04, next_s - GUARD_BEFORE)
    return s, e


def fillers(media: dict, words: list[dict], p: dict) -> tuple[list[list], list[int]]:
    if not p["fillers"]:
        return [], []
    out, flagged = [], []
    for g in filler_indices(words, aggressive=p["aggressive"], remove_like=p["like"]):
        s, e = _word_range(words, g)
        if e - s > 0.03:
            out.append([media["id"], round(s, 3), round(e, 3)])
            flagged += g
    return out, flagged


def stutters(media: dict, words: list[dict], p: dict) -> list[list]:
    if not p["stutters"]:
        return []
    out = []
    for g in stutter_indices(words):
        i0, i1 = g[0], g[-1]
        nxt = words[i1 + 1]["s"] if i1 + 1 < len(words) else words[i1]["e"]
        prev_e = words[i0 - 1]["e"] if i0 > 0 else words[i0]["s"] - 0.2
        s = max(words[i0]["s"] - 0.04, prev_e + 0.03)
        e = nxt - GUARD_BEFORE
        if e - s > 0.05:
            out.append([media["id"], round(s, 3), round(e, 3)])
    return out


def mistakes(sentences: list[dict]) -> list[dict]:
    """Sentences that are the creator talking to themselves ('wait, let me redo that')."""
    out = []
    for s in sentences:
        if not s["speech"]:
            continue
        n = norm(s["text"])
        toks = n.split()
        if len(toks) <= 9 and any(ph in n for ph in META_PHRASES):
            out.append(s)
    return out


def _take_score(sent: dict, words: list[dict], product_visible: bool) -> float:
    ws = [words[i] for i in sent["wi"]]
    toks = tokens(sent["text"])
    n_fill = len(filler_indices(ws, aggressive=True))
    n_stut = len(stutter_indices(ws))
    conf = sum((w.get("p") or 0.9) for w in ws) / max(len(ws), 1)
    dur = max(sent["we"] - sent["ws"], 0.1)
    rate = len(toks) / dur
    score = len(toks) * 0.6 - n_fill * 1.2 - n_stut * 1.5 + conf * 3
    if sent["text"].rstrip().endswith((".", "!", "?")):
        score += 1.0
    if sent["text"].rstrip().endswith(("-", "—", ",")):
        score -= 3
    if rate < 1.3 or rate > 5.0:
        score -= 1.0
    if product_visible:
        score += 1.5
    return score


def retakes(sentences: list[dict], words_by_media: dict[str, list[dict]], sensitivity: float,
            product_hits: dict[str, list] | None = None) -> list[dict]:
    """Group repeated attempts of the same line and pick the best take.

    sensitivity 0..1 → similarity threshold 0.90..0.55. A take that is a strict prefix of a later one is a false start.
    Returns groups: {takes:[sentence ids], keep: id, remove:[ids], reason}.
    """
    thr = 0.90 - 0.35 * max(0.0, min(1.0, sensitivity))
    speech = [s for s in sentences if s["speech"] and len(tokens(s["text"])) >= 3]
    tokens_ = ntokens
    parent = {s["id"]: s["id"] for s in speech}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    reasons = {}
    for i, a in enumerate(speech):
        ta = tokens_(a["text"])
        for b in speech[i + 1:i + 7]:
            tb = tokens_(b["text"])
            if a["media_id"] == b["media_id"] and b["ws"] - a["we"] > 60:
                break
            prefix = len(ta) >= 2 and len(ta) < len(tb) and tb[:len(ta)] == ta
            head = len(ta) >= 3 and SequenceMatcher(None, ta, tb[:len(ta)]).ratio() >= 0.85 and len(ta) < len(tb) * 0.8
            sim = SequenceMatcher(None, ta, tb).ratio()
            if prefix or head or sim >= thr:
                parent[find(a["id"])] = find(b["id"])
                reasons[a["id"]] = "false start" if (prefix or head) else "repeated take"

    groups: dict[str, list[dict]] = {}
    for s in speech:
        groups.setdefault(find(s["id"]), []).append(s)
    out = []
    for g in groups.values():
        if len(g) < 2:
            continue

        def pv(sent):
            hits = (product_hits or {}).get(sent["media_id"], [])
            return any(sent["ws"] <= h[0] <= sent["we"] for h in hits)

        scored = []
        for order, sent in enumerate(g):
            sc = _take_score(sent, words_by_media[sent["media_id"]], pv(sent)) + order * 0.35  # later takes are usually the keeper
            is_prefix = any(
                tokens(o["text"])[:len(tokens(sent["text"]))] == tokens(sent["text"]) and len(tokens(o["text"])) > len(tokens(sent["text"]))
                for o in g if o is not sent)
            if is_prefix:
                sc -= 100
            scored.append((sc, sent))
        best = max(scored, key=lambda x: x[0])[1]
        out.append({"takes": [s["id"] for s in g], "texts": [s["text"] for s in g], "keep": best["id"],
                    "remove": [s["id"] for s in g if s is not best],
                    "reason": "false start" if any(reasons.get(s["id"]) == "false start" for s in g) else "repeated take"})
    return out


def enforce_min_clip(ranges: list[list], words_by_media: dict[str, list[dict]], min_clip: float) -> list[list]:
    """Avoid micro-clips: merge two removals separated by a sliver with no speech in it."""
    by_media: dict[str, list] = {}
    for r in ranges:
        by_media.setdefault(r[0], []).append(r)
    out = []
    for mid, rs in by_media.items():
        rs.sort(key=lambda r: r[1])
        merged: list[list] = []
        for r in rs:
            if merged and r[1] <= merged[-1][2] + min_clip:
                gap_s, gap_e = merged[-1][2], r[1]
                has_word = any(w["s"] < gap_e and w["e"] > gap_s for w in words_by_media.get(mid, [])) if gap_e > gap_s else False
                if not has_word:
                    merged[-1][2] = max(merged[-1][2], r[2])
                    continue
            merged.append(list(r))
        out += merged
    return out


def zoom_props(units: list[dict], every: float) -> list[dict]:
    """Alternate subtle punch-in zooms on speech units to add visual change (viral pacing)."""
    if every <= 0:
        return []
    ops, acc, on = [], 0.0, False
    for u in units:
        d = u["e"] - u["s"]
        acc += d
        if acc >= every and d > 0.8:
            on = not on
            acc = 0.0
            if on:
                ops.append({"unit_id": u["id"], "props": {"zoom": 1.12}})
    return ops


def analyze(media_list: list[dict], words_by_media: dict[str, list[dict]], analysis_by_media: dict[str, dict],
            p: dict) -> dict:
    """Full cleanup proposal. Returns grouped ranges + retake groups + flagged filler word keys."""
    groups = {"dead_space": [], "fillers": [], "stutters": [], "mistakes": [], "retakes": [], "restarts": []}
    restart_texts: list[str] = []
    filler_keys = []
    sentences_all = []
    for m in media_list:
        if m.get("kind", "video") != "video" or not m.get("duration"):
            continue
        words = words_by_media.get(m["id"], [])
        an = analysis_by_media.get(m["id"], {})
        gaps = an.get("gaps")
        if gaps and sum(g[1] - g[0] for g in gaps) > 0.02 * float(m["duration"]):
            # "one take" joins: measure pauses with the strict detector so breaths and word decay are treated
            # as silence — the cut lands where the voice actually stops and resumes where it actually starts
            groups["dead_space"] += dead_space_audio(m, words, an.get("soft_gaps") or gaps, p)
            groups["dead_space"] += [[m["id"], a, b] for a, b in an.get("blank", []) if b - a >= 0.5 and
                                     _silent_fraction(an.get("silences", []), a, b) > 0.7]
        else:
            groups["dead_space"] += dead_space(m, words, an, p)
        f, flagged = fillers(m, words, p)
        groups["fillers"] += f
        filler_keys += [f"{m['id']}:{words[i]['i']}" for i in flagged]
        groups["stutters"] += stutters(m, words, p)
        sentences_all += build_sentences(m["id"], words, float(m["duration"]))
    for m in media_list:
        words = words_by_media.get(m["id"], [])
        if not p["retakes"] or not words:
            continue
        from .align import voiced_regions
        regions = voiced_regions(analysis_by_media.get(m["id"], {}).get("gaps") or [], float(m["duration"] or 0))
        for i, j in restart_spans(words):
            prev_e = words[i - 1]["e"] if i > 0 else 0.0
            a = max(words[i]["s"] - 0.05, prev_e + 0.03)
            b = words[j]["s"] - GUARD_BEFORE
            # the restart begins mid-phrase (glued to the abandoned words with no pause): cutting there would
            # clip speech, so drop that short fragment too and resume at the next clean phrase
            reg = next((r for r in regions if r[0] - 0.02 <= words[j]["s"] <= r[1]), None)
            if reg and j > 0 and reg[0] - 0.02 <= (words[j - 1]["s"] + words[j - 1]["e"]) / 2 <= reg[1]:
                tail = [t for t in range(j, len(words)) if (words[t]["s"] + words[t]["e"]) / 2 <= reg[1]]
                if len(tail) <= 3:
                    b = reg[1] + 0.05
            if b - a > 0.1:
                groups.setdefault("restarts", []).append([m["id"], round(a, 3), round(b, 3)])
                restart_texts.append(" ".join(w["t"] for w in words[i:j]))
    for s in mistakes(sentences_all):
        groups["mistakes"].append([s["media_id"], s["s"], s["e"]])
    retake_groups = []
    if p["retakes"]:
        hits = {mid: a.get("product_hits", []) for mid, a in analysis_by_media.items()}
        retake_groups = retakes(sentences_all, words_by_media, p["retake_sensitivity"], hits)
        by_id = {s["id"]: s for s in sentences_all}
        for g in retake_groups:
            for sid in g["remove"]:
                s = by_id[sid]
                groups["retakes"].append([s["media_id"], s["s"], s["e"]])
    gaps_by_media = {m["id"]: analysis_by_media.get(m["id"], {}).get("gaps") for m in media_list}
    dropped = 0
    for k in ("fillers", "stutters", "restarts", "retakes", "mistakes"):
        groups[k], d = snap_to_gaps(groups[k], gaps_by_media, tol=0.5 if k in ("retakes", "mistakes") else 0.35,
                                    words_by_media=words_by_media if k == "restarts" else None)
        dropped += d
    groups["dead_space"] = enforce_min_clip(groups["dead_space"], words_by_media, p["min_clip"])
    # final pass across ALL cut types: leftover slivers with no words (pause remnants between two cuts) become
    # flash frames that make the edit feel jumpy — fold them into the neighbouring cuts.
    for m in media_list:
        mid = m["id"]
        allr = sorted([r[1], r[2]] for k in groups for r in groups[k] if r[0] == mid)
        merged: list[list[float]] = []
        for a, b in allr:
            if merged and a <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        words = words_by_media.get(mid, [])
        # every clip should begin the instant speech begins: if a cut ends in the middle of a pause,
        # extend it to just before the next word; if a cut starts late in a pause, pull it back to the kept pause
        an_ = analysis_by_media.get(mid, {}) or {}
        gaps = an_.get("soft_gaps") or an_.get("gaps") or []
        for a, b in merged:
            g = next((g for g in gaps if g[0] - 0.01 <= b <= g[1]), None)
            if g and g[1] - 0.04 - b > 0.06 and g[1] < float(m["duration"] or 0) - 0.05:
                groups["dead_space"].append([mid, round(b - 0.01, 3), round(g[1] - 0.04, 3)])
            g = next((g for g in gaps if g[0] <= a <= g[1] + 0.01), None) or \
                next((g for g in (an_.get("gaps") or []) if g[0] <= a <= g[1] + 0.01), None)
            if g and a - (g[0] + p["keep_pause"]) > 0.06 and g[0] > 0.05:
                groups["dead_space"].append([mid, round(g[0] + p["keep_pause"], 3), round(a + 0.01, 3)])
        for (a1, b1), (a2, b2) in zip(merged, merged[1:]):
            if a2 - b1 < max(p["min_clip"], 0.6) and not any(b1 <= (w["s"] + w["e"]) / 2 <= a2 for w in words):
                groups["dead_space"].append([mid, round(b1 - 0.01, 3), round(a2 + 0.01, 3)])
    return {"groups": groups, "retake_groups": retake_groups, "filler_keys": filler_keys, "sentences": sentences_all,
            "restart_texts": restart_texts, "unsafe_skipped": dropped}
