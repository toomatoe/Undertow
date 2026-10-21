"""Optional Claude cluster namer (after the LLM-named event clusters of arXiv 2408.11133).

Used only when `get_settings().enrich_enabled` (ANTHROPIC_API_KEY set); model = settings.enrich_model, called the
same way as app/pipeline/enrich.py (anthropic SDK). Names are cached in {data_dir}/graph_names.json keyed by the
sha256 of the sorted member ids + terms (atomic write), so an unchanged cluster is never sent twice. Any failure
returns None and the engine falls back to the c-TF-IDF name. Tests never construct this class with a real client.

Namer contract (also for injected fakes): `namer(info) -> str | None`, info = {id, member_ids, terms, titles,
tickers, signal_label}.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import threading

from app.graph.naming import NAME_MAX, clean_llm_name

log = logging.getLogger(__name__)

CACHE_FILE = "graph_names.json"
CACHE_MAX = 2000

SYSTEM_PROMPT = f"""You name groups of related SEC filings and market news headlines for a research dashboard.
Given a group's distinctive terms, headlines and tickers, reply with one short, neutral, descriptive name for what the
items have in common (at most {NAME_MAX} characters). Describe the topic only. Never suggest trading, never use words
such as buy, sell, target or profit, and never claim that one event produced another."""

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {"name": {"type": "string"}},
    "required": ["name"],
    "additionalProperties": False,
}

_file_lock = threading.Lock()


def cache_key(info: dict) -> str:
    payload = json.dumps({"ids": sorted(int(i) for i in info.get("member_ids", [])), "terms": list(info.get("terms", []))},
                         sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


class LLMNamer:
    def __init__(self, api_key: str, model: str, data_dir: str, client=None):
        if client is None:
            import anthropic

            client = anthropic.Anthropic(api_key=api_key)
        self.client = client
        self.model = model
        self.path = os.path.join(data_dir, CACHE_FILE)

    # --- cache -------------------------------------------------------------------
    def _load(self) -> dict:
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _store(self, key: str, name: str) -> None:
        with _file_lock:
            data = self._load()
            data[key] = name
            if len(data) > CACHE_MAX:
                data = dict(list(data.items())[-CACHE_MAX:])
            d = os.path.dirname(self.path) or "."
            try:
                os.makedirs(d, exist_ok=True)
                fd, tmp = tempfile.mkstemp(prefix=".graph_names.", dir=d)
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(data, f, sort_keys=True)
                os.replace(tmp, self.path)
            except OSError as exc:
                log.warning("Could not write %s: %s", self.path, exc)

    # --- call ----------------------------------------------------------------------
    def __call__(self, info: dict) -> str | None:
        key = cache_key(info)
        cached = self._load().get(key)
        if isinstance(cached, str) and clean_llm_name(cached):
            return cached
        try:
            name = clean_llm_name(self._ask(info))
        except Exception as exc:  # any failure -> the engine uses the terms name
            log.warning("Cluster naming failed: %s", exc)
            return None
        if name:
            self._store(key, name)
        return name

    def _ask(self, info: dict) -> str | None:
        from app.pipeline.enrich import _FALLBACK_MODELS

        titles = "\n".join(f"- {t[:200]}" for t in list(info.get("titles", []))[:12])
        content = (
            f"Distinctive terms: {', '.join(info.get('terms', [])) or '(none)'}\n"
            f"Most common signal: {info.get('signal_label') or '(none)'}\n"
            f"Tickers: {', '.join(info.get('tickers', [])) or '(none)'}\n"
            f"Headlines:\n{titles or '(none)'}"
        )
        kwargs = dict(
            model=self.model,
            max_tokens=300,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content}],
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
        )
        if self.model.startswith(_FALLBACK_MODELS):
            response = self.client.beta.messages.create(
                betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs
            )
        else:
            response = self.client.messages.create(**kwargs)
        if getattr(response, "stop_reason", None) in ("refusal", "max_tokens"):
            return None
        text = next((b.text for b in response.content if getattr(b, "type", None) == "text"), None)
        if not text:
            return None
        return json.loads(text).get("name")


def default_namer(settings) -> LLMNamer | None:
    """The Claude namer when ANTHROPIC_API_KEY is set, else None (terms naming only)."""
    if not settings.enrich_enabled:
        return None
    try:
        return LLMNamer(settings.anthropic_api_key, settings.enrich_model, settings.data_dir)
    except Exception as exc:
        log.warning("Cluster namer unavailable: %s", exc)
        return None
