"""Shop-safe check: flags language that commonly gets TikTok Shop / affiliate videos restricted or pulled.

It never rewrites anything on its own — each issue carries why it's risky and a suggested alternative, and the
editor offers one-tap fixes (cut the line / edit the text) that the creator chooses to apply.
Heuristic guidance, not legal advice; platform policies change, so rules live in one list that's easy to update.
"""
from __future__ import annotations

import re

# (pattern, title, why, suggestion, severity)
RULES = [
    (r"\bguarantee[sd]?\b|\b100 ?% (results|guaranteed|effective)\b", "Guaranteed results",
     "Absolute guarantees are rarely substantiated and are commonly restricted in shop/ad policies.", "Use \"it worked for me\" or \"results may vary\".", "high"),
    (r"\b(cures?|heals?|treats?|prevents?) (acne|eczema|cancer|hair ?loss|anxiety|depression|disease|infection|psoriasis|diabetes|arthritis)\b",
     "Unsupported medical claim", "Disease/treatment claims typically require regulatory approval.", "Describe your experience (\"my skin looks calmer\").", "high"),
    (r"\b(fda[- ]approved|clinically proven|doctor[- ]recommended|dermatologist[- ]approved|dermatologist[- ]recommended)\b",
     "Unverified authority claim", "Only say this if the brand can document it.", "Remove, or add it to the product's approved claims.", "high"),
    (r"\b(lose|lost|drop(ped)?) \d+ ?(pounds|lbs|kg|kilos)\b|\bburns? (fat|calories)\b", "Weight-loss claim",
     "Specific weight-loss results are heavily restricted.", "Focus on how the product fits your routine.", "high"),
    (r"\b(overnight|instantly|in (one|1) day) (results|fix|cure|gone)\b|\bcompletely gone\b|\bnever again\b",
     "Absolute / exaggerated promise", "Implies results every viewer will get.", "Soften: \"I noticed a difference after a few uses\".", "medium"),
    (r"\bpermanent(ly)?\b", "Permanence claim", "Permanence is hard to substantiate.", "Say \"long-lasting\" if accurate.", "low"),
    (r"\b(only \d+ left|last \d+ (units|in stock)|selling out (fast|today)|about to sell out|won'?t be restocked|ends? (tonight|today|at midnight))\b",
     "Possible fake scarcity / urgency", "Scarcity and deadline claims must be true at time of posting.", "Only mention limits the brand confirmed.", "medium"),
    (r"\b(miracle|magic cure|risk[- ]free)\b", "Hyperbolic claim", "Commonly flagged as misleading.", "Describe the concrete benefit instead.", "medium"),
    (r"\b\d{2,3} ?% of (people|users|customers|women|men)\b", "Unverified statistic", "Statistics need a documented source.",
     "Attach the source or remove the number.", "medium"),
    (r"\b(#1|number one|best[- ]selling) (in the (world|country|us)|brand|product)\b|\bbest in the world\b", "Unverified superlative",
     "\"#1 / best-selling\" claims need proof.", "Say \"one of my favourites\" or cite the source.", "medium"),
    (r"\b(link in (my )?bio|dm me|comment (for|\"?link\"?) (the )?link|check (my|the) website|on amazon|use my code on)\b",
     "Sends viewers off TikTok Shop", "Shop videos should point to the in-app product link, not outside links.", "Say \"tap the orange cart\" or \"tap the product link\".", "high"),
    (r"\b(free gift|giveaway|win (a|this))\b", "Giveaway / free-gift mention", "Promotions must match an active official promotion.",
     "Only mention promotions that are live on the listing.", "low"),
]

MONEY = re.compile(r"\$\s?(\d+(?:\.\d{1,2})?)|\b(\d+(?:\.\d{1,2})?) (?:dollars|bucks)\b")
PCT = re.compile(r"\b(\d{1,2}) ?(?:%|percent)(?: off)?\b")


def _num(x) -> float | None:
    try:
        return float(re.sub(r"[^\d.]", "", str(x)))
    except ValueError:
        return None


def scan(text_items: list[dict], product: dict | None = None) -> list[dict]:
    """text_items: [{text, t0?, where, ref?}] → issues [{id, issue, severity, match, why, suggestion, text, t0, where, ref}]."""
    d = (product or {}).get("data", product or {}) or {}
    approved = [a.lower() for a in d.get("approved_claims", []) if a]
    avoid = [a.lower() for a in d.get("avoid_claims", []) if a]
    price = _num(d.get("price")) if d.get("price") else None
    disc = _num(d.get("discount")) if d.get("discount") and "%" in str(d.get("discount")) else None
    shipping = str(d.get("shipping") or "").lower()
    issues = []

    def add(it, title, match, why, sug, sev):
        issues.append({"id": f"{len(issues)}", "issue": title, "severity": sev, "match": match, "why": why, "suggestion": sug,
                       "text": it["text"], "t0": it.get("t0"), "where": it.get("where", "speech"), "ref": it.get("ref")})

    for it in text_items:
        low = it["text"].lower()
        for pat, title, why, alt, sev in RULES:
            m = re.search(pat, low)
            if m and not any(m.group(0) in a for a in approved):
                add(it, title, m.group(0), why, alt, sev)
        for a in avoid:
            if a and a in low:
                add(it, "Claim the brand asked you to avoid", a, "Listed under 'Claims to avoid' in the product profile.",
                    "Remove this line or rephrase.", "high")
        # consistency with the product profile (wrong price/discount is a top reason for shop violations)
        if price:
            for m in MONEY.finditer(low):
                val = float(m.group(1) or m.group(2))
                if abs(val - price) > 0.51 and not (disc and abs(val - price * (1 - disc / 100)) <= 0.6):
                    add(it, "Price doesn't match the listing", m.group(0).strip(),
                        f"The product profile says ${price:g}. Mismatched prices mislead buyers.", f"Say ${price:g} (or update the product profile).", "high")
        if disc is not None:
            for m in PCT.finditer(low):
                if "off" in low[m.start(): m.end() + 5] or "discount" in low or "sale" in low:
                    if abs(float(m.group(1)) - disc) > 0.5:
                        add(it, "Discount doesn't match the listing", m.group(0),
                            f"The product profile says {disc:g}% off.", f"Say {disc:g}% off (or update the profile).", "high")
        if "free shipping" in low and "free" not in shipping:
            add(it, "Free shipping not in the product profile", "free shipping", "Only claim free shipping if the listing offers it.",
                "Remove it or add free shipping to the product profile.", "medium")
    return issues


def summary(issues: list[dict]) -> dict:
    high = sum(1 for i in issues if i["severity"] == "high")
    return {"status": "risky" if high else ("review" if issues else "safe"), "high": high, "total": len(issues)}
