"""LLM narration layer — optional, additive, and structurally incapable of
displaying a wrong number.

The safety property is enforced by construction, not by prompting:

1. The LLM never receives numeric evidence. ``evidence`` is assembled from the
   analytics layer by :mod:`app.narrative` and is passed through untouched.
2. The LLM is asked to rewrite **prose only** — the situation sentence and the
   uncertainty sentence.
3. Whatever it returns is validated. If the output contains a digit, a currency
   marker, or a percent sign, it is discarded and the template is used.

So even a fully hallucinating model cannot move a ৳ figure. It can only make the
sentence describing that figure read better.

The narrative's ``source`` field reports which of those happened, and how much of
what the reader is looking at the model actually wrote: ``template``, ``llm``,
``llm-partial`` (some fields survived validation, some did not), and the
``-cached`` variants of the last two. See ``_source_name`` for why the partial
case is not simply folded into ``llm``.

Everything here is best-effort: if the token is unset, the network is down, the
call is slow, or the model misbehaves, the deterministic template narrative —
which is complete on its own — is returned unchanged.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

import httpx

from app.config import SETTINGS
from app.narrative import Narrative, lint

CACHE_DIR = SETTINGS["root"] / "data" / "narrations"

_NUMERAL_RE = re.compile(r"[0-9০-৯]|[৳$%]|\bTk\b|\btaka\b", re.IGNORECASE)

# Fields the model is permitted to touch. Evidence lists and every numeric
# string are absent by design — that absence is the guardrail.
REWRITABLE = ("situation", "uncertainty")

SYSTEM_PROMPT = (
    "You rewrite operational alert sentences for a mobile-money agent network "
    "dashboard in Bangladesh. You are given two sentences and must return the "
    "same two sentences, clearer and more natural, in the requested language.\n"
    "Hard rules:\n"
    "- Never invent, restate, or estimate any number, amount, balance, time, or "
    "percentage. If a sentence contains none, do not add one.\n"
    "- Never use the words: fraud, fraudulent, cheating, criminal, প্রতারণা, অপরাধ.\n"
    "- Never accuse anyone of wrongdoing and never recommend blocking, freezing, "
    "or reversing a transaction.\n"
    "- Never suggest transferring value between providers.\n"
    "- Keep each sentence under 30 words.\n"
    'Reply with JSON only: {"situation": "...", "uncertainty": "..."}'
)


def _cache_key(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def _cache_path(key: str) -> Path:
    return CACHE_DIR / f"{key}.json"


def _read_cache(key: str) -> dict | None:
    path = _cache_path(key)
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return None


def _write_cache(key: str, value: dict) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _cache_path(key).write_text(
            json.dumps(value, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass        # a cache miss is never worth failing a request over


def llm_available() -> bool:
    return bool(os.environ.get("ANTHROPIC_AUTH_TOKEN", "").strip())


def _safe(text: str, lang: str) -> bool:
    """Reject anything carrying a number, a currency marker, or banned words."""
    if not text or not text.strip():
        return False
    if _NUMERAL_RE.search(text):
        return False
    if lint(text):
        return False
    if lang == "bn" and not any("ঀ" <= ch <= "৿" for ch in text):
        return False        # asked for Bengali, got something else
    return True


def _source_name(accepted: dict, cached: bool) -> str:
    """Name how much of this narrative the model actually wrote.

    ``llm`` is only honest when the model supplied *every* field it was asked
    for. Fields are validated independently, so a response can be half
    accepted — and a reader shown "LLM-rephrased" over a block that is half
    template prose is being told something untrue about the text in front of
    them. That is the same class of overstatement the source row exists to
    prevent, so the mixed case gets its own name rather than being rounded up.

    The value is also read by ``static/app.js``, which renders it beside every
    alert; unknown values there fall back to the template label, which is the
    safe direction to be wrong in.
    """
    stem = "llm-cached" if cached else "llm"
    complete = len(accepted) >= len(REWRITABLE)
    return stem if complete else f"{stem}-partial"


def rephrase(narrative: Narrative, lang: str = "bn") -> Narrative:
    """Return a narrative with its prose improved, or the original untouched."""
    if not llm_available():
        return narrative

    key = _cache_key(f"{lang}|{narrative.situation}|{narrative.uncertainty}")
    cached = _read_cache(key)
    if cached:
        return _merge(narrative, cached, source=_source_name(cached, cached=True))

    body = {
        "model": SETTINGS["llm_model"],
        "max_tokens": SETTINGS["llm_max_tokens"],
        "system": SYSTEM_PROMPT,
        "messages": [{
            "role": "user",
            "content": (
                f"Language: {'Bengali (bn)' if lang == 'bn' else 'English'}.\n"
                f"Situation: {narrative.situation}\n"
                f"Uncertainty: {narrative.uncertainty}"
            ),
        }],
    }
    headers = {
        "Authorization": f"Bearer {os.environ['ANTHROPIC_AUTH_TOKEN']}",
        "Content-Type": "application/json",
        "anthropic-version": "2023-06-01",
        "User-Agent": "claude-cli/1.0.0 (external, cli)",
    }

    try:
        with httpx.Client(timeout=SETTINGS["llm_timeout_s"]) as client:
            resp = client.post(f"{SETTINGS['llm_base_url']}/v1/messages",
                               json=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, ValueError):
        return narrative    # template narrative is already complete

    text = "".join(block.get("text", "") for block in data.get("content", [])
                   if block.get("type") == "text").strip()
    if not text:
        return narrative

    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        parsed = json.loads(text)
    except ValueError:
        return narrative

    if not isinstance(parsed, dict):
        return narrative

    accepted = {}
    for field in REWRITABLE:
        candidate = parsed.get(field)
        if isinstance(candidate, str) and _safe(candidate, lang):
            accepted[field] = candidate.strip()

    if not accepted:
        return narrative

    _write_cache(key, accepted)
    return _merge(narrative, accepted,
                  source=_source_name(accepted, cached=False))


def _merge(narrative: Narrative, accepted: dict, source: str) -> Narrative:
    """Copy the narrative, replacing only the allowed prose fields.

    ``evidence`` and ``next_steps`` are carried across by reference on purpose:
    the model was never given them and must never be able to change them.
    """
    return Narrative(
        situation=accepted.get("situation", narrative.situation),
        evidence=list(narrative.evidence),
        uncertainty=accepted.get("uncertainty", narrative.uncertainty),
        next_steps=list(narrative.next_steps),
        rejected_text=narrative.rejected_text,
        source=source,
    )


def prewarm(narratives: list[tuple[Narrative, str]]) -> int:
    """Fill the cache at startup so the first dashboard load is never slow."""
    hits = 0
    for narrative, lang in narratives:
        if rephrase(narrative, lang).source.startswith("llm"):
            hits += 1
    return hits
