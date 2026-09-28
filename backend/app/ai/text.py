"""Transcript utilities shared by the AI modules: normalization, sentence units, lexicons."""
from __future__ import annotations

import re

WORD_RE = re.compile(r"[a-z0-9$%']+")

FILLERS_ALWAYS = {"um", "uh", "umm", "uhh", "erm", "er", "ah", "hmm", "mm", "mhm", "uhm"}
FILLER_PHRASES_AGGRESSIVE = [("you", "know"), ("i", "mean"), ("sort", "of"), ("kind", "of"), ("basically",), ("literally",)]
# words after which "like" is a real verb/preposition, not a filler
LIKE_KEEP_PREV = {"i", "you", "we", "they", "would", "looks", "look", "feel", "feels", "felt", "just", "don't", "didn't",
                  "really", "seems", "sounds", "smells", "tastes", "things", "something", "anything", "nothing", "more",
                  "much", "exactly", "not", "also", "she", "he", "people", "most", "what", "who", "gonna", "love", "'d"}

# sentences starting with these depend on the previous one and must travel with it when reordering/dropping
CONNECTIVES = ("and ", "but ", "so that", "because ", "which ", "that's why", "thats why", "then ", "also ", "plus ", "or ",
               "cause ", "'cause ", "which is why", "and that")


def norm(t: str) -> str:
    return " ".join(WORD_RE.findall(t.lower()))


def tokens(t: str) -> list[str]:
    return WORD_RE.findall(t.lower())


NUM_WORDS = {"zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8",
             "nine": "9", "ten": "10", "twenty": "20", "thirty": "30", "fifty": "50", "hundred": "100"}


def ntok(t: str) -> str:
    """Comparison token: lowercase, number words → digits, light stemming (washed/wash, tees/tee)."""
    t = NUM_WORDS.get(t, t)
    for suf in ("ing", "ed", "es", "s"):
        if len(t) > len(suf) + 2 and t.endswith(suf):
            return t[: -len(suf)]
    return t


def ntokens(text: str) -> list[str]:
    out = []
    for t in tokens(text):
        # "59" said as "5 9" etc: split digit runs so both forms compare equal
        out += list(t) if t.isdigit() and len(t) <= 3 else [ntok(t)]
    return out


def refine_words(words: list[dict], silences: list[list[float]]) -> list[dict]:
    """ASR word timestamps often swallow the pauses around a word (e.g. a 4 s 'word').
    Trim leading/trailing silence measured from the audio so dead-space removal sees the real pauses."""
    if not silences:
        return words
    out = []
    for w in words:
        s, e = w["s"], w["e"]
        if e - s > 0.45:
            for a, b in silences:
                if b - a < 0.2:
                    continue
                if a <= s + 0.03 and s < b < e - 0.12:
                    s = b - 0.04
                if s + 0.12 < a < e and b >= e - 0.03:
                    e = a + 0.06
        out.append({**w, "s": round(s, 3), "e": round(max(e, s + 0.08), 3)} if (s, e) != (w["s"], w["e"]) else w)
    return out


def restart_spans(words: list[dict], max_span: int = 40) -> list[tuple[int, int]]:
    """Abandoned mid-sentence attempts: the creator starts a phrase, stops, and says it again
    ("with that nice baggy fit that every | with that nice baggy fit to help…").
    Returns (i, j) word-index spans [i, j) to remove — the earlier attempt; the later one is kept."""
    from difflib import SequenceMatcher
    toks = [ntokens(w["t"])[0] if ntokens(w["t"]) else "" for w in words]
    n = len(toks)
    cands: list[tuple[int, int]] = []
    for j in range(1, n):
        best = None
        for i in range(max(0, j - max_span), j):
            if toks[i] != toks[j] or not toks[i] or j - i < 2:
                continue
            if words[j]["s"] - words[i]["s"] > 45:
                continue
            A = toks[i:j]
            B = toks[j:j + len(A) + 3]
            m = sum(b.size for b in SequenceMatcher(None, A, B, autojunk=False).get_matching_blocks())
            prefix = 0
            while prefix < len(A) and j + prefix < n and A[prefix] == toks[j + prefix]:
                prefix += 1
            # the restart must begin the same way (≥2 identical words) and repeat most of the abandoned attempt
            if prefix >= 2 and m >= 3 and m >= 0.6 * len(A) and (best is None or (prefix, m) > (best[2], best[3])):
                best = (i, j, prefix, m)
        if best:
            cands.append((best[0], best[1]))
    # Keep spans that nest or are disjoint; drop ones that would cross into a take another span keeps.
    # Earliest-starting attempts win (a full-sentence restart beats a fragment matched inside it).
    cands.sort(key=lambda x: (x[0], -x[1]))
    spans: list[tuple[int, int]] = []
    for i, j in cands:
        if any(a < i < b < j or i < a < j < b for a, b in spans):
            continue
        spans.append((i, j))
    # nested spans are already covered by their outer span
    return sorted((i, j) for i, j in spans if not any(a <= i and j <= b and (a, b) != (i, j) for a, b in spans))


def word_key(media_id: str, i: int) -> str:
    return f"{media_id}:{i}"


