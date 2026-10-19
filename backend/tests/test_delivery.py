import json
import re
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import Base, SessionLocal, engine, get_session
from app.delivery import digest as digest_mod
from app.delivery import service
from app.delivery.routes import DISABLED_DETAIL, make_router
from app.delivery.settings import DeliverySettings
from app.delivery.transport import FakeTransport
from app.models import Article, ArticleTicker, Company, EmailSend, Subscriber, TradingHalt
from app.newsletter import service as nl

DAY = date(2026, 10, 7)  # Wednesday, in ISO week 2026-W41 (Oct 5..11)
WEEK_END = date(2026, 10, 11)
POSTAL = "123 Example Street, Springfield, ST 00000"
BANNED = re.compile(r"\b(buy\w*|sell\w*|short it|target\w*|opportunit\w*|guarantee\w*|profit\w*)\b", re.I)


def utc(*a):
    return datetime(*a, tzinfo=timezone.utc)


def enabled_settings(**kw) -> DeliverySettings:
    base = dict(_env_file=None, smtp_host="smtp.test.invalid", email_from="QuantDesk <radar@example.com>",
                email_reply_to="hello@example.com", email_postal_address=POSTAL,
                email_link_base_url="https://api.example.com", email_token_secret="test-secret-key")
    return DeliverySettings(**{**base, **kw})


def disabled_settings() -> DeliverySettings:
    return DeliverySettings(_env_file=None)


class Env:
    def __init__(self):
        self.settings = enabled_settings()
        self.transport = FakeTransport()


@pytest.fixture
def env():
    return Env()


@pytest.fixture
def client(env):
    app = FastAPI()
    app.include_router(make_router(get_session, get_settings=lambda: env.settings, make_transport=lambda s: env.transport))
    return TestClient(app)


@pytest.fixture
def data_dir(tmp_path):
    (tmp_path / "event_study.json").write_text(json.dumps({"results": [
        {"signal": "delisting_notice", "bucket": "nano", "horizon_days": 20, "n": 140, "mean_abnormal": -0.081,
         "median_abnormal": -0.06, "excess_vs_baseline": -0.05, "t_stat": -4.2, "significant": True},
    ]}))
    return tmp_path


_n = 0


def filing(sym, form, signals, severity, when):
    global _n
    _n += 1
    a = Article(url=f"https://www.sec.gov/Archives/edgar/data/{_n}", url_hash=f"dh{_n}", title_hash=f"dt{_n}", title=f"{form}: {sym}",
                source="edgar", source_name="SEC EDGAR", published_at=when, form=form, signals=signals, severity=severity)
    a.tickers = [ArticleTicker(symbol=sym, method="edgar")]
    return a


def setup_function():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        s.add_all([
            Company(symbol="TINY", cik=1, name="Tiny Therapeutics", size_bucket="nano", public_float=20_000_000),
            Company(symbol="MIDL", cik=2, name="Middle Corp", size_bucket="micro", public_float=150_000_000),
            Company(symbol="BIG", cik=3, name="Big Corp", size_bucket="large", public_float=50_000_000_000),
        ])
        s.add_all([
            filing("TINY", "8-K", ["delisting_notice"], 3, utc(2026, 10, 7, 14)),       # in: Oct 7 ET
            filing("MIDL", "8-K", ["auditor_change"], 2, utc(2026, 10, 8, 3, 30)),     # Oct 7 23:30 ET: in, no evidence row
            filing("MIDL", "8-K", ["officer_change"], 1, utc(2026, 10, 7, 15)),        # severity 1: out
            filing("BIG", "8-K", ["bankruptcy"], 3, utc(2026, 10, 7, 12)),             # large cap: out
            filing("TINY", "8-K", ["delisting_notice"], 3, utc(2026, 10, 7, 3)),       # Oct 6 23:00 ET: out
        ])
        s.add(TradingHalt(symbol="TINY", name="Tiny Therapeutics", market="NASDAQ", reason_code="T1", halted_at=utc(2026, 10, 7, 17)))
        s.commit()


def active_subscriber(email, daily=False, settings=None):
    s = settings or enabled_settings()
    with SessionLocal() as session:
        sub = Subscriber(email=email, status="active", wants_daily=daily, created_at=utc(2026, 10, 1), confirmed_at=utc(2026, 10, 1))
        service._ensure_manage(sub, s)
        session.add(sub)
        session.commit()
        return sub.id


def text_part(msg) -> str:
    return msg.get_body(preferencelist=("plain",)).get_content()


