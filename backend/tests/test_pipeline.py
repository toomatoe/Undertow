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
