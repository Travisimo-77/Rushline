"""Natural-language editing assistant: request text → list of actions (grammar first, LLM fallback)."""
from __future__ import annotations

import re

NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
             "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40, "sixty": 60}


def _num(s: str) -> float | None:
    s = s.strip().lower()
    if s in NUM_WORDS:
        return NUM_WORDS[s]
    try:
        return float(s)
    except ValueError:
        return None


NUM = r"(\d+(?:\.\d+)?|one|two|three|four|five|six|seven|eight|nine|ten|fifteen|twenty|thirty|forty|sixty)"


def parse(text: str) -> list[dict]:
    t = " " + text.lower().strip() + " "
    acts: list[dict] = []

    def add(action, **args):
        if not any(a["action"] == action for a in acts):
            acts.append({"action": action, "args": args})

    # --- variations (check first; "make three versions" shouldn't also trigger other things)
    m = re.search(NUM + r"\s+(completely\s+)?(different\s+)?(versions|variations|ads|variants|cuts)", t)
    focus = None
    for f, pat in [("price", r"price|cheap|deal|discount"), ("problem", r"problem|pain"), ("demo", r"demo|demonstrat"),
                   ("story", r"story"), ("benefit", r"benefit")]:
        if re.search(r"(focused on|focus on|about the|around the|centered on)\s+(the\s+)?(product\s+)?(" + pat + ")", t):
            focus = f
    if m:
        add("generate_variations", count=int(_num(m.group(1)) or 3), focus=focus)
    elif re.search(r"\b(version|variation)\b", t) and focus:
        add("generate_variations", count=1, focus=focus)

    # --- duration
    m = re.search(NUM + r"[\s-]*(s|sec|secs|second|seconds)\b", t)
    if m and not re.search(r"(first|within( the first)?)\s+" + re.escape(m.group(0).strip()), t):
        secs = _num(m.group(1))
        if secs and 5 <= secs <= 600:
            if re.search(r"tiktok shop|shop ad|\bad\b", t):
                add("restructure", template="problem_solution")
            add("fit_duration", seconds=secs)
    if re.search(r"tiktok shop|shop optimi[sz]e|turn (this|it) into an? ad", t) and not any(a["action"] == "restructure" for a in acts):
        add("restructure", template="problem_solution")
        add("show_product_earlier", within=3)

    # --- cleanup
    if re.search(r"dead space|silence|pauses?|gaps?|dead air", t):
        add("remove_dead_space")
    if re.search(r"filler|\bums?\b|\buhs?\b|\blikes\b", t):
        add("remove_fillers")
    if re.search(r"retakes?|duplicate takes?|repeated takes?|mistakes|bad takes?", t):
        add("remove_retakes")
    if re.search(r"repetit|repeat(ed|s)?\b|redundan|same thing", t):
        add("remove_repetition")
    if re.search(r"\b(clean (it|this|everything) up|ai edit|auto ?edit|clean edit)\b", t):
        add("ai_edit")

    # --- pacing
    if re.search(r"\b(faster|quicker|tighten|snappier|speed (it|this) up|more energy|punchier)\b", t):
        add("improve_pacing", level="viral" if re.search(r"much|way|really|viral|super", t) else "fast")
    if re.search(r"more natural|less choppy|too choppy|slow (it|this) down|breathe", t):
        add("make_natural")

    # --- structure
    if re.search(r"(strongest|best|better) hook|use (my|the) .*hook|open with", t):
        add("find_best_hook")
    m = re.search(r"(show|move|put|bring) (the )?product .*(earlier|first|start|beginning|within)", t)
    if m:
        w = re.search(r"(first|within)\s+(the\s+first\s+)?" + NUM + r"\s*(s|sec|seconds)", t)
        add("show_product_earlier", within=_num(w.group(3)) if w else 3)
    if re.search(r"restructure|reorder|re-order|rearrange|stronger structure|problem.{0,5}solution", t) and not any(a["action"] == "generate_variations" for a in acts):
        add("restructure", template="problem_solution")
    if re.search(r"(cta|call to action|ending).{0,20}(shorter|tighter|quicker)|shorten (the )?(cta|call to action|ending)", t):
        add("shorten_cta")
    if re.search(r"shorten|make (it|this) shorter|cut (it|this) down", t) and not any(a["action"] in ("fit_duration", "shorten_cta") for a in acts):
        add("fit_duration", seconds=None)

    # --- style
    if re.search(r"(add|turn on|put) captions|subtitles", t) and "remove" not in t:
        add("add_captions")
    if re.search(r"(remove|turn off|no) (the )?(captions|subtitles)", t):
        add("remove_captions")
    if re.search(r"(audio|sound|voice|mic|noise)", t) and re.search(r"enhance|clean|better|fix|improve|reduce|remove", t):
        add("enhance_audio")
    if re.search(r"(color|colour|brightness|exposure|lighting|look)", t) and re.search(r"enhance|fix|better|improve|brighter|pop", t):
        add("enhance_video")

    # --- honest "coming soon"
    if re.search(r"b-?roll|product (shots|footage|clips)|cutaways?", t):
        add("add_broll")
    if re.search(r"text hook|on-?screen text|hook text|title card", t):
        add("add_text_hook")
    m2 = re.search(NUM + r"\s+(tiktok shop )?ads? from (my )?(pieces|parts|clips|takes)|batch", t)
    if m2:
        add("batch_ads", count=int(_num(m2.group(1)) or 10) if m2.group(1) else 10)
        acts[:] = [a for a in acts if a["action"] != "generate_variations"]
    if re.search(r"music|soundtrack|song", t):
        add("coming_soon", feature="Smart music & ducking")
    if re.search(r"split[- ]?screen|side by side", t):
        add("coming_soon", feature="Split-screen comparisons")
    return acts
