"""AI planners. Every AI action produces a reviewable PLAN (steps → ops). Nothing changes until the creator applies it.

Guarantees enforced here:
- only whole recorded sentences are moved or dropped (never re-worded, never spliced into new statements);
- dependent sentences ("…and that's why it works") move/drop together with the sentence before them;
- hooks come only from recorded lines;
- ranges already removed aren't counted twice, so the plan summary is honest.
"""
from __future__ import annotations

from ..ai import assistant, cleanup, llm
from ..ai.text import CONNECTIVES, fmt_t, norm, tokens
from ..media.analysis import auto_color
from ..media.captions import PRESETS
from .context import Ctx

TEMPLATES = {
    "problem_solution": ["hook", "problem", "pain_point", "product_intro", "solution", "demonstration", "feature", "benefit",
                         "other", "broll", "comparison", "objection", "social_proof", "price", "discount", "urgency", "cta"],
    "price": ["hook", "price", "discount", "product_intro", "demonstration", "benefit", "feature", "other", "broll",
              "problem", "pain_point", "solution", "social_proof", "comparison", "objection", "urgency", "cta"],
    "demo": ["hook", "demonstration", "product_intro", "benefit", "feature", "broll", "other", "solution", "problem", "pain_point",
             "social_proof", "comparison", "objection", "price", "discount", "urgency", "cta"],
    "story": ["hook", "problem", "pain_point", "other", "solution", "product_intro", "demonstration", "benefit", "feature", "broll",
              "social_proof", "objection", "comparison", "price", "discount", "urgency", "cta"],
    "benefit": ["hook", "benefit", "product_intro", "demonstration", "feature", "solution", "problem", "pain_point", "other", "broll",
                "social_proof", "comparison", "objection", "price", "discount", "urgency", "cta"],
}
TEMPLATE_LABEL = {"problem_solution": "Problem/Solution", "price": "Price hook", "demo": "Product demo", "story": "Storytime",
                  "benefit": "Benefit-heavy"}
FOCUS_HOOK_CATS = {"price": {"Price", "Discount"}, "problem_solution": {"Pain point", "Question", "Mistake"},
                   "demo": {"Demonstration", "Before/After"}, "story": {"Story", "Emotional", "Surprise"},
                   "benefit": {"Strong opinion", "Curiosity", "Surprise"}}
PRIORITY = {"hook": 100, "cta": 95, "product_intro": 90, "demonstration": 85, "problem": 75, "solution": 72, "benefit": 70,
            "price": 65, "discount": 62, "pain_point": 55, "feature": 50, "social_proof": 45, "urgency": 40, "objection": 38,
            "comparison": 36, "broll": 30, "other": 20}

COMING_SOON = {"b-roll", "music", "split"}


def _step(label: str, ops: list[dict], detail: str | list | None = None, disable: list[str] | None = None, kind: str = "edit") -> dict:
    return {"label": label, "detail": detail, "ops": ops, "disable": disable or [], "kind": kind}


def _new_seconds(ctx: Ctx, ranges: list[list]) -> float:
    """Seconds of currently-kept source that these ranges would remove."""
    total = 0.0
    for mid, s, e in ranges:
        for c in ctx.tl["clips"]:
            if c["media_id"] == mid:
                a, b = max(s, c["s"]), min(e, c["e"])
                if b > a:
                    total += (b - a) / c["speed"]
    return total


def _fresh(ctx: Ctx, ranges: list[list]) -> list[list]:
    return [r for r in ranges if _new_seconds(ctx, [r]) > 0.02]


def _cleanup_params(ctx: Ctx, strength: str | None = None) -> dict:
    st = strength or ctx.project.get("strength") or "fast"
    return cleanup.params_for(st, (ctx.project.get("settings") or {}).get("sensitivity"))


