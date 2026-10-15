"""LLM enrichment: summary, sentiment, event type, relevance and extra tickers per article.

Results are stored with the model name so they can be compared or re-run later.
Sentiment is scored from the headline/snippet only, at ingestion time, so a
backtest that uses it has no look-ahead (as long as the model's training
cutoff predates the articles being tested).
"""

import json
import logging
from typing import Literal

import anthropic
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

EVENT_TYPES = [
    "earnings", "guidance", "m&a", "deal", "analyst", "management", "legal",
    "regulatory", "product", "macro", "bankruptcy", "restructuring", "impairment",
    "accounting", "listing", "offering", "activist", "disclosure", "other",
]

# Facts that matter disproportionately for small caps. Only set when the text states them.
FLAGS = [
    "going_concern", "reverse_split", "dilutive_financing", "atm_program", "warrants_issued",
    "delisting_risk", "ceo_departure", "cfo_departure", "auditor_resigned", "restatement",
    "guidance_raised", "guidance_cut", "layoffs", "fda_decision", "clinical_trial_result",
    "major_contract", "buyback", "dividend_change", "insider_purchase", "acquisition_target",
]
BODY_CHARS = 8000  # enough for the substance of a press release or 8-K item

# Server-side refusal fallback is supported on these models only.
_FALLBACK_MODELS = ("claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5")

SYSTEM_PROMPT = """You annotate financial news and SEC filings for a market research dashboard focused on small companies.
For each item, using only the text provided:
- summary: neutral and concrete, max 40 words: what happened, key numbers, and why it matters to shareholders. For filings, describe the substance, not the form.
- flags: every listed fact the text explicitly states (e.g. going_concern only if substantial doubt about continuing as a going concern is disclosed). Empty if none.
- sentiment: expected short-term price impact on the primary company (or the broad market for macro news), from -1 (very negative) to 1 (very positive). Use 0 when unclear.
- sentiment_label: negative (< -0.15), positive (> 0.15), otherwise neutral.
- event_type: the single best category.
- relevance: 0 to 1, how likely this moves a tradable security's price. Lifestyle, promotional or generic content is near 0.
- tickers: US exchange tickers of companies that are the subject of the article (not ones merely mentioned). Empty if none. Never guess."""


class Enrichment(BaseModel):
    summary: str
    sentiment: float = Field(ge=-1, le=1)
    sentiment_label: Literal["negative", "neutral", "positive"]
    event_type: str
    relevance: float = Field(ge=0, le=1)
    tickers: list[str]
    flags: list[str] = []


OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "flags": {"type": "array", "items": {"type": "string", "enum": FLAGS}},
        "sentiment": {"type": "number"},
        "sentiment_label": {"type": "string", "enum": ["negative", "neutral", "positive"]},
        "event_type": {"type": "string", "enum": EVENT_TYPES},
        "relevance": {"type": "number"},
        "tickers": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "sentiment", "sentiment_label", "event_type", "relevance", "tickers", "flags"],
    "additionalProperties": False,
}


class Enricher:
    def __init__(self, api_key: str, model: str):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def enrich(self, title: str, snippet: str | None, source_name: str, body: str | None = None) -> Enrichment | None:
        content = f"Source: {source_name}\nHeadline: {title}\nSnippet: {snippet or '(none)'}"
        if body:
            content += f"\n\nDocument text (truncated):\n{body[:BODY_CHARS]}"
        kwargs = dict(
            model=self.model,
            max_tokens=2000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content}],
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
        )
        try:
            if self.model.startswith(_FALLBACK_MODELS):
                response = self.client.beta.messages.create(
                    betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs
                )
            else:
                response = self.client.messages.create(**kwargs)
        except anthropic.RateLimitError:
            log.warning("Enrichment rate-limited; will retry next cycle")
            return None
        except anthropic.APIStatusError as exc:
            log.error("Enrichment API error %s: %s", exc.status_code, exc.message)
            return None
        except anthropic.APIConnectionError as exc:
            log.warning("Enrichment connection error: %s", exc)
            return None

        if response.stop_reason in ("refusal", "max_tokens"):
            log.info("Enrichment skipped (%s): %s", response.stop_reason, title[:80])
            return None
        text = next((b.text for b in response.content if b.type == "text"), None)
        if not text:
            return None
        try:
            result = Enrichment.model_validate(json.loads(text))
        except ValueError as exc:
            log.warning("Enrichment output failed validation: %s", exc)
            return None
        result.tickers = [t.strip().upper().lstrip("$") for t in result.tickers if t.strip()]
        return result