def html_part(msg) -> str:
    return msg.get_body(preferencelist=("html",)).get_content()


def link(msg, path) -> str:
    m = re.search(rf"https://api\.example\.com{re.escape(path)}\?token=([A-Za-z0-9_\-]+)", text_part(msg))
    assert m, text_part(msg)
    return m.group(1)


def count(model) -> int:
    with SessionLocal() as s:
        return len(s.scalars(select(model)).all())


# --- subscribe / confirm / unsubscribe ---------------------------------------------


def test_disabled_returns_503_and_stores_nothing(client, env):
    env.settings = disabled_settings()
    r = client.post("/api/subscribe", json={"email": "a@example.com"})
    assert r.status_code == 503
    assert r.json() == {"detail": DISABLED_DETAIL}
    assert count(Subscriber) == 0 and count(EmailSend) == 0
    assert env.transport.sent == []
    assert client.get("/api/delivery/status").json() == {"enabled": False}


def test_disabled_without_env_by_default(monkeypatch):
    for k in ("SMTP_HOST", "EMAIL_FROM", "EMAIL_POSTAL_ADDRESS"):
        monkeypatch.delenv(k, raising=False)
    assert DeliverySettings(_env_file=None).enabled is False
    with SessionLocal() as s:
        assert service.send_newsletter(s, "/nonexistent", "2026-W41", FakeTransport(), settings=disabled_settings())["sent"] == 0
        assert service.send_daily_digest(s, "/nonexistent", DAY, FakeTransport(), settings=disabled_settings())["sent"] == 0
        with pytest.raises(service.DeliveryDisabled):
            service.subscribe(s, "a@example.com", False, FakeTransport(), settings=disabled_settings())
    assert count(Subscriber) == 0


@pytest.mark.parametrize("bad", ["", "plainaddress", "a@b", "a b@example.com", "a@example.com\r\nBcc: x@y.com",
                                 "x" * 65 + "@example.com", "a@" + "b" * 250 + ".com", "a..b@example.com"])
def test_invalid_emails_get_422(client, env, bad):
    r = client.post("/api/subscribe", json={"email": bad})
    assert r.status_code == 422
    assert count(Subscriber) == 0 and env.transport.sent == []


def test_double_opt_in_flow(client, env):
    r = client.post("/api/subscribe", json={"email": "  Reader@Example.COM ", "daily": True})
    assert r.status_code == 202
    generic = r.json()
    assert generic == {"message": service.GENERIC_MESSAGE}
    assert len(env.transport.sent) == 1
    msg = env.transport.sent[0]
    assert msg["To"] == "reader@example.com"
    token = link(msg, "/api/subscribe/confirm")

    with SessionLocal() as s:
        sub = s.scalar(select(Subscriber))
        assert sub.email == "reader@example.com" and sub.status == "pending" and sub.wants_daily is True

    page = client.get("/api/subscribe/confirm", params={"token": token})
    assert page.status_code == 200 and "Subscription confirmed" in page.text
    assert page.headers["referrer-policy"] == "no-referrer"
    with SessionLocal() as s:
        sub = s.scalar(select(Subscriber))
        assert sub.status == "active" and sub.confirmed_at is not None
    # Idempotent second click
    assert "Already confirmed" in client.get("/api/subscribe/confirm", params={"token": token}).text

    # Duplicate subscribe of an active address: same generic response, nothing sent, prefs unchanged
    r2 = client.post("/api/subscribe", json={"email": "reader@example.com", "daily": False})
    assert r2.status_code == 202 and r2.json() == generic
    assert len(env.transport.sent) == 1
    with SessionLocal() as s:
        assert s.scalar(select(Subscriber)).wants_daily is True

    # Unknown address also gets the identical response (no enumeration)
    assert client.post("/api/subscribe", json={"email": "other@example.com"}).json() == generic


def test_pending_resubscribe_same_day_sends_one_confirm(client, env):
    client.post("/api/subscribe", json={"email": "p@example.com"})
    client.post("/api/subscribe", json={"email": "p@example.com"})
    assert len(env.transport.sent) == 1
    assert count(Subscriber) == 1


def test_confirm_bad_or_expired_token(client, env):
    assert client.get("/api/subscribe/confirm", params={"token": "nope"}).status_code == 404
    client.post("/api/subscribe", json={"email": "late@example.com"})
    token = link(env.transport.sent[0], "/api/subscribe/confirm")
    with SessionLocal() as s:
        later = datetime.now(timezone.utc) + timedelta(days=service.CONFIRM_TTL_DAYS + 1)
        assert service.confirm(s, token, now=later) == "expired"
        assert s.scalar(select(Subscriber)).status == "pending"


