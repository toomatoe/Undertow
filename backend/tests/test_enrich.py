import json
from types import SimpleNamespace

from app.pipeline.enrich import Enricher


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


def test_enrich_handles_refusal_and_bad_output():
    assert make_enricher("claude-haiku-5-5", fake_response(GOOD, "refusal"), []).enrich("x", None, "s") is None
    bad = dict(GOOD, sentiment=5)
    assert make_enricher("claude-haiku-5-5", fake_response(bad), []).enrich("x", None, "s") is None