# ------------------------------------------------------------------------------------------------ cleanup steps
def cleanup_steps(ctx: Ctx, which: set[str], strength: str | None = None) -> list[dict]:
    p = _cleanup_params(ctx, strength)
    res = cleanup.analyze(ctx.ready_media, ctx.words_by_media, ctx.analysis, p)
    g = res["groups"]
    steps = []
    if "dead_space" in which:
        r = _fresh(ctx, g["dead_space"])
        if r:
            secs = _new_seconds(ctx, r)
            steps.append(_step(f"Remove {secs:.1f}s of dead space & pauses", [{"kind": "remove", "label": f"Removed {secs:.1f}s of silence",
                                                                                "params": {"ranges": r, "reason": "dead_space"}}],
                               f"{len(r)} gaps tightened to ~{p['keep_pause'] * 1000:.0f} ms; cuts snapped to word edges"))
    if "fillers" in which:
        r = _fresh(ctx, g["fillers"])
        if r:
            steps.append(_step(f"Remove {len(r)} filler word{'s' * (len(r) != 1)}", [{"kind": "remove", "label": f"Removed {len(r)} filler words",
                                                                                   "params": {"ranges": r, "reason": "fillers"}}],
                               "um / uh" + (" / discourse “like”" if p["like"] else "") + (" / you know, I mean" if p["aggressive"] else "")))
    if "stutters" in which:
        r = _fresh(ctx, g["stutters"])
        if r:
            steps.append(_step(f"Fix {len(r)} stutter{'s' * (len(r) != 1)} / false start{'s' * (len(r) != 1)}",
                               [{"kind": "remove", "label": f"Removed {len(r)} stutters", "params": {"ranges": r, "reason": "stutters"}}]))
    if "mistakes" in which:
        r = _fresh(ctx, g["mistakes"])
        if r:
            steps.append(_step(f"Remove {len(r)} restart/mistake line{'s' * (len(r) != 1)}",
                               [{"kind": "remove", "label": f"Removed {len(r)} mistake lines", "params": {"ranges": r, "reason": "mistakes"}}],
                               "e.g. “wait, let me redo that”"))
    if "retakes" in which:
        by_id = {s["id"]: s for s in res["sentences"]}
        ranges, detail = [], []
        for grp in res["retake_groups"]:
            rr = _fresh(ctx, [[by_id[i]["media_id"], by_id[i]["s"], by_id[i]["e"]] for i in grp["remove"]])
            if rr:
                ranges += rr
                detail.append(f"Kept take {grp['takes'].index(grp['keep']) + 1}/{len(grp['takes'])}: “{by_id[grp['keep']]['text'][:70]}”")
        rr = _fresh(ctx, g.get("restarts", []))
        if rr:
            steps.append(_step(f"Remove {len(rr)} abandoned mid-sentence take{'s' * (len(rr) != 1)}",
                               [{"kind": "remove", "label": f"Removed {len(rr)} restarts", "params": {"ranges": rr, "reason": "retakes"}}],
                               [f"Cut: “{t[:70]}”" for t in res.get("restart_texts", [])[:12]]))
        if ranges:
            steps.append(_step(f"Remove {len(ranges)} duplicate/abandoned take{'s' * (len(ranges) != 1)} (kept the cleanest)",
                               [{"kind": "remove", "label": f"Removed {len(ranges)} retakes", "params": {"ranges": ranges, "reason": "retakes"}}],
                               detail))
    return steps


def _viral_extras(ctx: Ctx, p: dict) -> list[dict]:
    steps = []
    zp = cleanup.zoom_props(ctx.tl["units"], p["zoom_every"])
    if zp:
        steps.append(_step(f"Add {len(zp)} punch-in zoom{'s' * (len(zp) != 1)}",
                           [{"kind": "props", "label": "Punch-in zoom", "params": z} for z in zp], "subtle 112% zoom for visual change"))
    return steps


# ------------------------------------------------------------------------------------------------ structure helpers
def _blocks(ctx: Ctx) -> list[dict]:
    """Kept units grouped so that dependent sentences stay attached to their antecedent."""
    blocks: list[dict] = []
    for u in ctx.unit_rows:
        low = u["text"].lower().strip()
        dependent = bool(blocks) and (low.startswith(CONNECTIVES) or not u["speech"] or len(tokens(u["text"])) <= 2)
        if dependent and blocks and blocks[-1]["section"] != "hook":
            b = blocks[-1]
            b["units"].append(u["unit_id"]); b["t1"] = u["t1"]; b["text"] += " " + u["text"]
            if b["section"] == "other" and u["section"] != "other":
                b["section"] = u["section"]
            b["visible"] = b["visible"] or u["visible"]
        else:
            blocks.append({"units": [u["unit_id"]], "origin": u["origin"], "section": u["section"], "t0": u["t0"], "t1": u["t1"],
                           "text": u["text"], "hook": u.get("hook") or {}, "visible": u["visible"], "media_id": u["media_id"]})
    for n, b in enumerate(blocks):
        b["idx"] = n
        b["dur"] = b["t1"] - b["t0"]
    return blocks


def _seq(blocks) -> str:
    out = []
    for b in blocks:
        lbl = b["section"].replace("_", " ").title().replace("Cta", "CTA")
        if not out or out[-1] != lbl:
            out.append(lbl)
    return " → ".join(out)


def _pick_hook(ctx: Ctx, cats: set | None = None, hook_id: str | None = None):
    hooks = ctx.hooks
    if hook_id:
        return next((h for h in hooks if h["id"] == hook_id), None)
    if cats:
        for h in hooks:
            if set(h["categories"]) & cats:
                return h
    return hooks[0] if hooks else None


