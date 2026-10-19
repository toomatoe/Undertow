"""Double-opt-in email list and idempotent fan-out of the weekly newsletter and the daily digest.

All functions are synchronous (SQLAlchemy session + blocking transport). Async callers (main.py scheduler)
run the send_* functions via asyncio.to_thread. Nothing is sent unless DeliverySettings.enabled.

Tokens:
- confirm token: random, emailed once in the confirm message, stored as SHA-256 only.
- manage token (unsubscribe / daily toggle): HMAC-SHA256(token key, "manage:" + email), so every message can
  carry a working link while the DB holds only its SHA-256. The key is EMAIL_TOKEN_SECRET or a random key
  created once at {DATA_DIR}/delivery/token_key.
"""

import base64
import hashlib
import hmac
import logging
import os
import re
import secrets
from datetime import date, datetime, timedelta, timezone
from email import policy as email_policy
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.delivery import digest as digest_mod
from app.delivery.settings import DeliverySettings, get_delivery_settings
from app.delivery.transport import SmtpTransport, Transport
from app.models import EmailSend, Subscriber
from app.newsletter import service as nl
from app.research.eventstudy import ET

log = logging.getLogger(__name__)

GENERIC_MESSAGE = ("Thanks. If this address can receive email from us, a confirmation link is on its way. "
                   "Nothing else is sent until you confirm.")
DISCLAIMER = "Research and education only, not financial advice. Historical statistics are not predictions."
CONFIRM_TTL_DAYS = 7
PENDING_PURGE_DAYS = 30
EMAIL_MAX_LEN = 254
# Simple, deliberately strict: local@domain.tld, no spaces, quotes, CR/LF or IP-literal domains.
EMAIL_RE = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}@"
    r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$"
)
KINDS = ("confirm", "newsletter", "daily_digest")
# Fold headers only past the SMTP line limit: the default 78 makes the stdlib RFC 2047-encode a long
# List-Unsubscribe URL, which mail clients then cannot use.
MAIL_POLICY = email_policy.default.clone(max_line_length=998)


class DeliveryDisabled(Exception):
    pass


class InvalidEmail(ValueError):
    pass


# --- helpers -----------------------------------------------------------------------


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def today_et(now: datetime | None = None) -> date:
    return (now or utcnow()).astimezone(ET).date()


def normalize_email(email: str | None) -> str | None:
    """Lowercased, stripped address, or None when it fails the regex / length limit."""
    if not isinstance(email, str):
        return None
    addr = email.strip().lower()
    if len(addr) > EMAIL_MAX_LEN or not EMAIL_RE.match(addr) or ".." in addr:
        return None
    return addr


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _token_key(s: DeliverySettings) -> bytes:
    if s.email_token_secret and s.email_token_secret.get_secret_value():
        return s.email_token_secret.get_secret_value().encode("utf-8")
    folder = os.path.join(get_settings().data_dir, "delivery")
    path = os.path.join(folder, "token_key")
    os.makedirs(folder, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        with open(path, encoding="utf-8") as f:
            return f.read().strip().encode("utf-8")
    key = secrets.token_hex(32)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(key)
    return key.encode("utf-8")


def manage_token(email: str, s: DeliverySettings) -> str:
    mac = hmac.new(_token_key(s), f"manage:{email}".encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).decode("ascii").rstrip("=")


def _ensure_manage(sub: Subscriber, s: DeliverySettings) -> str:
    """Raw manage token for this subscriber; re-syncs the stored hash if the token key changed."""
    raw = manage_token(sub.email, s)
    if sub.manage_token_hash != hash_token(raw):
        sub.manage_token_hash = hash_token(raw)
    return raw


def _by_token(session: Session, column, token: str | None) -> Subscriber | None:
    if not token or len(token) > 200:
        return None
    return session.scalar(select(Subscriber).where(column == hash_token(token)))


def unsubscribe_url(s: DeliverySettings, token: str) -> str:
    return f"{s.link_base}/api/unsubscribe?token={token}"


def confirm_url(s: DeliverySettings, token: str) -> str:
    return f"{s.link_base}/api/subscribe/confirm?token={token}"


# --- message building --------------------------------------------------------------


def _footer_text(s: DeliverySettings, unsub: str, reason: str) -> str:
    return "\n".join(["", "--", reason, f"Unsubscribe (one click): {unsub}", f"QuantDesk, {s.email_postal_address}", DISCLAIMER, ""])


def _footer_html(s: DeliverySettings, unsub: str, reason: str) -> str:
    e = nl._e
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f4f5f7;">'
        f'<tr><td align="center" style="padding:0 8px 24px;{nl.FONT}font-size:11px;line-height:1.5;color:{nl.C_MUTED};">'
        f'<div style="max-width:640px;">'
        f'<p style="margin:0 0 6px;">{e(reason)}</p>'
        f'<p style="margin:0 0 6px;"><a href="{e(unsub)}" style="color:{nl.C_LINK};text-decoration:underline;">Unsubscribe</a> (one click)</p>'
        f'<p style="margin:0 0 6px;">QuantDesk, {e(s.email_postal_address)}</p>'
        f'<p style="margin:0;">{e(DISCLAIMER)}</p>'
        "</div></td></tr></table>\n"
    )


