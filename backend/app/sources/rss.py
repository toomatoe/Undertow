import calendar
import html
import re
from datetime import datetime, timezone

import feedparser
import httpx

from app.sources.base import RawArticle

_TAG_RE = re.compile(r"<[^>]+>")


def clean_html(text: str | None, limit: int = 600) -> str | None:
    if not text:
        return None
    text = html.unescape(_TAG_RE.sub(" ", text))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit] or None


def entry_published(entry) -> datetime:
    for key in ("published_parsed", "updated_parsed"):
        parsed = entry.get(key)
        if parsed:
            return datetime.fromtimestamp(calendar.timegm(parsed), tz=timezone.utc)
    return datetime.now(timezone.utc)


class RssSource:
    def __init__(self, name: str, url: str, user_agent: str):
        self.name = name
        self.url = url
        self.user_agent = user_agent

    def fetch(self) -> list[RawArticle]:
        resp = httpx.get(
            self.url,
            headers={"User-Agent": self.user_agent},
            timeout=20,
            follow_redirects=True,
        )
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
        articles = []
        for entry in feed.entries:
            link, title = entry.get("link"), entry.get("title")
            if not link or not title:
                continue
            articles.append(
                RawArticle(
                    url=link,
                    title=clean_html(title, 500) or title,
                    published_at=entry_published(entry),
                    source="rss",
                    source_name=self.name,
                    snippet=clean_html(entry.get("summary")),
                    author=entry.get("author"),
                )
            )
        return articles
