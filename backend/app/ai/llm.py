"""Optional LLM provider (Anthropic Messages API). Everything works without it; when configured it is used to
(1) refine sales-section labels and (2) interpret free-form assistant requests the grammar can't parse.
The LLM never edits the timeline directly — it returns the same JSON action vocabulary the grammar produces,
which is then validated and turned into a reviewable plan.
"""
from __future__ import annotations

import json

from .. import config
from .structure import SECTIONS


def available() -> bool:
    return bool(config.ANTHROPIC_API_KEY)


def _call(system: str, user: str, max_tokens: int = 1500) -> str:
    import httpx
    r = httpx.post("https://api.anthropic.com/v1/messages", timeout=60, headers={
        "x-api-key": config.ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": config.ANTHROPIC_MODEL, "max_tokens": max_tokens, "system": system,
              "messages": [{"role": "user", "content": user}]})
    r.raise_for_status()
    return "".join(b.get("text", "") for b in r.json()["content"])


def _json(text: str):
    s = text[text.find("{"): text.rfind("}") + 1] if "{" in text else text[text.find("["): text.rfind("]") + 1]
    return json.loads(s)


def refine_sections(labelled: list[dict], product: dict | None) -> dict[str, str]:
    if not available():
        return {}
    lines = "\n".join(f"{s['id']}\t{s['text']}" for s in labelled if s.get("speech", True))
    system = ("You label lines of a short-form product video transcript with ad sections. Allowed labels: "
              + ", ".join(SECTIONS) + ". Respond with JSON object {id: label}. Do not invent lines.")
    try:
        out = _json(_call(system, f"Product: {json.dumps((product or {}).get('name', ''))}\n\n{lines}"))
        return {k: v for k, v in out.items() if v in SECTIONS}
    except Exception:
        return {}


ACTIONS_DOC = """Allowed actions (JSON list of {"action": name, "args": {...}}):
remove_dead_space, remove_fillers, remove_retakes, remove_repetition, ai_edit, find_best_hook {hook_id?},
restructure {template: problem_solution|price|demo|story}, show_product_earlier {within?: seconds},
fit_duration {seconds}, add_captions {preset?}, remove_captions, improve_pacing {level: fast|viral}, make_natural,
enhance_audio, enhance_video, shorten_cta, generate_variations {count, focus?: price|problem|demo|story|benefit},
coming_soon {feature}"""


def parse_request(text: str, context: str) -> list[dict]:
    if not available():
        return []
    system = ("You convert a video creator's editing request into actions for a timeline editor. "
              "Never invent spoken content. " + ACTIONS_DOC + " Respond with JSON only.")
    try:
        out = _json(_call(system, f"Context:\n{context}\n\nRequest: {text}", 600))
        return out if isinstance(out, list) else out.get("actions", [])
    except Exception:
        return []