def _with_footer(page: str, footer: str) -> str:
    i = page.lower().rfind("</body>")
    return page[:i] + footer + page[i:] if i >= 0 else page + footer


def build_message(s: DeliverySettings, to: str, subject: str, html_body: str, text_body: str, *,
                  manage: str, reason: str) -> EmailMessage:
    """Every outgoing message: plain-text + HTML parts, footer (reason, unsubscribe link, postal address,
    disclaimer) and RFC 8058 List-Unsubscribe / List-Unsubscribe-Post headers."""
    unsub = unsubscribe_url(s, manage)
    msg = EmailMessage(policy=MAIL_POLICY)
    msg["From"] = s.email_from
    msg["To"] = to
    msg["Subject"] = subject
    if s.email_reply_to:
        msg["Reply-To"] = s.email_reply_to
    msg["Date"] = formatdate(usegmt=True)
    domain = parseaddr(s.email_from or "")[1].rpartition("@")[2] or None
    msg["Message-ID"] = make_msgid(domain=domain)
    targets = [f"<{unsub}>"]
    if s.email_reply_to and (reply := parseaddr(s.email_reply_to)[1]):
        targets.append(f"<mailto:{reply}?subject=unsubscribe>")
    msg["List-Unsubscribe"] = ", ".join(targets)
    msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    msg.set_content(text_body.rstrip("\n") + "\n" + _footer_text(s, unsub, reason))
    msg.add_alternative(_with_footer(html_body, _footer_html(s, unsub, reason)), subtype="html")
    return msg


# --- subscription lifecycle --------------------------------------------------------


def _confirm_message(s: DeliverySettings, sub: Subscriber, raw_confirm: str) -> EmailMessage:
    link = confirm_url(s, raw_confirm)
    daily = " and the daily filing digest" if sub.wants_daily else ""
    text = (f"Please confirm your subscription to the QuantDesk weekly Small-Cap Filing Radar{daily}.\n\n"
            f"Confirm: {link}\n\nThe link is valid for {CONFIRM_TTL_DAYS} days. If you did not ask for this, ignore this email: "
            "nothing more will be sent.\n")
    e = nl._e
    page = (
        '<!DOCTYPE html>\n<html lang="en"><head><meta charset="utf-8"><title>Confirm your subscription</title></head>\n'
        f'<body style="margin:0;padding:24px 8px;background:#f4f5f7;{nl.FONT}color:{nl.C_TEXT};">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr><td align="center">'
        f'<div style="max-width:560px;background:#ffffff;border:1px solid {nl.C_BORDER};border-radius:8px;padding:24px;text-align:left;font-size:14px;line-height:1.5;">'
        f'<p style="margin:0 0 12px;">Please confirm your subscription to the QuantDesk weekly Small-Cap Filing Radar{e(daily)}.</p>'
        f'<p style="margin:0 0 12px;"><a href="{e(link)}" style="display:inline-block;padding:10px 16px;background:{nl.C_LINK};color:#ffffff;'
        'text-decoration:none;border-radius:6px;">Confirm subscription</a></p>'
        f'<p style="margin:0;color:{nl.C_MUTED};font-size:12px;">The link is valid for {CONFIRM_TTL_DAYS} days. If you did not ask for this, '
        "ignore this email: nothing more will be sent.</p>"
        "</div></td></tr></table>\n</body></html>\n"
    )
    reason = (f"You are receiving this one-time message because someone asked to subscribe this address at {s.site_base}. "
              "Without confirmation you will not hear from us again.")
    return build_message(s, sub.email, "Confirm your QuantDesk subscription", page, text,
                         manage=_ensure_manage(sub, s), reason=reason)


