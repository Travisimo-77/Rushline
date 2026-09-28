"""Sales-structure detection, hook analysis and ad diagnostics.

Heuristic provider (always available). If an LLM provider is configured, `llm.refine_sections` can override
labels, but the output schema is identical so the rest of the app doesn't care which provider ran.
"""
from __future__ import annotations

import re

from .text import clean_display, norm, tokens

SECTIONS = ["hook", "problem", "pain_point", "product_intro", "solution", "feature", "benefit", "demonstration",
            "social_proof", "price", "discount", "urgency", "objection", "comparison", "cta", "other", "broll"]

SECTION_LABELS = {
    "hook": "Hook", "problem": "Problem", "pain_point": "Pain point", "product_intro": "Product intro",
    "solution": "Solution", "feature": "Feature", "benefit": "Benefit", "demonstration": "Demo",
    "social_proof": "Social proof", "price": "Price", "discount": "Discount", "urgency": "Urgency",
    "objection": "Objection", "comparison": "Comparison", "cta": "CTA", "other": "Other", "broll": "B-roll",
}

LEX: dict[str, list[tuple[str, float]]] = {
    "problem": [(r"\b(problem|issue|struggl\w*|tired of|sick of|hate (it )?when|annoying|frustrat\w*|never (works|stays|lasts)|"
                 r"keeps? (falling|breaking|getting)|can'?t (find|get|stand)|always (ends up|falls)|the worst|ruin\w*)\b", 2.0),
                (r"\b(flat|greasy|frizz\w*|dry|oily|messy|broke|expensive)\b", 0.6)],
    "pain_point": [(r"\b(embarrass\w*|insecure|wast\w+ (money|time)|gave up|so (bad|hard)|nothing work\w*|tried everything)\b", 2.0)],
    "product_intro": [(r"\b(this is (the|my|called)|meet|introducing|found (this|the)|this (little|new)|i('ve| have) been using|"
                       r"it'?s called|this right here|say hi to)\b", 2.0)],
    "solution": [(r"\b(that'?s (why|where)|solves?|fix(es|ed)?|the answer|finally|changed (everything|my)|game ?changer|"
                  r"so i (tried|got|switched)|until i (found|tried))\b", 1.8)],
    "feature": [(r"\b(comes with|made (with|of|from)|contains?|includes?|has (a|an|the)|\d+ ?(ml|oz|g|pack|patches|pieces|count)|"
                 r"ingredients?|formula|waterproof|rechargeable|size|material|built[- ]in)\b", 1.6)],
    "benefit": [(r"\b(so (you|your|it)|which means|lasts? (all|for)|without (leaving|making|feeling)|feels? (so|like)|"
                 r"makes? (my|your|it)|keeps? (my|your|it)|all day|saves? (you|me|time)|easier|softer|smoother|"
                 r"shinier|lighter|stronger|healthier|volume|glow\w*|results?)\b", 1.5)],
    "demonstration": [(r"\b(watch|look (at|how)|see (how|this|that)|let me show|i'?m (going|gonna) (to )?(put|apply|show|try|use|open)|"
                       r"right here|like this|check (this|it) out|just (apply|put|rub|spray)|open(ing)? (it|this))\b", 1.8)],
    "social_proof": [(r"\b(reviews?|stars?|everyone|everybody|viral|sold out|million|thousands?|best ?sell\w*|"
                      r"my (friends?|sister|mom)|dermatologists?|people are|went viral|trending)\b", 1.6)],
    "price": [(r"(\$\s?\d+|\b\d+ (dollars|bucks)\b|\bprice\b|\bcosts?\b|\bcheap\w*\b|\baffordable\b|\bunder \$?\d+|\bonly \$?\d+)", 2.2)],
    "discount": [(r"(\b\d+ ?(%|percent)( off)?\b|\bdiscount\w*\b|\bcoupon\b|\bcode\b|\bsale\b|\bdeal\b|\bbogo\b|\bfree shipping\b|\boff right now\b)", 2.2)],
    "urgency": [(r"\b(right now|today only|before it'?s gone|sells? out|selling out|limited|won'?t last|ends? (today|tonight|soon)|"
                 r"last (chance|day)|hurry|while (it|supplies) last)\b", 2.0)],
    "objection": [(r"\b(i know what you'?re thinking|you might (think|be wondering)|worried|skeptical|but (what about|is it)|"
                   r"is it worth|was scared|thought it (would|was)|won'?t it|doesn'?t it)\b", 2.0)],
    "comparison": [(r"\b(compared to|versus|vs\.?|better than|instead of|unlike|the other (one|brand)|dupe|than my old|cheaper than)\b", 2.0)],
    "cta": [(r"\b(link|orange (cart|basket|button)|shop (button|now)|tap (the|on)|click|grab (one|yours|it)|get (yours|one|it) (now|here|before)|"
             r"go (get|buy|check)|add (it )?to (your )?cart|check out|buy (it|now|this)|order (now|yours|it)|down below|in my bio|"
             r"you need (this|to try)|don'?t (sleep|miss)|run\b)\b", 2.4)],
}

