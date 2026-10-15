from datetime import datetime, timedelta, timezone

from app.db import Base, SessionLocal, engine
from app.models import Article
from app.pipeline.ingest import store
from app.pipeline.tickers import Company, TickerUniverse
from app.sources.base import RawArticle

UNIVERSE = TickerUniverse([Company("AAPL", 320193, "Apple Inc.")])


def setup_module():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def raw(url: str, title: str, hours_ago: float = 0, **kw) -> RawArticle:
    return RawArticle(
        url=url,
        title=title,
        published_at=datetime.now(timezone.utc) - timedelta(hours=hours_ago),
        source="rss",
        source_name="Test",
        **kw,
    )


def test_store_dedupes_by_url_and_title():
    with SessionLocal() as s:
        a = store(s, raw("https://a.com/1?utm_source=x", "Apple $AAPL beats"), UNIVERSE)
        assert a is not None
        assert [(t.symbol, t.method) for t in a.tickers] == [("AAPL", "cashtag")]
        # same URL, tracking param differs
        assert store(s, raw("https://a.com/1", "Different title"), UNIVERSE) is None
        # syndicated copy, different URL, same headline
        assert store(s, raw("https://b.com/x", "apple $AAPL beats!"), UNIVERSE) is None
        s.commit()
        assert s.query(Article).count() == 1


def test_vendor_tickers_take_precedence():
    with SessionLocal() as s:
        a = store(s, raw("https://c.com/2", "Apple $AAPL news", tickers={("AAPL", "vendor")}), UNIVERSE)
        assert [(t.symbol, t.method) for t in a.tickers] == [("AAPL", "vendor")]
        s.rollback()