def _claim(session: Session, sub_id: int, kind: str, ref: str) -> EmailSend | None:
    """Claim the (subscriber, kind, ref) slot before sending. None if already sent / in flight."""
    row = session.scalar(select(EmailSend).where(EmailSend.subscriber_id == sub_id, EmailSend.kind == kind, EmailSend.ref == ref))
    if row is not None:
        if row.status != "failed":
            return None
        row.status, row.error, row.sent_at = "sending", None, utcnow()
    else:
        row = EmailSend(subscriber_id=sub_id, kind=kind, ref=ref, status="sending", sent_at=utcnow())
        session.add(row)
    try:
        session.commit()
    except IntegrityError:  # a concurrent run claimed it first
        session.rollback()
        return None
    return row


def _deliver(session: Session, row: EmailSend, transport: Transport, msg: EmailMessage) -> bool:
    try:
        transport.send(msg)
    except Exception as exc:  # SMTP / network errors become a failed row; retried on the next run
        row.status, row.error = "failed", f"{type(exc).__name__}: {exc}"[:300]
        log.warning("Email %s/%s to subscriber %s failed: %s", row.kind, row.ref, row.subscriber_id, type(exc).__name__)
        session.commit()
        return False
    row.status, row.error, row.sent_at = "sent", None, utcnow()
    session.commit()
    return True


def subscribe(session: Session, email: str, wants_daily: bool, transport: Transport, *,
              settings: DeliverySettings | None = None, source: str | None = None) -> dict:
    """Create or refresh a pending subscriber and send the confirm email.

    Always returns the same generic response (no address enumeration). An active address gets nothing; at most
    one confirm email per address per ET day (the EmailSend unique key), which also limits abuse.
    Raises DeliveryDisabled when not configured (nothing stored) and InvalidEmail for a bad address.
    """
    s = settings or get_delivery_settings()
    if not s.enabled:
        raise DeliveryDisabled()
    addr = normalize_email(email)
    if addr is None:
        raise InvalidEmail("Invalid email address")
    generic = {"message": GENERIC_MESSAGE}

    sub = session.scalar(select(Subscriber).where(Subscriber.email == addr))
    if sub is not None and sub.status == "active":
        return generic  # never let an anonymous request change an active subscriber's preferences
    if sub is None:
        sub = Subscriber(email=addr, status="pending", wants_daily=bool(wants_daily), created_at=utcnow(),
                         source=(source or None) and source[:32])
        _ensure_manage(sub, s)
        session.add(sub)
        try:
            session.commit()
        except IntegrityError:  # concurrent subscribe of the same address
            session.rollback()
            return generic
    else:
        if sub.status == "unsubscribed":
            sub.status, sub.confirmed_at = "pending", None
        sub.wants_daily = bool(wants_daily)
        session.commit()

    row = _claim(session, sub.id, "confirm", today_et().isoformat())
    if row is None:
        return generic  # a confirm email already went out today; its link still works
    raw = secrets.token_urlsafe(32)
    sub.confirm_token_hash = hash_token(raw)
    session.commit()
    _deliver(session, row, transport, _confirm_message(s, sub, raw))
    return generic


