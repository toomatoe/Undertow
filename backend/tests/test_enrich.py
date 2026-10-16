import json
from datetime import datetime, timezone
from types import SimpleNamespace

import anthropic
import httpx
import pytest

from app.db import Base, SessionLocal, engine
from app.models import Article
from app.pipeline.enrich import Enricher, EnrichmentFailed
from app.pipeline.ingest import enrich_pending
from app.pipeline.tickers import TickerUniverse


def fake_response(payload: dict | None, stop_reason: str = "end_turn"):
    content = [SimpleNamespace(type="text", text=json.dumps(payload))] if payload else []
    return SimpleNamespace(stop_reason=stop_reason, content=content)


def make_enricher(model: str, response, calls: list):
    e = Enricher(api_key="test-key", model=model)

    def create(**kwargs):
        calls.append(kwargs)
        return response

    e.client = SimpleNamespace(
        messages=SimpleNamespace(create=create), beta=SimpleNamespace(messages=SimpleNamespace(create=create))
    )
    return e


GOOD = {
    "summary": "Apple beat estimates.",
    "sentiment": 0.6,
    "sentiment_label": "positive",
    "event_type": "earnings",
    "relevance": 0.9,
    "tickers": ["$aapl ", ""],
}


def test_enrich_parses_and_normalizes():
    calls = []
    result = make_enricher("claude-opus-5-5", fake_response(GOOD), calls).enrich("Apple beats", None, "CNBC")
    assert result.tickers == ["AAPL"]
    assert result.sentiment_label == "positive"
    # Opus requests carry the server-side refusal fallback and structured output schema
    assert calls[0]["fallbacks"] == "default"
    assert calls[0]["output_config"]["format"]["type"] == "json_schema"


def test_enrich_no_fallback_for_haiku():
    calls = []
    make_enricher("claude-haiku-5-5", fake_response(GOOD), calls).enrich("Apple beats", None, "CNBC")
    assert "fallbacks" not in calls[0]


@pytest.mark.parametrize(
    "response,reason",
    [
        (fake_response(GOOD, "refusal"), "refusal"),
        (fake_response(GOOD, "max_tokens"), "max_tokens"),
        (fake_response(dict(GOOD, sentiment=5)), "invalid output"),
        (fake_response(None), "empty output"),
    ],
)
def test_enrich_permanent_failures_raise(response, reason):
    with pytest.raises(EnrichmentFailed) as info:
        make_enricher("claude-haiku-5-5", response, []).enrich("x", None, "s")
    assert info.value.reason == reason


def test_enrich_transient_failure_returns_none():
    e = make_enricher("claude-haiku-5-5", None, [])
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")

    def create(**kwargs):
        raise anthropic.RateLimitError("slow down", response=httpx.Response(429, request=request), body=None)

    e.client = SimpleNamespace(messages=SimpleNamespace(create=create))
    assert e.enrich("x", None, "s") is None


def _article(url: str, title: str) -> Article:
    return Article(
        url=url, url_hash=url, title_hash=url, title=title, source="rss", source_name="Test",
        published_at=datetime.now(timezone.utc),
    )


def test_enrich_pending_marks_permanent_failures_and_keeps_transient_pending():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    class StubEnricher:
        model = "claude-haiku-5-5"

        def enrich(self, title, snippet, source_name, body=None):
            if title == "refused":
                raise EnrichmentFailed("refusal")
            return None  # transient

    with SessionLocal() as s:
        s.add_all([_article("u1", "refused"), _article("u2", "rate limited")])
        s.commit()
        assert enrich_pending(s, StubEnricher(), TickerUniverse([]), limit=10) == 0
        refused = s.query(Article).filter_by(title="refused").one()
        assert refused.enriched_at is not None
        assert refused.enrich_model == "claude-haiku-5-5 (failed: refusal)"
        assert refused.ai_summary is None
        pending = s.query(Article).filter_by(title="rate limited").one()
        assert pending.enriched_at is None and pending.enrich_model is None
        # The refused row no longer takes budget on the next cycle
        seen = []
        StubEnricher.enrich = lambda self, title, *a, **k: seen.append(title)
        enrich_pending(s, StubEnricher(), TickerUniverse([]), limit=10)
        assert seen == ["rate limited"]