def restructure_step(ctx: Ctx, template: str = "problem_solution", hook_id: str | None = None) -> dict | None:
    blocks = _blocks(ctx)
    if len(blocks) < 2:
        return None
    order = TEMPLATES.get(template, TEMPLATES["problem_solution"])
    rank = {s: i for i, s in enumerate(order)}
    hook_block = None
    first_score = (blocks[0].get("hook") or {}).get("score", 0)
    if not hook_id and (blocks[0]["section"] == "hook" or first_score >= 45):
        hook_block = blocks[0]  # respect the opening the creator (or a previous step) chose
    else:
        hook = _pick_hook(ctx, FOCUS_HOOK_CATS.get(template), hook_id)
        if hook:
            hook_block = next((b for b in blocks if hook["id"] == b["origin"]), None)
    if hook_block is None:
        hook_block = next((b for b in blocks if b["section"] == "hook"), None)

    def key(b):
        if b is hook_block:
            return (-1, 0)
        sec = b["section"] if b["section"] != "hook" else "other"
        return (rank.get(sec, rank["other"]), b["idx"])

    new = sorted(blocks, key=key)
    if [b["idx"] for b in new] == [b["idx"] for b in blocks]:
        return None
    unit_ids = [u for b in new for u in b["units"]]
    moved = sum(1 for a, b in zip(blocks, new) if a is not b)
    return _step(f"Restructure as {TEMPLATE_LABEL.get(template, template)} ({moved} section{'s' * (moved != 1)} moved)",
                 [{"kind": "order", "label": f"Restructured: {TEMPLATE_LABEL.get(template, template)}", "params": {"unit_ids": unit_ids}}],
                 [f"Before: {_seq(blocks)}", f"After:  {_seq(new)}",
                  "Whole sentences only — wording and meaning unchanged."], kind="structure")


def best_hook_step(ctx: Ctx, hook_id: str | None = None) -> dict | None:
    h = _pick_hook(ctx, None, hook_id)
    if not h:
        return None
    unit = next((u for u in ctx.tl["units"] if u["origin"] == h["id"]), None)
    if unit is None:
        return None
    ops = []
    sent = ctx.label_by_id.get(h["id"])
    if not h.get("kept") and sent:
        ops.append({"kind": "restore", "label": "Restored hook line", "params": {"ranges": [[sent["media_id"], sent["s"], sent["e"]]]}})
    if h.get("in_use") and not ops:
        return None
    ops.append({"kind": "move", "label": f"Moved hook to opening: “{h['text'][:40]}”", "params": {"unit_id": unit["id"], "after": None}})
    return _step(f"Open with hook: “{h['text'][:80]}”", ops, f"Hook score {h['score']}/100 · {', '.join(h['categories'])}", kind="structure")


def alternate_hooks_step(ctx: Ctx, keep_id: str) -> dict | None:
    """Other recorded hook attempts left in the body would repeat the opening; offer to remove them (visible, reversible)."""
    rows = ctx.unit_rows
    ranges, texts = [], []
    for u in rows[1:]:
        if u["origin"] == keep_id:
            continue
        lab = ctx.label_by_id.get(u["origin"], {})
        if lab.get("section") == "hook" and (lab.get("hook") or {}).get("score", 0) >= 45:
            ranges.append([lab["media_id"], lab["s"], lab["e"]]); texts.append(f"“{lab['text'][:60]}”")
    if not ranges:
        return None
    return _step(f"Remove {len(ranges)} alternate hook take{'s' * (len(ranges) != 1)}",
                 [{"kind": "remove", "label": f"Removed {len(ranges)} alternate hooks", "params": {"ranges": ranges, "reason": "alt_hooks"}}], texts)


def show_product_step(ctx: Ctx, within: float = 3.0) -> dict | None:
    vis = ctx.visibility
    if vis["first"] is not None and vis["first"] <= within:
        return None
    blocks = _blocks(ctx)
    if len(blocks) < 2:
        return None
    cand = next((b for b in blocks[1:] if b["visible"]), None) or \
        next((b for b in blocks[1:] if b["section"] in ("demonstration", "product_intro")), None)
    if not cand:
        return None
    anchor = blocks[0]["units"][-1]
    ops = [{"kind": "move", "label": "Moved product shot earlier", "params": {"unit_id": uid, "after": prev}}
           for uid, prev in zip(cand["units"], [anchor] + cand["units"][:-1])]
    why = "product visible in this shot" if cand["visible"] else f"{cand['section'].replace('_', ' ')} line (add product photos for visual tracking)"
    return _step(f"Show product right after the hook (was {fmt_t(cand['t0'])})", ops, f"“{cand['text'][:70]}” — {why}", kind="structure")


