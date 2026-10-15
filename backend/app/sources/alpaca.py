"""Alpaca market-data news (Benzinga). Free with an Alpaca paper-trading account."""

from datetime import datetime

import httpx

from app.sources.base import RawArticle
from app.sources.rss import clean_html

NEWS_URL = "https://data.alpaca.markets/v1beta1/news"


class AlpacaNewsSource:
    name = "Alpaca / Benzinga"

    def __init__(self, key_id: str, secret_key: str):
        self.headers = {"APCA-API-KEY-ID": key_id, "APCA-API-SECRET-KEY": secret_key}

    def fetch(self) -> list[RawArticle]:
        resp = httpx.get(
            NEWS_URL,
            headers=self.headers,
            params={"limit": 50, "sort": "desc", "include_content": "false"},
            timeout=20,
        )
        resp.raise_for_status()
        articles = []
        for item in resp.json().get("news", []):
            if not item.get("url") or not item.get("headline"):
                continue
            articles.append(
                RawArticle(
                    url=item["url"],
                    title=item["headline"],
                    published_at=datetime.fromisoformat(item["created_at"].replace("Z", "+00:00")),
                    source="alpaca",
                    source_name=f"{item.get('source', 'benzinga').title()} (Alpaca)",
                    snippet=clean_html(item.get("summary")),
                    author=item.get("author"),
                    tickers={(s.upper(), "vendor") for s in item.get("symbols", [])},
                )
            )
        return articles