def test_unsubscribe_get_page_and_post_one_click(client, env):
    client.post("/api/subscribe", json={"email": "u@example.com"})
    msg = env.transport.sent[0]
    client.get("/api/subscribe/confirm", params={"token": link(msg, "/api/subscribe/confirm")})
    token = link(msg, "/api/unsubscribe")

    page = client.get("/api/unsubscribe", params={"token": token})
    assert page.status_code == 200 and '<form method="post"' in page.text and "<button" in page.text
    with SessionLocal() as s:
        assert s.scalar(select(Subscriber)).status == "active"  # GET alone never unsubscribes

    r = client.post(f"/api/unsubscribe?token={token}", data={"List-Unsubscribe": "One-Click"})
    assert r.status_code == 200
    with SessionLocal() as s:
        sub = s.scalar(select(Subscriber))
        assert sub.status == "unsubscribed" and sub.unsubscribed_at is not None
    assert client.post(f"/api/unsubscribe?token={token}").status_code == 200  # idempotent
    assert client.post("/api/unsubscribe?token=bogus").status_code == 404
    # The old confirm link cannot resubscribe
    assert client.get("/api/subscribe/confirm", params={"token": link(msg, "/api/subscribe/confirm")}).status_code == 404


def test_daily_toggle(client, env):
    sid = active_subscriber("d@example.com", daily=False, settings=env.settings)
    token = service.manage_token("d@example.com", env.settings)
    assert client.post("/api/subscription/daily", params={"token": token, "on": "true"}).json() == {"wants_daily": True}
    with SessionLocal() as s:
        assert s.get(Subscriber, sid).wants_daily is True
    assert client.post("/api/subscription/daily", params={"token": "bad", "on": "true"}).status_code == 404


def test_tokens_stored_only_as_sha256(client, env):
    client.post("/api/subscribe", json={"email": "h@example.com"})
    msg = env.transport.sent[0]
    confirm_raw, manage_raw = link(msg, "/api/subscribe/confirm"), link(msg, "/api/unsubscribe")
    with SessionLocal() as s:
        sub = s.scalar(select(Subscriber))
        assert sub.confirm_token_hash == service.hash_token(confirm_raw)
        assert sub.manage_token_hash == service.hash_token(manage_raw)
        dump = json.dumps([[str(v) for v in row] for row in s.execute(select(Subscriber.__table__)).all()]
                          + [[str(v) for v in row] for row in s.execute(select(EmailSend.__table__)).all()])
    assert confirm_raw not in dump and manage_raw not in dump
    columns = {c.name for c in Subscriber.__table__.columns} | {c.name for c in EmailSend.__table__.columns}
    assert not {c for c in columns if "ip" in c.split("_") or "agent" in c}


def test_status_counts(env):
    active_subscriber("a1@example.com")
    with SessionLocal() as s:
        service.subscribe(s, "p1@example.com", False, env.transport, settings=env.settings)
        assert service.status(s, env.settings) == {"enabled": True, "active": 1, "pending": 1}


def test_purge_pending():
    with SessionLocal() as s:
        s.add(Subscriber(email="old@example.com", status="pending", created_at=utc(2026, 1, 1)))
        s.add(Subscriber(email="new@example.com", status="pending", created_at=utc(2026, 10, 18)))
        s.commit()
        assert service.purge_pending(s, now=utc(2026, 10, 19)) == 1
        assert [x.email for x in s.scalars(select(Subscriber))] == ["new@example.com"]


# --- newsletter fan-out ------------------------------------------------------------