def fit_duration_step(ctx: Ctx, target: float | None) -> dict | None:
    D = ctx.tl["duration"]
    target = target or ctx.project.get("target_duration") or round(D * 0.8)
    if D <= target + 0.5:
        return None
    blocks = _blocks(ctx)
    protected = set()
    if blocks:
        protected.add(blocks[0]["idx"])
    for sec in ("cta", "product_intro"):
        b = next((b for b in blocks if b["section"] == sec), None)
        if b:
            protected.add(b["idx"])
    seen_sec: dict[str, int] = {}
    scored = []
    for b in blocks:
        n = seen_sec.get(b["section"], 0)
        seen_sec[b["section"]] = n + 1
        pr = PRIORITY.get(b["section"], 20) - 18 * n  # 2nd benefit/feature is worth less than the 1st
        if b["section"] == "hook" and b["idx"] != blocks[0]["idx"]:
            pr = 12  # alternate hook in the body
        if b["visible"]:
            pr += 8
        scored.append((pr, -b["dur"], b))
    drop, total = [], D
    for pr, _, b in sorted(scored, key=lambda x: (x[0], x[1])):
        if total <= target + 0.5:
            break
        if b["idx"] in protected:
            continue
        drop.append(b)
        total -= b["dur"]
    if not drop:
        return None
    ranges = []
    for b in drop:
        for uid in b["units"]:
            u = next(x for x in ctx.tl["units"] if x["id"] == uid)
            ranges.append([u["media_id"], u["s"], u["e"]])
    detail = [f"Drop {b['section'].replace('_', ' ')} ({b['dur']:.1f}s): “{b['text'][:60]}”" for b in sorted(drop, key=lambda b: b["idx"])]
    if total > target + 0.5:
        detail.append(f"Can't reach {target:.0f}s without cutting the hook, product or CTA — result ≈ {total:.0f}s.")
    return _step(f"Fit to {target:.0f}s (drop {len(drop)} lower-priority line{'s' * (len(drop) != 1)})",
                 [{"kind": "remove", "label": f"Trimmed to ~{total:.0f}s", "params": {"ranges": ranges, "reason": "duration"}}], detail,
                 kind="structure")


def shorten_cta_step(ctx: Ctx) -> dict | None:
    ctas = [b for b in _blocks(ctx) if b["section"] == "cta"]
    if not ctas:
        return None
    ops, detail = [], []
    if len(ctas) > 1:
        keep = min(ctas, key=lambda b: b["dur"]) if ctx.project.get("mode") != "clean" else ctas[-1]
        for b in ctas:
            if b is keep:
                continue
            for uid in b["units"]:
                u = next(x for x in ctx.tl["units"] if x["id"] == uid)
                ops.append({"kind": "remove", "label": "Removed extra CTA", "params": {"ranges": [[u["media_id"], u["s"], u["e"]]], "reason": "cta"}})
            detail.append(f"Drop: “{b['text'][:60]}”")
        detail.append(f"Keep: “{keep['text'][:60]}”")
    p = cleanup.params_for("viral")
    for b in ctas:
        for uid in b["units"]:
            u = next(x for x in ctx.tl["units"] if x["id"] == uid)
            words = [w for w in ctx.words_by_media[u["media_id"]] if u["s"] <= w["s"] < u["e"]]
            m = ctx.media_map[u["media_id"]]
            rr = _fresh(ctx, [r for r in cleanup.dead_space(m, words, {}, p) if u["s"] <= r[1] and r[2] <= u["e"]]
                        + cleanup.fillers(m, words, p)[0])
            if rr:
                ops.append({"kind": "remove", "label": "Tightened CTA", "params": {"ranges": rr, "reason": "cta"}})
    if not ops:
        return None
    return _step("Shorten CTA", ops, detail or ["Tightened pauses and fillers inside the CTA"])


def remove_repetition_step(ctx: Ctx) -> dict | None:
    from ..ai.cleanup import retakes as find_retakes
    kept = [s for s in ctx.labelled if any(u["origin"] == s["id"] for u in ctx.unit_rows)]
    groups = find_retakes(kept, ctx.words_by_media, 0.85)
    ranges, detail = [], []
    by = {s["id"]: s for s in kept}
    for g in groups:
        for sid in g["remove"]:
            s = by[sid]
            ranges.append([s["media_id"], s["s"], s["e"]])
            detail.append(f"Repeats: “{s['text'][:60]}”")
    ranges = _fresh(ctx, ranges)
    if not ranges:
        return None
    return _step(f"Remove {len(ranges)} repetitive line{'s' * (len(ranges) != 1)}",
                 [{"kind": "remove", "label": f"Removed {len(ranges)} repeated lines", "params": {"ranges": ranges, "reason": "repetition"}}], detail)


