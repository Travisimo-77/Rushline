"""Creator performance learning: results entered per exported video are joined with what the edit looked like
(hook type, length, product timing, text hook, B-roll…) to surface patterns in the creator's OWN history.
Every insight is framed as a correlation with its sample size — never a guarantee."""
from __future__ import annotations

import csv
import io
import math
import re

from .. import db

METRICS = {  # key: (label, higher_is_better, unit)
    "views": ("views", True, ""), "avg_watch_time": ("avg watch time", True, "s"), "completion_rate": ("completion rate", True, "%"),
    "hold_2s": ("2-second hold", True, "%"), "hold_6s": ("6-second hold", True, "%"), "likes": ("likes", True, ""),
    "comments": ("comments", True, ""), "shares": ("shares", True, ""), "ctr": ("click-through rate", True, "%"),
    "product_clicks": ("product clicks", True, ""), "orders": ("orders", True, ""), "gmv": ("GMV", True, "$"),
}
PRIORITY = ["gmv", "orders", "product_clicks", "ctr", "completion_rate", "hold_2s", "avg_watch_time", "views"]


def snapshot(ctx) -> dict:
    """What the edit looked like — the 'features' we learn from."""
    rows = ctx.unit_rows
    first = rows[0] if rows else {}
    hook = first.get("hook") or {}
    D = ctx.tl["duration"]
    cuts = sum(1 for a, b in zip(ctx.tl["clips"], ctx.tl["clips"][1:]) if a["media_id"] != b["media_id"] or abs(b["s"] - a["e"]) > 0.05)
    ctas = [u for u in rows if u["section"] == "cta"]
    return {
        "duration": round(D, 1), "hook_type": (hook.get("categories") or ["Statement"])[0] if first.get("section") == "hook" else "No clear hook",
        "hook_text": (first.get("text") or "")[:120], "template": (ctx.version.get("meta") or {}).get("template") or "main edit",
        "product_first": ctx.visibility.get("first"), "text_hook": bool(ctx.overlays_tl and min(o["t0"] for o in ctx.overlays_tl) < 1),
        "captions": bool(ctx.caption_style.get("enabled", True)), "broll": len(ctx.brolls), "cuts_per_10s": round(cuts / max(D, 1) * 10, 1),
        "cta": bool(ctas), "cta_seconds": round(sum(u["t1"] - u["t0"] for u in ctas), 1),
    }


def _num(v):
    if v in (None, ""):
        return None
    try:
        return float(str(v).replace(",", "").replace("$", "").replace("%", "").strip())
    except ValueError:
        return None


def clean_metrics(m: dict) -> dict:
    return {k: _num(v) for k, v in (m or {}).items() if k in METRICS and _num(v) is not None}


def _factors(f: dict) -> dict:
    out = {}
    if f.get("hook_type"):
        out["Hook type"] = f["hook_type"]
    d = f.get("duration")
    if d:
        out["Length"] = "under 20s" if d < 20 else "20–30s" if d < 30 else "30–45s" if d < 45 else "over 45s"
    pf = f.get("product_first")
    out["Product timing"] = "product in first 4s" if pf is not None and pf <= 4 else "product after 4s"
    out["Text hook"] = "with a text hook" if f.get("text_hook") else "without a text hook"
    out["Captions"] = "with captions" if f.get("captions") else "without captions"
    out["B-roll"] = "with product B-roll" if f.get("broll") else "without B-roll"
    if f.get("cuts_per_10s") is not None:
        out["Pacing"] = "fast cuts (4+ per 10s)" if f["cuts_per_10s"] >= 4 else "calmer cuts"
    return out