def is_sentence_end(text: str) -> bool:
    return text.rstrip().endswith((".", "?", "!", "…"))


def build_sentences(media_id: str, words: list[dict], duration: float, pause_split: float = 0.7) -> list[dict]:
    """Split a media's words into sentence units whose ranges tile [0, duration] with no gaps.

    Boundaries sit at the midpoint of the silence between sentences, so no speech is ever split mid-word.
    A media with no speech becomes one unit (B-roll / product footage).
    """
    if not words:
        return [{"id": f"{media_id}@0", "media_id": media_id, "s": 0.0, "e": duration, "ws": 0.0, "we": duration,
                 "wi": [], "text": "", "speech": False}]
    groups: list[list[int]] = [[]]
    for i, w in enumerate(words):
        groups[-1].append(i)
        nxt = words[i + 1] if i + 1 < len(words) else None
        if nxt is None:
            break
        gap = nxt["s"] - w["e"]
        long_enough = len(groups[-1]) >= 2
        if (is_sentence_end(w["t"]) and long_enough) or gap >= pause_split or (len(groups[-1]) >= 40 and gap > 0.25):
            groups.append([])
    groups = [g for g in groups if g]
    out = []
    for gi, g in enumerate(groups):
        ws, we = words[g[0]]["s"], words[g[-1]]["e"]
        s = 0.0 if gi == 0 else (words[groups[gi - 1][-1]]["e"] + ws) / 2
        e = duration if gi == len(groups) - 1 else (we + words[groups[gi + 1][0]]["s"]) / 2
        s, e = round(s, 3), round(max(e, s + 0.01), 3)
        out.append({
            "id": f"{media_id}@{int(round(s * 1000))}", "media_id": media_id, "s": s, "e": e, "ws": ws, "we": we,
            "wi": g, "text": " ".join(words[i]["t"].strip() for i in g).strip(), "speech": True,
        })
    return out


def filler_indices(words: list[dict], aggressive: bool = False, remove_like: bool = True) -> list[list[int]]:
    """Return groups of word indices that are filler words/phrases."""
    out: list[list[int]] = []
    n = len(words)
    i = 0
    while i < n:
        t = norm(words[i]["t"])
        if t in FILLERS_ALWAYS:
            out.append([i]); i += 1; continue
        if remove_like and t == "like":
            prev = norm(words[i - 1]["t"]) if i > 0 else ""
            prev_raw = words[i - 1]["t"] if i > 0 else "."
            gap_before = words[i]["s"] - words[i - 1]["e"] if i > 0 else 1.0
            gap_after = words[i + 1]["s"] - words[i]["e"] if i + 1 < n else 1.0
            comma = words[i]["t"].strip().endswith(",") or prev_raw.strip().endswith(",")
            if prev in FILLERS_ALWAYS or (prev not in LIKE_KEEP_PREV and (comma or gap_before > 0.18 or gap_after > 0.18 or is_sentence_end(prev_raw))):
                out.append([i]); i += 1; continue
        if aggressive:
            hit = False
            for ph in FILLER_PHRASES_AGGRESSIVE:
                L = len(ph)
                if i + L <= n and tuple(norm(words[i + k]["t"]) for k in range(L)) == ph:
                    # only when set off by a pause/comma (discourse use), not "a kind of clay"
                    before = words[i]["s"] - words[i - 1]["e"] if i > 0 else 1
                    after = words[i + L]["s"] - words[i + L - 1]["e"] if i + L < n else 1
                    if before > 0.15 or after > 0.15 or words[i + L - 1]["t"].strip().endswith(","):
                        out.append(list(range(i, i + L))); i += L; hit = True; break
            if hit:
                continue
        i += 1
    return out


def stutter_indices(words: list[dict]) -> list[list[int]]:
    """Immediately repeated 1-3 word n-grams ("I I think", "it's so it's so good"), and cut-off words ("th-")."""
    out: list[list[int]] = []
    n = len(words)
    i = 0
    toks = [norm(w["t"]) for w in words]
    while i < n:
        if words[i]["t"].strip().endswith(("-", "—")) and len(toks[i]) <= 12:
            out.append([i]); i += 1; continue
        matched = False
        for L in (3, 2, 1):
            if i + 2 * L <= n and toks[i:i + L] == toks[i + L:i + 2 * L] and all(toks[i:i + L]):
                span = words[i + 2 * L - 1]["e"] - words[i]["s"]
                if span < 1.2 * L + 6 and not (L == 1 and toks[i] in {"very", "so", "really", "no", "bye", "ha", "go", "yes"}):
                    out.append(list(range(i, i + L))); i += L; matched = True; break
        if not matched:
            i += 1
    return out


FILLER_RE = re.compile(r"\b(um+|uh+|erm|uhm|hmm+)\b,?\s*", re.I)


def clean_display(text: str) -> str:
    """Display text without hesitation sounds (the recorded words are unchanged)."""
    t = FILLER_RE.sub("", text).strip()
    return t[:1].upper() + t[1:] if t else t


def fmt_t(t: float) -> str:
    m, s = divmod(max(t, 0), 60)
    return f"{int(m)}:{s:04.1f}"