def natural_step(ctx: Ctx) -> dict | None:
    tight = [o for o in ctx.ops if o["enabled"] and o["kind"] == "remove" and (o["params"].get("reason") in ("dead_space",))]
    zooms = [o for o in ctx.ops if o["enabled"] and o["kind"] == "props" and "zoom" in o["params"].get("props", {}) and o["source"] != "user"]
    if not tight and not zooms:
        return None
    new = ctx.with_ops([], disabled={o["id"] for o in tight})
    steps = cleanup_steps(new, {"dead_space"}, "clean")
    ops = steps[0]["ops"] if steps else []
    return _step("Relax pacing (natural pauses)", ops, ["Replace tight pause removal with natural ~350 ms pauses"]
                 + (["Remove automatic zooms"] if zooms else []), disable=[o["id"] for o in tight + zooms])


def captions_step(ctx: Ctx, preset: str | None = None, on: bool = True) -> dict:
    preset = preset or (ctx.settings.get("captions", {}).get("preset") or "tiktok")
    if not on:
        return _step("Turn captions off", [{"kind": "settings", "label": "Captions off", "params": {"patch": {"captions": {"enabled": False}}}}])
    return _step(f"Captions: {PRESETS.get(preset, {}).get('label', preset)}",
                 [{"kind": "settings", "label": f"Captions ({PRESETS.get(preset, {}).get('label', preset)})",
                   "params": {"patch": {"captions": {"enabled": True, "preset": preset}}}}], "auto emphasis on key words (not on flagged claims)")


