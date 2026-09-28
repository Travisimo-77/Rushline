"""Caption layout (shared by preview + render so what you see is what you export) and ASS subtitle generation."""
from __future__ import annotations

import re

from ..ai.text import norm

PRESETS: dict[str, dict] = {
    "clean":       {"label": "Clean", "size": 5.0, "weight": 600, "outline": 3, "shadow": 1, "uppercase": False, "words_per_line": 5,
                    "mode": "phrase", "animation": "none", "emphasis": False, "background": False, "color": "#FFFFFF", "highlight": "#FFFFFF"},
    "tiktok":      {"label": "TikTok", "size": 6.2, "weight": 800, "outline": 7, "shadow": 2, "uppercase": False, "words_per_line": 3,
                    "mode": "phrase", "animation": "pop", "emphasis": True, "background": False, "color": "#FFFFFF", "highlight": "#FFD84D"},
    "word":        {"label": "Word-by-word", "size": 8.0, "weight": 900, "outline": 8, "shadow": 2, "uppercase": True, "words_per_line": 1,
                    "mode": "word", "animation": "pop", "emphasis": True, "background": False, "color": "#FFFFFF", "highlight": "#7CF5C4"},
    "karaoke":     {"label": "Karaoke", "size": 6.0, "weight": 800, "outline": 6, "shadow": 1, "uppercase": False, "words_per_line": 4,
                    "mode": "karaoke", "animation": "none", "emphasis": False, "background": False, "color": "#FFFFFF", "highlight": "#FF7A59"},
    "bold":        {"label": "Bold", "size": 7.2, "weight": 900, "outline": 9, "shadow": 3, "uppercase": True, "words_per_line": 3,
                    "mode": "phrase", "animation": "pop", "emphasis": True, "background": False, "color": "#FFFFFF", "highlight": "#FFD84D"},
    "minimal":     {"label": "Minimal", "size": 4.4, "weight": 500, "outline": 0, "shadow": 4, "uppercase": False, "words_per_line": 6,
                    "mode": "phrase", "animation": "fade", "emphasis": False, "background": False, "color": "#FFFFFF", "highlight": "#FFFFFF"},
    "ugc":         {"label": "UGC", "size": 5.2, "weight": 700, "outline": 0, "shadow": 0, "uppercase": False, "words_per_line": 4,
                    "mode": "phrase", "animation": "none", "emphasis": False, "background": True, "bg_color": "#FFFFFFEE",
                    "color": "#111111", "highlight": "#111111"},
    "high_energy": {"label": "High-energy", "size": 8.6, "weight": 900, "outline": 9, "shadow": 3, "uppercase": True, "words_per_line": 2,
                    "mode": "karaoke", "animation": "pop", "emphasis": True, "background": False, "color": "#FFFFFF", "highlight": "#5CFFB0"},
    "punch":       {"label": "Keyword punch", "size": 7.0, "weight": 900, "outline": 8, "shadow": 2, "uppercase": True, "words_per_line": 3,
                    "mode": "phrase", "animation": "pop", "emphasis": True, "emph_scale": 1.25, "background": False,
                    "color": "#FFFFFF", "highlight": "#FFE14D"},
}

EMPHASIS_WORDS = {"sale", "free", "off", "results", "result", "new", "today", "now", "save", "deal", "cheap", "obsessed",
                  "best", "never", "finally", "every", "instantly", "love", "shipping", "discount", "only", "wow", "insane",
                  "before", "after", "link", "cart", "shop", "hack", "secret", "stop"}
EMPH_RE = re.compile(r"^(\$\d|\d+%|\d+(\.\d+)?$|\d+x$)")


def is_emphasis(text: str) -> bool:
    t = norm(text)
    return t in EMPHASIS_WORDS or bool(EMPH_RE.match(text.strip().lstrip("$").rstrip(".,!?")) and any(c.isdigit() for c in text)) \
        or text.strip().startswith("$")


def layout(words: list[dict], style: dict, flagged_keys: set | None = None) -> list[dict]:
    """words: [{key,text,t0,t1}] in timeline order → lines [{t0,t1,words:[{text,t0,t1,emph}]}]."""
    flagged_keys = flagged_keys or set()
    mode = style.get("mode", "phrase")
    per = 1 if mode == "word" else max(1, int(style.get("words_per_line", 3)))
    lines: list[dict] = []
    cur: list[dict] = []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        end_sentence = w["text"].rstrip().endswith((".", "?", "!", ","))
        gap = (nxt["t0"] - w["t1"]) if nxt else 9
        chars = sum(len(x["text"]) + 1 for x in cur)
        if len(cur) >= per or end_sentence or gap > 0.35 or chars > 22 or nxt is None or nxt.get("clip") != w.get("clip") and gap > 0.1:
            lines.append({"t0": cur[0]["t0"], "t1": cur[-1]["t1"], "words": [
                {"text": x["text"].upper() if style.get("uppercase") else x["text"], "t0": x["t0"], "t1": x["t1"], "key": x["key"],
                 "emph": bool(style.get("emphasis")) and x["key"] not in flagged_keys and is_emphasis(x["text"])} for x in cur]})
            cur = []
    for a, b in zip(lines, lines[1:]):
        a["t1"] = round(min(max(a["t1"] + 0.12, a["t1"]), b["t0"]), 3)
    if lines:
        lines[-1]["t1"] = round(lines[-1]["t1"] + 0.25, 3)
    for ln in lines:
        for w in ln["words"]:
            w["text"] = w["text"].rstrip(",") if style.get("preset") != "clean" else w["text"]
    return lines