def test_send_newsletter_idempotent_with_compliance_headers(env, data_dir):
    a = active_subscriber("one@example.com", settings=env.settings)
    active_subscriber("two@example.com", settings=env.settings)
    with SessionLocal() as s:
        s.add(Subscriber(email="pending@example.com", status="pending", created_at=utc(2026, 10, 1)))
        s.add(Subscriber(email="gone@example.com", status="unsubscribed", created_at=utc(2026, 10, 1)))
        s.commit()
        issue, created = nl.generate(s, str(data_dir), WEEK_END, public_base_url="https://quantdesk.example")
        assert created and not issue["flagged_words"]

        r1 = service.send_newsletter(s, str(data_dir), issue["id"], env.transport, settings=env.settings)
        assert r1["sent"] == 2 and r1["failed"] == 0
        r2 = service.send_newsletter(s, str(data_dir), issue["id"], env.transport, settings=env.settings)
        assert r2["sent"] == 0 and r2["skipped"] == 2
    assert sorted(m["To"] for m in env.transport.sent) == ["one@example.com", "two@example.com"]

    msg = next(m for m in env.transport.sent if m["To"] == "one@example.com")
    token = service.manage_token("one@example.com", env.settings)
    assert msg["List-Unsubscribe"] == f"<https://api.example.com/api/unsubscribe?token={token}>, <mailto:hello@example.com?subject=unsubscribe>"
    assert msg["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    raw = msg.as_bytes()  # what smtplib sends: the header URL must survive folding intact
    assert f"<https://api.example.com/api/unsubscribe?token={token}>".encode() in raw
    assert msg["Subject"].startswith("Small-Cap Filing Radar")
    assert msg["Message-ID"] and msg["Date"] and msg["Reply-To"] == "hello@example.com"
    text, page = text_part(msg), html_part(msg)
    for body in (text, page):
        assert POSTAL in body
        assert service.DISCLAIMER in body
        assert f"/api/unsubscribe?token={token}" in body
    assert "TINY" in text and "<table" not in text  # the plain part is the archived Markdown
    assert page.index(POSTAL) < page.lower().rindex("</body>")
    with SessionLocal() as s:
        rows = s.scalars(select(EmailSend).where(EmailSend.subscriber_id == a)).all()
        assert [(r.kind, r.ref, r.status) for r in rows] == [("newsletter", "2026-W41", "sent")]


def test_send_newsletter_retries_failures_and_respects_cap(env, data_dir):
    for i in range(3):
        active_subscriber(f"s{i}@example.com", settings=env.settings)
    with SessionLocal() as s:
        issue, _ = nl.generate(s, str(data_dir), WEEK_END)
        failing = FakeTransport(fail_for={"s0@example.com"})
        r = service.send_newsletter(s, str(data_dir), issue["id"], failing, settings=enabled_settings(email_max_per_run=2))
        assert (r["sent"], r["failed"], r["deferred"]) == (1, 1, 1)
        row = s.scalar(select(EmailSend).where(EmailSend.status == "failed"))
        assert row.error.startswith("SMTPRecipientsRefused")
        r = service.send_newsletter(s, str(data_dir), issue["id"], env.transport, settings=env.settings)
        assert (r["sent"], r["failed"], r["skipped"]) == (2, 0, 1)


def test_send_newsletter_missing_or_flagged_issue(env, data_dir):
    active_subscriber("x@example.com", settings=env.settings)
    with SessionLocal() as s:
        assert service.send_newsletter(s, str(data_dir), "2026-W40", env.transport, settings=env.settings)["skipped_reason"] == "issue_not_found"
        issue, _ = nl.generate(s, str(data_dir), WEEK_END)
        path = data_dir / "newsletters" / f"{issue['id']}.json"
        path.write_text(json.dumps({**issue, "flagged_words": ["buy"]}))
        r = service.send_newsletter(s, str(data_dir), issue["id"], env.transport, settings=env.settings)
        assert r["skipped_reason"] == "flagged_words" and r["sent"] == 0
    assert env.transport.sent == []


# --- daily digest ------------------------------------------------------------------


def test_build_daily_digest_content(data_dir):
    with SessionLocal() as s:
        d = digest_mod.build_daily_digest(s, str(data_dir), DAY, public_base_url="https://quantdesk.example")
    assert [i["ticker"] for i in d["items"]] == ["TINY", "MIDL"]  # severity 3 first; sev 1, large cap, other day excluded
    assert d["halts_total"] == 1 and d["serious_halts"] == 1
    assert d["flagged_words"] == []
    md, page = d["markdown"], d["html"]
    for body in (md, page):
        assert "Historical, hypothetical: past nano caps after" in body
        assert "https://quantdesk.example/ticker/TINY" in body
        assert "https://www.sec.gov/Archives/edgar/data/" in body
        assert digest_mod.NO_EVIDENCE in body  # MIDL has no evidence row
        assert "historical and hypothetical, not predictions" in body
        assert "$" not in body  # no prices or market figures
    assert not BANNED.search(md.replace("TINY", "").replace("Tiny Therapeutics", ""))
    assert "<script" not in page and "<style" not in page and "class=" not in page


def test_daily_digest_only_to_wants_daily(env, data_dir):
    active_subscriber("daily@example.com", daily=True, settings=env.settings)
    active_subscriber("weekly@example.com", daily=False, settings=env.settings)
    with SessionLocal() as s:
        s.add(Subscriber(email="pend@example.com", status="pending", wants_daily=True, created_at=utc(2026, 10, 1)))
        s.commit()
        r = service.send_daily_digest(s, str(data_dir), DAY, env.transport, settings=env.settings)
        assert r["sent"] == 1
        assert service.send_daily_digest(s, str(data_dir), DAY, env.transport, settings=env.settings)["sent"] == 0
    assert [m["To"] for m in env.transport.sent] == ["daily@example.com"]
    msg = env.transport.sent[0]
    assert msg["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    for body in (text_part(msg), html_part(msg)):
        assert "Historical, hypothetical" in body
        assert service.DISCLAIMER in body and POSTAL in body
    assert msg["Subject"] == "QuantDesk daily filing digest: Wed Oct 7, 2026 (2 signal filings)"


def test_daily_digest_skips_empty_day(env, data_dir):
    active_subscriber("daily@example.com", daily=True, settings=env.settings)
    with SessionLocal() as s:
        r = service.send_daily_digest(s, str(data_dir), date(2026, 9, 1), env.transport, settings=env.settings)
    assert r["skipped_reason"] == "empty" and env.transport.sent == []


def test_advice_word_check_blocks_digest(env, data_dir, monkeypatch):
    active_subscriber("daily@example.com", daily=True, settings=env.settings)
    monkeypatch.setattr(digest_mod, "INTRO", "A great opportunity to buy small caps.")
    with SessionLocal() as s:
        r = service.send_daily_digest(s, str(data_dir), DAY, env.transport, settings=env.settings)
    assert r["skipped_reason"] == "flagged_words" and set(r["flagged_words"]) >= {"buy", "opportunity"}
    assert env.transport.sent == [] and count(EmailSend) == 0


def test_daily_digest_due_hour():
    s = enabled_settings(email_daily_digest_hour_et=18)
    assert service.daily_digest_day(utc(2026, 10, 19, 21, 59), s) is None      # 17:59 ET
    assert service.daily_digest_day(utc(2026, 10, 19, 22, 0), s) == date(2026, 10, 18)  # 18:00 ET: yesterday's day
    assert service.daily_digest_day(utc(2026, 10, 20, 3, 59), s) == date(2026, 10, 18)  # 23:59 ET
    assert service.daily_digest_day(utc(2026, 10, 20, 4, 0), s) is None        # 00:00 ET next day
    assert enabled_settings().email_daily_digest_hour_et == 7
    assert service.daily_digest_day(utc(2026, 10, 19, 10, 59), enabled_settings()) is None  # 06:59 ET
    assert service.daily_digest_day(utc(2026, 10, 19, 11, 0), enabled_settings()) == date(2026, 10, 18)
    with pytest.raises(ValueError):
        enabled_settings(email_daily_digest_hour_et=24)


def test_evening_filing_reaches_next_digest(env, data_dir):
    """Simulate the scheduler hourly over three days with a send hour of 18:00 ET: filings published after the send
    hour (Oct 7 23:30 ET and Oct 8 21:00 ET) must each reach exactly one digest, and each day is sent once."""
    env.settings = enabled_settings(email_daily_digest_hour_et=18)
    active_subscriber("daily@example.com", daily=True, settings=env.settings)
    with SessionLocal() as s:
        s.add(filing("TINY", "8-K", ["delisting_notice"], 3, utc(2026, 10, 9, 1)))  # Oct 8 21:00 ET, after the send hour
        s.commit()
        refs = []
        t = utc(2026, 10, 7, 4)  # Oct 7 00:00 ET
        while t < utc(2026, 10, 10, 4):
            day = service.daily_digest_day(t, env.settings)
            if day is not None:
                r = service.send_daily_digest(s, str(data_dir), day, env.transport, settings=env.settings)
                if r["sent"]:
                    refs.append(r["ref"])
            t += timedelta(hours=1)
    assert refs == ["2026-10-06", "2026-10-07", "2026-10-08"]  # sent at 18:00 ET on Oct 7, 8 and 9
    bodies = [text_part(m) for m in env.transport.sent]
    assert len(bodies) == 3
    assert "auditor" in bodies[1].lower() and "MIDL" in bodies[1]  # Oct 7 23:30 ET filing, in the Oct 8 send
    assert "TINY" in bodies[2]                                     # Oct 8 21:00 ET filing, in the Oct 9 send
    assert sum("MIDL" in b for b in bodies) == 1