# ------------------------------------------------------------------------------------------------ plan entry point
def build(ctx: Ctx, action: str, args: dict | None = None) -> dict:
    args = args or {}
    D0 = ctx.tl["duration"]
    notes: list[str] = []
    steps: list[dict] = []
    variations = None
    cur = ctx

    def push(step_or_steps):
        nonlocal cur
        items = step_or_steps if isinstance(step_or_steps, list) else [step_or_steps]
        for st in items:
            if st:
                steps.append(st)
        if any(items):
            dis = {d for s in steps for d in s["disable"]}
            cur = ctx.with_ops([o for s in steps for o in s["ops"]], disabled=dis)

    title = action.replace("_", " ").title()
    if action == "ai_edit":
        title = "AI Edit"
        strength = args.get("strength") or ctx.project.get("strength") or "fast"
        push(cleanup_steps(cur, {"dead_space", "fillers", "stutters", "mistakes", "retakes"}, strength))
        p = cleanup.params_for(strength)
        if strength == "viral":
            push(_viral_extras(cur, p))
        # clean voice audio is part of every AI Edit (it can be unticked in the plan)
        if not (cur.settings.get("audio") or {}).get("enhance") and any(m.get("has_audio") for m in cur.ready_media):
            push(_enhance_audio_step())
    elif action == "remove_dead_space":
        push(cleanup_steps(cur, {"dead_space"}))
    elif action == "remove_fillers":
        push(cleanup_steps(cur, {"fillers", "stutters"}))
    elif action == "remove_retakes":
        push(cleanup_steps(cur, {"retakes", "mistakes"}))
    elif action == "remove_repetition":
        push(cleanup_steps(cur, {"retakes", "mistakes"}))
        push(remove_repetition_step(cur))
    elif action == "improve_pacing":
        lvl = args.get("level", "fast")
        push(cleanup_steps(cur, {"dead_space", "fillers", "stutters"}, lvl))
        if lvl == "viral":
            push(_viral_extras(cur, cleanup.params_for("viral")))
    elif action == "make_natural":
        push(natural_step(cur))
    elif action == "find_best_hook":
        st = best_hook_step(cur, args.get("hook_id"))
        push(st)
        if st and args.get("remove_alternates", True):
            h = _pick_hook(cur, None, args.get("hook_id"))
            if h:
                push(alternate_hooks_step(cur, h["id"]))
    elif action == "restructure":
        push(restructure_step(cur, args.get("template", "problem_solution"), args.get("hook_id")))
    elif action == "show_product_earlier":
        st = show_product_step(cur, float(args.get("within") or 3))
        push(st)
        if not st:
            notes.append("Product already appears early, or no product shot / product line was found."
                         if cur.visibility["tracked"] else "Add product photos to the product profile (or tag product shots) to enable visual tracking.")
    elif action == "fit_duration":
        push(fit_duration_step(cur, args.get("seconds")))
    elif action == "shorten_video":
        push(fit_duration_step(cur, args.get("seconds") or round(D0 * 0.75)))
    elif action == "shorten_cta":
        push(shorten_cta_step(cur))
    elif action == "add_captions":
        push(captions_step(cur, args.get("preset")))
    elif action == "remove_captions":
        push(captions_step(cur, on=False))
    elif action == "enhance_audio":
        push(_enhance_audio_step())
    elif action == "enhance_video":
        col = auto_color([cur.analysis.get(m["id"], {}) for m in cur.ready_media])
        push(_step("Enhance video", [{"kind": "settings", "label": "Auto color", "params": {"patch": {"color": col}}}],
                   [f"Brightness {col['brightness']:+.2f}", f"Contrast ×{col['contrast']}", f"Saturation ×{col['saturation']}",
                    "Light sharpening — bounded to avoid an over-processed look"]))
    elif action in ("tiktok_shop_optimize", "tiktok_shop"):
        title = "TikTok Shop optimize"
        if not any(o["source"] == "ai" and o["kind"] == "remove" for o in cur.ops):
            push(cleanup_steps(cur, {"dead_space", "fillers", "stutters", "mistakes", "retakes"}))
        push(best_hook_step(cur))
        push(restructure_step(cur, "problem_solution"))
        push(show_product_step(cur, 3))
        if cur.project.get("target_duration"):
            push(fit_duration_step(cur, cur.project["target_duration"]))
        if not ctx.product:
            notes.append("Link a product profile so Rushline can match features, benefits and price lines more accurately.")
    elif action == "generate_variations":
        variations = variation_specs(ctx, int(args.get("count") or 3), args.get("focus"))
        title = f"Generate {len(variations)} ad variation{'s' * (len(variations) != 1)}"
        if not variations:
            notes.append("Not enough distinct material (hooks/sections) to build different versions yet.")
    elif action == "add_text_hook":
        push(text_hook_step(cur, args.get("text"), float(args.get("dur") or 2.5), float(args.get("y") or 16)))
        if not steps:
            notes.append("No hook text available yet — type your own.")
    elif action == "remove_text_hook":
        push(_step("Remove text hook", [{"kind": "remove_overlay", "label": "Removed text hook", "params": {"id": "hook"}}]))
    elif action == "add_broll":
        st = broll_step(cur, args.get("at"), args.get("max"))
        push(st)
        if not st:
            notes.append("Add labelled product B-roll clips (or product photos) in Products → B-roll library first."
                         if not cur.broll_library else "No good spots found — the product is already on screen where it matters.")
    elif action == "punch_in":
        push(punch_in_step(cur, float(args.get("t") or 0)))
    elif action == "tighten":
        push(tighten_step(cur, float(args.get("t0") or 0), float(args.get("t1") or 0)))
    elif action == "remove_line":
        push(remove_line_step(cur, args.get("unit_id")))
    elif action == "batch_ads":
        variations = batch_specs(ctx, int(args.get("count") or 10))
        title = f"Build {len(variations)} ads from your pieces"
        if not variations:
            notes.append("Record a few different hooks and CTAs (e.g. 3 hooks + 2 CTAs) to build ads from pieces.")
    elif action == "coming_soon":
        notes.append(f"{args.get('feature', 'That feature')} is COMING SOON (Phase 2). Nothing was changed.")
    elif action == "assistant":
        return assistant_plan(ctx, args.get("text", ""))
    else:
        notes.append(f"Unknown action: {action}")

    D1 = cur.tl["duration"] if steps else D0
    if not steps and not variations and not notes:
        notes.append("Nothing to change — this already looks good for that request.")
    return {"title": title, "action": action, "args": args, "steps": steps, "notes": notes, "variations": variations,
            "summary": {"before": round(D0, 2), "after": round(D1, 2), "removed": round(max(D0 - D1, 0), 2)},
            "major": any(s["kind"] == "structure" for s in steps) or (D0 - D1) > max(3, D0 * 0.2)}


def _enhance_audio_step() -> dict:
    return _step("Enhance voice audio", [{"kind": "settings", "label": "Audio enhanced",
                                          "params": {"patch": {"audio": {"enhance": True, "normalize": True}}}}],
                 ["Noise reduction", "Voice EQ (high-pass / de-hiss)", "Gentle compression", "Loudness normalize to −14 LUFS",
                  "Clipping protection (true-peak limiter)"])


EXEC_ORDER = ["ai_edit", "remove_dead_space", "remove_fillers", "remove_retakes", "remove_repetition", "improve_pacing", "make_natural",
              "find_best_hook", "restructure", "show_product_earlier", "shorten_cta", "fit_duration", "shorten_video", "add_captions",
              "remove_captions", "enhance_audio", "enhance_video", "add_broll", "add_text_hook", "generate_variations", "batch_ads",
              "coming_soon"]