def _ass_color(hex_: str) -> str:
    h = hex_.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    a = h[6:8] if len(h) >= 8 else "FF"
    alpha = 255 - int(a, 16)
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def _ts(t: float) -> str:
    t = max(0.0, t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _wrap(t: str, n: int) -> str:
    """Balanced line breaks for short on-screen text (ASS hard break \\N)."""
    words, lines, cur = t.split(), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > n:
            lines.append(cur); cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return "\\N".join(lines)


def _esc(t: str) -> str:
    return t.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", " ")


def to_ass(lines: list[dict], style: dict, W: int, H: int, overlays: list[dict] | None = None, watermark: bool = False) -> str:
    size = round(float(style.get("size", 6)) / 100 * H)
    outline = round(float(style.get("outline", 6)) * H / 1920, 1)
    shadow = round(float(style.get("shadow", 2)) * H / 1920, 1)
    bold = -1 if int(style.get("weight", 700)) >= 600 else 0
    box = bool(style.get("background"))
    border_style = 3 if box else 1
    back = _ass_color(style.get("bg_color", "#000000B0")) if box else "&H80000000"
    outline_col = back if box else "&H00000000"
    font = style.get("font", "Poppins")
    y = round(float(style.get("y", 62)) / 100 * H)
    hl = _ass_color(style.get("highlight", "#FFD84D"))[4:]  # BGR part for inline \c
    base = _ass_color(style.get("color", "#FFFFFF"))[4:]
    scale = int(round(float(style.get("emph_scale", 1.12)) * 100))
    out = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "WrapStyle: 0", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, "
        "StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Cap,{font},{size},{_ass_color(style.get('color', '#FFFFFF'))},&H000000FF,{outline_col},{back},{bold},0,0,0,100,100,0,0,"
        f"{border_style},{outline if not box else round(size * 0.18)},{shadow},5,{int(W * 0.08)},{int(W * 0.08)},0,1",
        f"Style: Ovl,{font},{round(size * 0.8)},&H00FFFFFF,&H000000FF,&H00000000,&H90000000,-1,0,0,0,100,100,0,0,3,{round(size * 0.2)},0,5,40,40,0,1",
        # on-screen text hook: black text on a white card (the look viewers recognise from native TikTok text)
        f"Style: Hook,{font},{round(H * 0.036)},&H00111111,&H000000FF,&H00FFFFFF,&H00FFFFFF,-1,0,0,0,100,100,0,0,3,{round(H * 0.012)},0,5,60,60,0,1",
        f"Style: Wm,{font},{round(H * 0.022)},&H60FFFFFF,&H000000FF,&H80000000,&H00000000,-1,0,0,0,100,100,0,0,1,1,0,9,30,30,40,1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    anim = style.get("animation", "none")
    pos = f"\\an5\\pos({W // 2},{y})"
    if style.get("enabled", True):
        for ln in lines:
            intro = ""
            if anim == "pop":
                intro = "\\fscx82\\fscy82\\t(0,90,\\fscx100\\fscy100)"
            elif anim == "fade":
                intro = "\\fad(120,80)"

            def word_txt(w, active=False):
                t = _esc(w["text"])
                if active:
                    return f"{{\\c&H{hl}&}}{t}{{\\c&H{base}&}}"
                if w.get("emph"):
                    return f"{{\\c&H{hl}&\\fscx{scale}\\fscy{scale}}}{t}{{\\c&H{base}&\\fscx100\\fscy100}}"
                return t

            if style.get("mode") == "karaoke":
                for i, w in enumerate(ln["words"]):
                    t0 = ln["t0"] if i == 0 else w["t0"]
                    t1 = ln["words"][i + 1]["t0"] if i + 1 < len(ln["words"]) else ln["t1"]
                    txt = " ".join(word_txt(x, active=(j == i)) for j, x in enumerate(ln["words"]))
                    out.append(f"Dialogue: 0,{_ts(t0)},{_ts(max(t1, t0 + 0.05))},Cap,,0,0,0,,{{{pos}{intro if i == 0 else ''}}}{txt}")
            else:
                txt = " ".join(word_txt(x) for x in ln["words"])
                out.append(f"Dialogue: 0,{_ts(ln['t0'])},{_ts(ln['t1'])},Cap,,0,0,0,,{{{pos}{intro}}}{txt}")
    for o in overlays or []:
        oy = round(float(o.get("y", 20)) / 100 * H)
        st = "Hook" if o.get("style") == "hook" else "Ovl"
        txt = _esc(o["text"])
        if st == "Hook":
            txt = _wrap(txt, 22)
        out.append(f"Dialogue: 1,{_ts(o['t0'])},{_ts(o['t1'])},{st},,0,0,0,,{{\\an5\\pos({W // 2},{oy})\\fad(120,120)}}{txt}")
    if watermark:
        out.append(f"Dialogue: 2,{_ts(0)},{_ts(36000)},Wm,,0,0,0,,Made with Rushline")
    return "\n".join(out) + "\n"
