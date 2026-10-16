"""Signal alerts: push new filing signals to Discord within seconds of detection.

Registered as a NEW_ARTICLE_HOOK in pipeline.ingest, so it runs right after a
filing is stored by the fast EDGAR poll. Every decision (sent, skipped, failed)
is written to alert_log with the detection latency (EDGAR acceptance -> now),
which is the product's speed metric.

Rules (all in config): signal severity >= alert_min_severity, and the company
is in alert_sizes or on the watchlist, and the filing is newer than
alert_max_age_minutes. Content is impersonal and factual: what was filed, size,
and the Edge Lab's historical evidence, never a recommendation.
"""

import logging
import statistics
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import SessionLocal
from app.models import AlertLog, Article, Company, WatchlistItem
from app.pipeline.signals import ALL_SIGNALS

log = logging.getLogger(__name__)

DIRECTION_ICON = {"-": "🔻", "+": "🔺", "?": "🔷"}
DISCLAIMER = "Automated filing alert. Historical stats are hypothetical and not investment advice."


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _money(v: int | None) -> str:
    if not v:
        return "unknown float"
    return f"${v / 1e9:.1f}B float" if v >= 1e9 else f"${v / 1e6:.0f}M float"


def format_message(article: Article, company: Company | None, evidence: list[dict], latency_s: float) -> dict:
    """Discord webhook payload (one embed). Pure function, easy to test."""
    sigs = [ALL_SIGNALS[c] for c in (article.signals or []) if c in ALL_SIGNALS]
    top = sigs[0]
    ticker = company.symbol if company else (article.tickers[0].symbol if article.tickers else "?")
    lines = [f"{DIRECTION_ICON[s.direction]} **{s.label}**: {s.why}" for s in sigs[:4]]
    for ev in evidence[:2]:
        excess = ev.get("excess_vs_baseline")
        lines.append(
            f"📊 Past {ev['bucket']} caps after this signal: {ev['mean_abnormal']:+.1%} vs index over {ev['horizon_days']}d"
            + (f" ({excess:+.1%} vs ordinary days)" if excess is not None else "")
            + f", n={ev['n']}" + (" · statistically significant" if ev.get("significant") else "")
        )
    size = f"{company.size_bucket} cap, {_money(company.public_float)}" if company and company.size_bucket else "size unknown"
    return {
        "username": "QuantDesk",
        "embeds": [{
            "title": f"${ticker} · {article.form or 'Filing'} · {top.label}"[:256],
            "url": article.url,
            "description": "\n".join(lines)[:4000],
            "color": 0xE34948 if top.direction == "-" else 0x2A78D6,
            "fields": [
                {"name": "Company", "value": (article.title.split(": ", 1)[-1])[:1024], "inline": False},
                {"name": "Size", "value": size, "inline": True},
                {"name": "Detected", "value": f"{latency_s:.0f}s after SEC acceptance", "inline": True},
            ],
            "footer": {"text": DISCLAIMER},
            "timestamp": _aware(article.published_at).isoformat(),
        }],
    }


def decide(article: Article, company: Company | None, watchlist: set[str], settings: Settings, now: datetime) -> str | None:
    """Return a skip reason, or None if the filing should alert."""
    if article.source != "edgar" or not article.signals:
        return "no_signal"
    if (article.severity or 0) < settings.alert_min_severity:
        return "below_severity"
    if now - _aware(article.published_at) > timedelta(minutes=settings.alert_max_age_minutes):
        return "too_old"
    symbols = {t.symbol for t in article.tickers}
    if symbols & watchlist:
        return None
    if company is None or company.size_bucket not in settings.alert_sizes:
        return "outside_size_filter"
    return None


class Alerter:
    def __init__(self, settings: Settings, evidence_for: Callable[[Article], list[dict]], post=httpx.post):
        self.settings = settings
        self.evidence_for = evidence_for
        self.post = post

    @property
    def channel(self) -> str:
        return "discord" if self.settings.discord_webhook_url else "none"

    def __call__(self, article_id: int) -> None:
        with SessionLocal() as session:
            self.handle(session, article_id)

    def handle(self, session: Session, article_id: int, now: datetime | None = None) -> AlertLog | None:
        now = now or datetime.now(timezone.utc)
        article = session.get(Article, article_id)
        if article is None or article.source != "edgar" or not article.signals:
            return None  # news articles never alert and aren't logged
        company = next((c for t in article.tickers if (c := session.get(Company, t.symbol)) is not None), None)
        watchlist = set(session.scalars(select(WatchlistItem.symbol)).all())
        latency = (now - _aware(article.published_at)).total_seconds()
        entry = AlertLog(article_id=article.id, channel=self.channel, detected_at=now, latency_seconds=round(latency, 1))
        reason = decide(article, company, watchlist, self.settings, now)
        if reason is None and self.channel == "none":
            reason = "no_channel_configured"
        if reason:
            entry.status, entry.reason = "skipped", reason
        else:
            try:
                resp = self.post(self.settings.discord_webhook_url, json=format_message(article, company, self.evidence_for(article), latency), timeout=10)
                resp.raise_for_status()
                entry.status = "sent"
            except Exception as exc:  # never let delivery problems break ingestion
                entry.status, entry.reason = "failed", type(exc).__name__[:64]
                log.warning("Alert delivery failed for %s: %s", article.id, exc)
        session.add(entry)
        session.commit()
        return entry

    def send_test(self) -> dict:
        if self.channel == "none":
            return {"ok": False, "error": "Set DISCORD_WEBHOOK_URL in .env and restart the API."}
        resp = self.post(self.settings.discord_webhook_url, json={"username": "QuantDesk", "content": "✅ QuantDesk test alert: delivery works."}, timeout=10)
        return {"ok": resp.status_code < 300, "status": resp.status_code}


def stats(session: Session, limit: int = 100) -> dict:
    rows = session.scalars(select(AlertLog).order_by(AlertLog.id.desc()).limit(limit)).all()
    lat = sorted(r.latency_seconds for r in rows if r.latency_seconds is not None and r.latency_seconds >= 0)
    counts: dict[str, int] = {}
    for r in rows:
        key = r.status if r.status != "skipped" else f"skipped:{r.reason}"
        counts[key] = counts.get(key, 0) + 1
    return {
        "recent": len(rows),
        "latency_median_s": round(statistics.median(lat), 1) if lat else None,
        "latency_p90_s": round(lat[min(len(lat) - 1, int(0.9 * len(lat)))], 1) if lat else None,
        "counts": counts,
    }