def assistant_plan(ctx: Ctx, text: str) -> dict:
    acts = assistant.parse(text)
    source = "grammar"
    if not acts and llm.available():
        context = "\n".join(f"[{u['section']}] {u['text']}" for u in ctx.unit_rows[:60])
        acts = llm.parse_request(text, context)
        source = "llm"
    acts = sorted([a for a in acts if a.get("action") in EXEC_ORDER], key=lambda a: EXEC_ORDER.index(a["action"]))
    if not acts:
        return {"title": "Assistant", "action": "assistant", "args": {"text": text}, "steps": [], "variations": None,
                "notes": ["I couldn't map that to an edit yet. Try: “remove the dead space”, “make this a 25-second TikTok Shop ad”, "
                          "“use my strongest hook”, “move the product earlier”, “make 3 versions”, “add captions”."],
                "summary": {"before": ctx.tl["duration"], "after": ctx.tl["duration"], "removed": 0}, "major": False}
    steps, notes, variations = [], [], None
    cur = ctx
    for a in acts:
        sub = build(cur, a["action"], a.get("args") or {})
        steps += sub["steps"]
        notes += sub["notes"]
        if sub.get("variations"):
            variations = sub["variations"]
        if sub["steps"]:
            cur = ctx.with_ops([o for s in steps for o in s["ops"]], disabled={d for s in steps for d in s["disable"]})
    if steps or variations:
        notes = [n for n in notes if not n.startswith("Nothing to change")]
    D0, D1 = ctx.tl["duration"], cur.tl["duration"]
    return {"title": "AI plan", "action": "assistant", "args": {"text": text}, "steps": steps, "notes": notes, "variations": variations,
            "interpreted": [a["action"] for a in acts], "source": source,
            "summary": {"before": round(D0, 2), "after": round(D1, 2), "removed": round(max(D0 - D1, 0), 2)},
            "major": True}


def variation_specs(ctx: Ctx, count: int, focus: str | None = None) -> list[dict]:
    count = max(1, min(count, ctx.plan.get("variations", 5)))
    secs = {u["section"] for u in ctx.unit_rows} | {s["section"] for s in ctx.labelled}
    templates = ["problem_solution", "price", "demo", "story", "benefit"]
    usable = [t for t in templates if (t != "price" or secs & {"price", "discount"}) and (t != "demo" or "demonstration" in secs or ctx.visibility["segments"])
              and (t != "story" or len(ctx.unit_rows) >= 5)]
    if focus:
        f = {"problem": "problem_solution"}.get(focus, focus)
        usable = [f] if f in TEMPLATES else usable
    hooks = ctx.hooks or [None]
    specs, used = [], set()
    i = 0
    while len(specs) < count and i < count * 6:
        t = usable[i % len(usable)] if usable else "problem_solution"
        pref = FOCUS_HOOK_CATS.get(t, set())
        h = next((h for h in hooks if h and set(h["categories"]) & pref and (t, h["id"]) not in used), None) \
            or next((h for h in hooks if h and (t, h["id"]) not in used and h["id"] not in {x[1] for x in used}), None) or hooks[i % len(hooks)]
        key = (t, h["id"] if h else None)
        if key not in used:
            used.add(key)
            specs.append({"template": t, "hook_id": h["id"] if h else None, "hook_text": h["text"] if h else None,
                          "hook_categories": h["categories"] if h else [], "label": TEMPLATE_LABEL[t],
                          "target": ctx.project.get("target_duration")})
        i += 1
    return specs


# ------------------------------------------------------------------------------------------------ growth features
def text_hook_step(ctx: Ctx, text: str | None, dur: float = 2.5, y: float = 16) -> dict | None:
    text = (text or (ctx.text_hook_ideas[0]["text"] if ctx.text_hook_ideas else "")).strip()[:80]
    clips = ctx.tl["clips"]
    if not text or not clips:
        return None
    c = clips[0]
    return _step(f"Add text hook: “{text}”", [{"kind": "text_overlay", "label": f"Text hook: {text[:40]}",
                                                "params": {"id": "hook", "media_id": c["media_id"], "t": c["s"], "dur": dur, "text": text,
                                                           "y": y, "style": "hook"}}],
                 f"Shows for the first {dur:.1f}s · white card, top third (clear of TikTok UI)")


def broll_step(ctx: Ctx, at: float | None = None, max_items: int | None = None) -> dict | None:
    from .features import broll_suggestions
    sug = broll_suggestions(ctx, max_items=max_items or (1 if at is not None else None), at=at)
    if not sug:
        return None
    ops = [{"kind": "broll", "label": f"B-roll: {s['label'][:30]}", "params": {k: s[k] for k in ("id", "media_id", "t", "dur", "source_id", "src_in")}}
           for s in sug]
    return _step(f"Add {len(sug)} product B-roll shot{'s' * (len(sug) != 1)}", ops,
                 [f"{s['t0']:.1f}s · {s['label']} over “{s['text']}”" for s in sug])