HOOK_FEATURES: list[tuple[str, str, float]] = [
    ("Question", r"(\?$|^(why|how|what|did you|have you|do you|is (it|this)|are you|who|which|would you|can you)\b)", 2.0),
    ("Pain point", r"\b(if (you|your)|tired of|struggl\w*|hate (it )?when|stop \w+ing|can'?t (get|find|stand)|keeps? \w+ing)\b", 2.0),
    ("Price", r"(\$\s?\d+|\b\d+ (dollars|bucks)\b|\bcheap\b|\bunder \$?\d+|\bonly \$?\d+|\bprice\b|\bstill this cheap\b)", 2.2),
    ("Discount", r"(\b\d+ ?(%|percent)\b|\bsale\b|\bdiscount\b|\bdeal\b|\bfree\b)", 2.0),
    ("Curiosity", r"\b(secret|nobody|no one|didn'?t know|this is why|here'?s (why|how|what)|the reason|you need to|"
                  r"until i|thought (this|it) was|turns out|what happened|wait (for|till|until))\b", 2.2),
    ("Strong opinion", r"\b(best|worst|obsessed|favorite|hands down|game ?changer|holy grail|must[- ]have|"
                       r"overrated|overhyped|never going back)\b", 1.6),
    ("Contrarian", r"\b(don'?t buy|stop (using|buying)|unpopular opinion|everyone is wrong|not what you think|"
                   r"overhyped|lied to|scam)\b", 2.2),
    ("Urgency", r"\b(right now|today|before it'?s gone|sells? out|hurry|last chance)\b", 1.2),
    ("Demonstration", r"\b(watch (this|me|what)|look at (this|that)|see (this|that)|let me show)\b", 1.6),
    ("Before/After", r"\b(before and after|before (vs|versus)|the difference|look at the results?|after (one|two|a) (use|week|day))\b", 1.8),
    ("Story", r"^(so (i|my|yesterday|last)|i was|my (mom|friend|sister|husband|boyfriend|girlfriend)|when i|last (week|night|month))\b", 1.2),
    ("Surprise", r"\b(can'?t believe|no way|shocked|surprised|insane|crazy|wow|mind ?blown|unbelievable)\b", 1.6),
    ("Mistake", r"\b(mistake|doing it wrong|wrong way|messed up|i was wrong)\b", 2.0),
    ("Emotional", r"\b(cried|crying|love (this|it) so|changed my life|so happy|finally)\b", 1.3),
]


def _product_terms(product: dict | None) -> dict:
    if not product:
        return {"name": [], "features": [], "benefits": []}
    d = product.get("data", product)
    name_toks = [t for t in tokens(product.get("name", "")) if len(t) > 2]
    return {
        "name": name_toks,
        "features": [set(tokens(f)) for f in d.get("features", []) if f],
        "benefits": [set(tokens(b)) for b in d.get("benefits", []) if b],
        "price": str(d.get("price") or "").replace("$", "").strip(),
        "discount": str(d.get("discount") or "").strip(),
    }


