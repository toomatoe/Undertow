from app.pipeline.dedupe import canonical_url, title_hash, url_hash
from app.pipeline.tickers import Company, TickerUniverse, tag_tickers
from app.sources.edgar import event_from_items, parse_items

UNIVERSE = TickerUniverse(
    [
        Company("AAPL", 320193, "Apple Inc."),
        Company("BRK.B", 1067983, "Berkshire Hathaway Inc"),
        Company("NVDA", 1045810, "NVIDIA CORP"),
    ]
)


def test_canonical_url_strips_tracking_and_fragment():
    a = canonical_url("https://WWW.Example.com/story/123/?utm_source=x&id=7#comments")
    b = canonical_url("https://www.example.com/story/123?id=7")
    assert a == b
    assert url_hash("https://x.com/a?utm_medium=rss") == url_hash("https://x.com/a")


def test_title_hash_ignores_case_and_punctuation():
    assert title_hash("Apple Beats Estimates!") == title_hash("apple beats estimates")
    assert title_hash("Apple beats") != title_hash("Apple misses")


def test_tag_tickers_cashtag_and_exchange():
    text = "Shares of $NVDA jumped; Berkshire (NYSE: BRK.B) added. $FAKE is not real. Price $5."
    assert tag_tickers(text, UNIVERSE) == {("NVDA", "cashtag"), ("BRK.B", "exchange")}


def test_tag_tickers_exchange_list():
    text = "Alphabet Inc. (NASDAQ: GOOGL, GOOG) and (NYSE: NVDA; BRK.B)"
    universe = TickerUniverse(list(UNIVERSE.by_ticker.values()) + [Company("GOOGL", 1652044, "Alphabet Inc."), Company("GOOG", 1652044, "Alphabet Inc.")])
    assert tag_tickers(text, universe) == {
        ("GOOGL", "exchange"), ("GOOG", "exchange"), ("NVDA", "exchange"), ("BRK.B", "exchange")
    }


def test_tag_tickers_ignores_plain_words():
    assert tag_tickers("Apple and AAPL rallied in the US", UNIVERSE) == set()


def test_edgar_items_to_event():
    summary = "Filed: 2026-10-15 Item 2.02: Results of Operations Item 9.01: Financial Statements"
    items = parse_items(summary)
    assert items == ["2.02", "9.01"]
    assert event_from_items(items) == "earnings"
    assert event_from_items(["8.01"]) == "other"
    assert event_from_items([]) is None


def test_universe_cik_lookup():
    assert UNIVERSE.tickers_for_cik(320193) == ["AAPL"]
    assert UNIVERSE.tickers_for_cik(1) == []


def test_edgar_fetch_survives_one_failed_form(monkeypatch):
    import httpx
    import pytest

    from app.sources import edgar

    atom = b"""<?xml version="1.0" encoding="ISO-8859-1" ?>
<feed xmlns="http://www.w3.org/2005/Atom">
<entry>
<title>8-K - Apple Inc. (0000320193) (Filer)</title>
<link href="https://www.sec.gov/Archives/edgar/data/320193/000032019326000001/0000320193-26-000001-index.htm"/>
<summary type="html">Item 2.02: Results of Operations</summary>
<updated>2026-10-15T16:05:00-04:00</updated>
</entry>
</feed>"""
    calls = []

    def fake_get(url, params, headers, timeout):
        calls.append(params["type"])
        request = httpx.Request("GET", url)
        if params["type"] == "S-1":
            return httpx.Response(503, request=request)
        return httpx.Response(200, content=atom, request=request)

    monkeypatch.setattr(edgar.httpx, "get", fake_get)
    monkeypatch.setattr(edgar.time, "sleep", lambda s: None)

    articles = edgar.EdgarSource("test-agent", UNIVERSE, forms=["S-1", "8-K"]).fetch()
    assert calls == ["S-1", "8-K"]
    assert [a.title for a in articles] == ["8-K: Apple Inc. (items 2.02)"]
    assert articles[0].tickers == {("AAPL", "edgar")}

    with pytest.raises(RuntimeError, match="All EDGAR feeds failed"):
        edgar.EdgarSource("test-agent", UNIVERSE, forms=["S-1"]).fetch()


def test_edgar_sc_13d_maps_to_activist():
    from app.sources.edgar import FORM_EVENTS

    assert FORM_EVENTS["SC 13D"] == "activist"