def confirm(session: Session, token: str | None, *, now: datetime | None = None) -> str:
    """'confirmed' | 'already' | 'expired' | 'invalid'. Idempotent."""
    sub = _by_token(session, Subscriber.confirm_token_hash, token)
    if sub is None or sub.status == "unsubscribed":
        return "invalid"
    if sub.status == "active":
        return "already"
    now = now or utcnow()
    last = session.scalar(
        select(func.max(EmailSend.sent_at)).where(EmailSend.subscriber_id == sub.id, EmailSend.kind == "confirm", EmailSend.status == "sent")
    )
    if last is None or now - _aware(last) > timedelta(days=CONFIRM_TTL_DAYS):
        return "expired"
    sub.status, sub.confirmed_at, sub.unsubscribed_at = "active", now, None
    session.commit()
    return "confirmed"


def unsubscribe(session: Session, token: str | None) -> str:
    """'unsubscribed' | 'already' | 'invalid'. Takes effect immediately; idempotent."""
    sub = _by_token(session, Subscriber.manage_token_hash, token)
    if sub is None:
        return "invalid"
    if sub.status == "unsubscribed":
        return "already"
    sub.status, sub.unsubscribed_at, sub.wants_daily, sub.confirm_token_hash = "unsubscribed", utcnow(), False, None
    session.commit()
    return "unsubscribed"


def set_daily(session: Session, token: str | None, on: bool) -> bool | None:
    """New wants_daily value, or None for an unknown token or an unsubscribed address."""
    sub = _by_token(session, Subscriber.manage_token_hash, token)
    if sub is None or sub.status == "unsubscribed":
        return None
    sub.wants_daily = bool(on)
    session.commit()
    return sub.wants_daily


def status(session: Session, settings: DeliverySettings | None = None) -> dict:
    s = settings or get_delivery_settings()
    counts = dict(session.execute(select(Subscriber.status, func.count(Subscriber.id)).group_by(Subscriber.status)).all())
    return {"enabled": s.enabled, "active": counts.get("active", 0), "pending": counts.get("pending", 0)}


def purge_pending(session: Session, *, now: datetime | None = None, days: int = PENDING_PURGE_DAYS) -> int:
    """Delete never-confirmed rows older than `days` (data minimisation). Returns the number deleted."""
    cutoff = (now or utcnow()) - timedelta(days=days)
    rows = [r for r in session.scalars(select(Subscriber).where(Subscriber.status == "pending")) if _aware(r.created_at) < cutoff]
    for r in rows:
        for send in session.scalars(select(EmailSend).where(EmailSend.subscriber_id == r.id)):
            session.delete(send)
        session.delete(r)
    session.commit()
    return len(rows)


# --- fan-out -----------------------------------------------------------------------


def _fan_out(session: Session, s: DeliverySettings, transport: Transport | None, kind: str, ref: str, where,
             subject: str, html_body: str, text_body: str, reason: str) -> dict:
    own = transport is None
    transport = transport or SmtpTransport(s)
    result = {"kind": kind, "ref": ref, "sent": 0, "failed": 0, "skipped": 0, "deferred": 0}
    try:
        done = set(session.scalars(select(EmailSend.subscriber_id).where(
            EmailSend.kind == kind, EmailSend.ref == ref, EmailSend.status.in_(["sent", "sending"]))))
        ids = session.scalars(select(Subscriber.id).where(*where).order_by(Subscriber.id)).all()
        for sid in ids:
            if sid in done:
                result["skipped"] += 1
                continue
            if result["sent"] + result["failed"] >= s.email_max_per_run:
                result["deferred"] += 1  # picked up by the next run (idempotent)
                continue
            sub = session.get(Subscriber, sid)
            session.refresh(sub)  # honour an unsubscribe that landed during this run
            if sub.status != "active" or (kind == "daily_digest" and not sub.wants_daily):
                continue
            row = _claim(session, sid, kind, ref)
            if row is None:
                result["skipped"] += 1
                continue
            msg = build_message(s, sub.email, subject, html_body, text_body, manage=_ensure_manage(sub, s), reason=reason)
            result["sent" if _deliver(session, row, transport, msg) else "failed"] += 1
    finally:
        if own:
            transport.close()
    log.info("Email %s %s: %s", kind, ref, result)
    return result