def punch_in_step(ctx: Ctx, t: float) -> dict | None:
    c = next((c for c in ctx.tl["clips"] if c["t0"] <= t < c["t1"]), None)
    if not c:
        return None
    z = 1.0 if (c["props"].get("zoom") or 1) > 1.05 else 1.12
    return _step(f"Punch-in zoom at {t:.1f}s", [{"kind": "props", "label": "Punch-in zoom", "params": {"unit_id": c["unit_id"], "props": {"zoom": z}}}],
                 "Visual change to reset attention")


def tighten_step(ctx: Ctx, t0: float, t1: float) -> dict | None:
    from ..timeline import map_range  # noqa: F401
    p = cleanup.params_for("viral")
    rng = []
    for c in ctx.tl["clips"]:
        if c["t1"] <= t0 or c["t0"] >= t1:
            continue
        a = c["s"] + max(0.0, t0 - c["t0"]) * c["speed"]
        b = c["s"] + (min(t1, c["t1"]) - c["t0"]) * c["speed"]
        m = ctx.media_map[c["media_id"]]
        an = ctx.analysis.get(m["id"], {})
        words = [w for w in ctx.words_by_media[m["id"]] if a <= w["s"] < b]
        if an.get("gaps"):
            got = cleanup.dead_space_audio(m, ctx.words_by_media[m["id"]], an.get("soft_gaps") or an["gaps"], p)
        else:
            got = cleanup.dead_space(m, words, an, p)
        rng += [r for r in got if a <= r[1] and r[2] <= b]
        rng += cleanup.fillers(m, words, p)[0]
    rng = _fresh(ctx, rng)
    if not rng:
        return None
    secs = _new_seconds(ctx, rng)
    return _step(f"Tighten {t0:.0f}–{t1:.0f}s (−{secs:.1f}s)", [{"kind": "remove", "label": "Tightened pacing",
                                                               "params": {"ranges": rng, "reason": "dead_space"}}])


def remove_line_step(ctx: Ctx, unit_id: str | None) -> dict | None:
    u = next((u for u in ctx.tl["units"] if u["id"] == unit_id), None)
    if not u:
        return None
    return _step("Cut this line", [{"kind": "remove", "label": "Removed flagged line", "params": {"ranges": [[u["media_id"], u["s"], u["e"]]],
                                                                                              "reason": "compliance"}}])


def cta_step(ctx: Ctx, cta_id: str) -> list[dict]:
    """Use one recorded CTA as the ending: restore it if cut, move it last, drop the other CTA takes."""
    steps = []
    sent = ctx.label_by_id.get(cta_id)
    unit = next((u for u in ctx.tl["units"] if u["origin"] == cta_id), None)
    if not sent or not unit:
        return steps
    ops = []
    if not any(u["origin"] == cta_id for u in ctx.unit_rows):
        ops.append({"kind": "restore", "label": "Restored CTA", "params": {"ranges": [[sent["media_id"], sent["s"], sent["e"]]]}})
    last = ctx.unit_rows[-1]["unit_id"] if ctx.unit_rows else None
    if last and last != unit["id"]:
        ops.append({"kind": "move", "label": "Moved CTA to the end", "params": {"unit_id": unit["id"], "after": last}})
    others = [u for u in ctx.unit_rows if u["section"] == "cta" and u["origin"] != cta_id]
    for u in others:
        ops.append({"kind": "remove", "label": "Removed other CTA take", "params": {"ranges": [[u["media_id"], u["s"], u["e"]]], "reason": "alt_cta"}})
    if ops:
        steps.append(_step(f"End with CTA: “{sent['text'][:60]}”", ops))
    return steps


def batch_specs(ctx: Ctx, count: int) -> list[dict]:
    """Every distinct hook × CTA × structure combination, spread so neighbouring ads differ on as many axes as possible."""
    count = max(1, min(count, ctx.plan.get("variations", 5) * 2, 50))
    pieces = ctx.pieces
    hooks = pieces["hooks"] or [None]
    ctas = pieces["ctas"] or [None]
    templates = [t for t in ("problem_solution", "price", "demo", "benefit", "story") if t != "price" or
                 ({u["section"] for u in ctx.unit_rows} & {"price", "discount"})]
    combos = []
    for i in range(len(hooks) * len(ctas) * len(templates)):
        h = hooks[i % len(hooks)]
        c = ctas[(i // len(hooks)) % len(ctas)]
        t = templates[(i + i // (len(hooks) * len(ctas))) % len(templates)]
        key = (h and h["id"], c and c["id"], t)
        if key not in [x[0] for x in combos]:
            combos.append((key, h, c, t))
    specs = []
    for key, h, c, t in combos[:count]:
        specs.append({"template": t, "hook_id": h and h["id"], "hook_text": h and h["text"], "hook_categories": (h or {}).get("categories", []),
                      "cta_id": c and c["id"], "cta_text": c and c["text"], "label": TEMPLATE_LABEL[t], "target": ctx.project.get("target_duration")})
    return specs