def classify(sentences: list[dict], product: dict | None = None, visible: dict[str, bool] | None = None) -> list[dict]:
    """Label each sentence with a primary section + scores. Visible = sentence_id → product visible."""
    pt = _product_terms(product)
    out = []
    for idx, s in enumerate(sentences):
        if not s.get("speech", True):
            sec = "demonstration" if (visible or {}).get(s["id"]) else "broll"
            out.append({**s, "section": sec, "confidence": 0.5, "scores": {}})
            continue
        low = s["text"].lower()
        toks = set(tokens(s["text"]))
        scores = {k: 0.0 for k in LEX}
        for sec, pats in LEX.items():
            for pat, w in pats:
                if re.search(pat, low):
                    scores[sec] += w
        if pt["name"] and sum(t in toks for t in pt["name"]) >= max(1, len(pt["name"]) // 2):
            scores["product_intro"] += 1.6
        for f in pt["features"]:
            if f and len(f & toks) / len(f) >= 0.5:
                scores["feature"] += 1.4
        for b in pt["benefits"]:
            if b and len(b & toks) / len(b) >= 0.5:
                scores["benefit"] += 1.4
        if pt.get("price") and pt["price"] in low:
            scores["price"] += 1.5
        if (visible or {}).get(s["id"]):
            scores["demonstration"] += 0.8
        hook = hook_score(s, first_in_media=s.get("first_in_media", False))
        hook_bonus = hook["score"] / 100 * 3.0 if idx < 3 or s.get("first_in_media") else hook["score"] / 100 * 1.4
        scores["hook"] = hook_bonus if hook["score"] >= 45 else 0.0
        best = max(scores, key=scores.get)
        conf = scores[best]
        if conf < 0.9:
            best = "other"
        out.append({**s, "section": best, "confidence": round(min(conf / 4, 1.0), 2),
                    "scores": {k: round(v, 2) for k, v in scores.items() if v > 0}, "hook": hook})
    return out


def hook_score(s: dict, first_in_media: bool = False) -> dict:
    text = s["text"].strip()
    low = norm(text) if not text.endswith("?") else norm(text) + "?"
    raw_low = text.lower()
    score = 0.0
    cats = []
    for cat, pat, w in HOOK_FEATURES:
        if re.search(pat, raw_low) or re.search(pat, low):
            score += w
            cats.append(cat)
    n = len(tokens(text))
    dur = s.get("we", 0) - s.get("ws", 0)
    if 4 <= n <= 14:
        score += 1.0
    elif n > 22:
        score -= 1.5
    if dur > 4.5:
        score -= 1.0
    if re.search(r"\byou(r)?\b", raw_low):
        score += 0.5
    if first_in_media:
        score += 0.6
    return {"score": int(max(0, min(100, score / 6.0 * 100))), "categories": cats or ["Statement"]}


def find_hooks(labelled: list[dict], limit: int = 6) -> list[dict]:
    """Ranked hook candidates — only lines the creator actually recorded."""
    seen = set()
    cands = []
    for s in labelled:
        if not s.get("speech", True):
            continue
        h = s.get("hook") or hook_score(s)
        key = norm(s["text"])
        if key in seen or len(tokens(s["text"])) < 3:
            continue
        seen.add(key)
        if h["score"] >= 30:
            cands.append({"id": s["id"], "media_id": s["media_id"], "text": clean_display(s["text"]), "score": h["score"],
                          "categories": h["categories"], "duration": round(s["we"] - s["ws"], 2), "s": s["s"], "e": s["e"]})
    cands.sort(key=lambda c: -c["score"])
    return cands[:limit]


def diagnostics(ordered: list[dict], duration: float, target: float | None, vis: dict | None) -> list[dict]:
    """Human-readable structure feedback. `ordered` = labelled sentences in timeline order with t0/t1."""
    notes = []
    secs = [o["section"] for o in ordered]
    present = set(secs)

    def first(sec):
        for o in ordered:
            if o["section"] == sec:
                return o
        return None

    if not ordered:
        return [{"level": "info", "code": "empty", "message": "Nothing on the timeline yet."}]
    h = ordered[0]
    if h["section"] != "hook" and (h.get("hook") or {}).get("score", 0) < 45:
        notes.append({"level": "warn", "code": "weak_opening", "message": "Your video doesn't open with a clear hook.",
                      "fix": "find_best_hook"})
    elif h["t1"] - h["t0"] > 4.0:
        notes.append({"level": "warn", "code": "long_hook", "message": f"Hook takes {h['t1'] - h['t0']:.1f}s to land — aim for under 3s.",
                      "fix": None})
    if "cta" not in present:
        notes.append({"level": "warn", "code": "no_cta", "message": "No clear CTA detected. Tell viewers what to do (e.g. tap the product link).",
                      "fix": None})
    else:
        c = [o for o in ordered if o["section"] == "cta"]
        cta_len = sum(o["t1"] - o["t0"] for o in c)
        if cta_len > 6:
            notes.append({"level": "info", "code": "long_cta", "message": f"CTA runs {cta_len:.1f}s — shorter CTAs usually hold attention better.",
                          "fix": "shorten_cta"})
        if ordered[-1]["section"] != "cta" and ordered.index(c[-1]) < len(ordered) - 2:
            notes.append({"level": "info", "code": "cta_not_last", "message": "Your CTA isn't near the end.", "fix": "restructure"})
    pi, pr = first("product_intro"), first("problem") or first("pain_point")
    if pi and pr and pi["t0"] < pr["t0"]:
        notes.append({"level": "info", "code": "product_before_problem",
                      "message": "You introduce the product before clearly establishing the problem.", "fix": "restructure"})
    if "problem" not in present and "pain_point" not in present:
        notes.append({"level": "info", "code": "no_problem", "message": "No problem/pain point detected — problem-first ads often build more context."})
    n_feat = secs.count("feature")
    if n_feat >= 2 and "benefit" not in present:
        notes.append({"level": "warn", "code": "features_no_benefits",
                      "message": "You mention several features but don't explain why they matter to the customer."})
    if "demonstration" not in present and not (vis and vis.get("total", 0) > 2):
        notes.append({"level": "warn", "code": "no_demo", "message": "You never visually demonstrate the product."})
    if vis and vis.get("first") is not None and vis["first"] > 4:
        notes.append({"level": "warn", "code": "product_late", "message": f"Product first appears at {vis['first']:.1f}s.",
                      "fix": "show_product_earlier"})
    if vis and vis.get("longest_gap", 0) > 10 and duration > 12:
        notes.append({"level": "info", "code": "product_absent", "message": f"Product is off-screen for {vis['longest_gap']:.0f}s in a row."})
    if secs.count("benefit") >= 4:
        notes.append({"level": "info", "code": "many_benefits", "message": "Lots of benefits — consider keeping the 2 strongest.", "fix": "remove_repetition"})
    if target and duration > target * 1.1:
        notes.append({"level": "info", "code": "over_target", "message": f"Video is {duration:.1f}s; target is {target:.0f}s.", "fix": "fit_duration"})
    return notes