def send_newsletter(session: Session, data_dir: str, issue_id: str, transport: Transport | None = None, *,
                    settings: DeliverySettings | None = None) -> dict:
    """Email an archived newsletter issue to every active subscriber, once each."""
    s = settings or get_delivery_settings()
    if not s.enabled:
        return {"kind": "newsletter", "ref": issue_id, "skipped_reason": "disabled", "sent": 0}
    issue = nl.load_issue(data_dir, issue_id)
    page, md = nl.load_text(data_dir, issue_id, "html"), nl.load_text(data_dir, issue_id, "md")
    if not issue or not page or not md:
        log.error("Newsletter %s is not in the archive; nothing sent", issue_id)
        return {"kind": "newsletter", "ref": issue_id, "skipped_reason": "issue_not_found", "sent": 0}
    flagged = issue.get("flagged_words")
    if flagged is None:
        flagged = nl.flagged_words(issue)
    if flagged:
        log.error("Newsletter %s not emailed: advice-word check flagged %s", issue_id, flagged)
        return {"kind": "newsletter", "ref": issue_id, "skipped_reason": "flagged_words", "flagged_words": flagged, "sent": 0}
    reason = f"You are receiving this because you confirmed a subscription to the QuantDesk weekly newsletter at {s.site_base}."
    return _fan_out(session, s, transport, "newsletter", issue_id, [Subscriber.status == "active"],
                    f"{issue['title']}: {nl.week_label(issue)}", page, md, reason)


def send_daily_digest(session: Session, data_dir: str, day_et: date, transport: Transport | None = None, *,
                      settings: DeliverySettings | None = None) -> dict:
    """Email the digest for one ET day to active subscribers who opted into the daily digest, once each.
    Pass a finished day (see `daily_digest_day`): the digest covers the whole ET day [00:00, 24:00). Refuses to send if the advice-word check flags anything; skips days with no filings and no halts."""
    s = settings or get_delivery_settings()
    ref = day_et.isoformat()
    if not s.enabled:
        return {"kind": "daily_digest", "ref": ref, "skipped_reason": "disabled", "sent": 0}
    d = digest_mod.build_daily_digest(session, data_dir, day_et)
    if d["flagged_words"]:
        log.error("Daily digest %s not emailed: advice-word check flagged %s", ref, d["flagged_words"])
        return {"kind": "daily_digest", "ref": ref, "skipped_reason": "flagged_words", "flagged_words": d["flagged_words"], "sent": 0}
    if digest_mod.is_empty(d):
        return {"kind": "daily_digest", "ref": ref, "skipped_reason": "empty", "sent": 0}
    reason = f"You are receiving this because you opted into the QuantDesk daily filing digest at {s.site_base}."
    return _fan_out(session, s, transport, "daily_digest", ref,
                    [Subscriber.status == "active", Subscriber.wants_daily.is_(True)],
                    digest_mod.subject(d), d["html"], d["markdown"], reason)


def daily_digest_day(now: datetime | None = None, settings: DeliverySettings | None = None) -> date | None:
    """The ET date whose digest is due at `now`: YESTERDAY (ET) once today's ET hour >= EMAIL_DAILY_DIGEST_HOUR_ET,
    else None. A digest always covers one full, finished ET calendar day [00:00, 24:00), so consecutive digests tile
    time with no gap: a filing published late in the evening (EDGAR accepts until 22:00 ET) is in the digest sent the
    next day, never between windows."""
    s = settings or get_delivery_settings()
    local = (now or utcnow()).astimezone(ET)
    return local.date() - timedelta(days=1) if local.hour >= s.email_daily_digest_hour_et else None