def insights(entries: list[dict]) -> list[dict]:
    usable = [e for e in entries if e.get("features") and e.get("metrics")]
    if len(usable) < 3:
        return []
    found = []
    for metric in PRIORITY:
        vals = [e for e in usable if e["metrics"].get(metric) is not None]
        if len(vals) < 3:
            continue
        overall = sum(e["metrics"][metric] for e in vals) / len(vals)
        groups: dict[tuple, list[float]] = {}
        for e in vals:
            for fac, level in _factors(e["features"]).items():
                groups.setdefault((fac, level), []).append(e["metrics"][metric])
        by_factor: dict[str, list] = {}
        for (fac, level), xs in groups.items():
            if len(xs) >= 2:
                by_factor.setdefault(fac, []).append((level, sum(xs) / len(xs), len(xs)))
        for fac, levels in by_factor.items():
            if len(levels) < 2:
                continue
            levels.sort(key=lambda x: -x[1])
            (hi, hv, hn), (lo, lv, ln) = levels[0], levels[-1]
            if lv <= 0 or hv / lv < 1.15:
                continue
            lift = hv / lv
            label, _, unit = METRICS[metric]
            fmt = (lambda x: f"${x:,.0f}") if unit == "$" else (lambda x: f"{x:,.1f}{unit}" if unit else f"{x:,.0f}")
            found.append({
                "factor": fac, "metric": metric, "best": hi, "worst": lo, "lift": round(lift, 2), "n": [hn, ln],
                "text": f"In your videos, {hi} averaged {fmt(hv)} {label} vs {fmt(lv)} for {lo} ({hn} vs {ln} videos).",
                "confidence": "low" if min(hn, ln) < 3 else "medium" if min(hn, ln) < 6 else "higher",
                "weight": math.log(lift) * math.sqrt(min(hn, ln)) * (1.3 if metric in ("gmv", "orders", "product_clicks", "ctr") else 1),
                "tip": _tip(fac, hi),
            })
    found.sort(key=lambda x: -x["weight"])
    seen, out = set(), []
    for f in found:
        if f["factor"] in seen:
            continue
        seen.add(f["factor"])
        out.append(f)
    return out[:8]


def _tip(factor: str, best: str) -> str:
    return {
        "Hook type": f"Try opening more ads with a {best.lower()} hook.",
        "Length": f"Aim for {best} when you set a target length.",
        "Product timing": "Keep the product on screen early (Show product earlier)." if "first" in best else "Your data favours building up before the reveal.",
        "Text hook": "Keep adding an on-screen text hook." if best.startswith("with") else "Your viewers respond without text hooks — test fewer.",
        "Captions": "Keep captions on." if best.startswith("with") else "Your data favours no captions.",
        "B-roll": "Add product B-roll to more ads." if best.startswith("with") else "Your talking-head-only videos did better — use B-roll lightly.",
        "Pacing": "Use Fast/Viral pacing more often." if best.startswith("fast") else "Clean/Fast pacing is working better than aggressive cuts.",
    }.get(factor, "")


def insights_for_user(user_id: str) -> list[dict]:
    return insights(db.all_("SELECT * FROM performance WHERE user_id=?", user_id))


HEADER_MAP = [
    ("title", r"title|video|name|description"), ("url", r"url|link"), ("posted_at", r"date|posted|publish"),
    ("views", r"^views?$|video views|plays"), ("likes", r"likes?"), ("comments", r"comments?"), ("shares", r"shares?"),
    ("avg_watch_time", r"average watch|avg\.? watch|watch time"), ("completion_rate", r"complet|full video|watched full"),
    ("ctr", r"ctr|click[- ]through"), ("product_clicks", r"product clicks?|clicks?"), ("orders", r"orders?|units sold|sales count"),
    ("gmv", r"gmv|revenue|sales amount|earnings"),
]


def parse_csv(text: str) -> list[dict]:
    """Import results exported from TikTok / TikTok Shop analytics (or any sheet) — columns are matched by name."""
    rdr = csv.DictReader(io.StringIO(text))
    cols = {}
    for h in rdr.fieldnames or []:
        for key, pat in HEADER_MAP:
            if key not in cols.values() and re.search(pat, h.strip().lower()):
                cols[h] = key
                break
    rows = []
    for r in rdr:
        item = {"metrics": {}}
        for h, key in cols.items():
            if key in ("title", "url", "posted_at"):
                item[key] = (r.get(h) or "").strip()[:200]
            else:
                item["metrics"][key] = r.get(h)
        item["metrics"] = clean_metrics(item["metrics"])
        if item["metrics"]:
            rows.append(item)
    return rows
