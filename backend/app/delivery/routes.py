"""Public subscription endpoints. main.py mounts them with `app.include_router(router)` (see AGENTS.md)."""

import html
from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from app.db import get_session as default_get_session
from app.delivery import service
from app.delivery.settings import DeliverySettings, get_delivery_settings
from app.delivery.transport import SmtpTransport, Transport

DISABLED_DETAIL = "Email delivery is not configured on this server"
# Token pages: never cached, never indexed, and the token never leaks through a Referer header.
PAGE_HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Robots-Tag": "noindex",
                "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'"}


class SubscribeIn(BaseModel):
    email: str
    daily: bool = False

    @field_validator("email")
    @classmethod
    def _valid(cls, v: str) -> str:
        addr = service.normalize_email(v)
        if addr is None:
            raise ValueError("Enter a valid email address")
        return addr


def _page(title: str, body_html: str, status_code: int = 200) -> HTMLResponse:
    doc = (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{html.escape(title)}</title></head>"
        '<body style="margin:0;padding:32px 16px;background:#f4f5f7;font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;color:#12161d;">'
        '<main style="max-width:520px;margin:0 auto;background:#fff;border:1px solid #dfe3ea;border-radius:8px;padding:24px;line-height:1.5;">'
        f'<h1 style="font-size:20px;margin:0 0 12px;">{html.escape(title)}</h1>{body_html}'
        f'<p style="font-size:12px;color:#5f6878;margin:16px 0 0;">{html.escape(service.DISCLAIMER)}</p>'
        "</main></body></html>"
    )
    return HTMLResponse(doc, status_code=status_code, headers=PAGE_HEADERS)


def make_router(
    get_session: Callable = default_get_session,
    get_settings: Callable[[], DeliverySettings] | None = None,
    make_transport: Callable[[DeliverySettings], Transport] | None = None,
) -> APIRouter:
    """Factory so tests (or main.py) can inject the session dependency, settings and transport."""
    router = APIRouter(prefix="/api", tags=["delivery"])

    def settings() -> DeliverySettings:
        return (get_settings or get_delivery_settings)()

    def transport_for(s: DeliverySettings) -> Transport:
        return (make_transport or SmtpTransport)(s)

    @router.post("/subscribe", status_code=202)
    def subscribe(body: SubscribeIn, session: Session = Depends(get_session)):
        s = settings()
        if not s.enabled:
            raise HTTPException(503, DISABLED_DETAIL)
        transport = transport_for(s)
        try:
            return service.subscribe(session, body.email, body.daily, transport, settings=s, source="web")
        except service.InvalidEmail:
            raise HTTPException(422, "Enter a valid email address")
        finally:
            close = getattr(transport, "close", None)
            if close:
                close()

    @router.get("/subscribe/confirm", response_class=HTMLResponse)
    def confirm(token: str = Query("", max_length=200), session: Session = Depends(get_session)):
        result = service.confirm(session, token)
        if result == "confirmed":
            return _page("Subscription confirmed", "<p>Thanks, you're subscribed. Every email has a one-click unsubscribe link.</p>")
        if result == "already":
            return _page("Already confirmed", "<p>This subscription is already active.</p>")
        if result == "expired":
            return _page("Link expired", "<p>This confirmation link has expired. Please subscribe again to get a new one.</p>", 410)
        return _page("Link not valid", "<p>This confirmation link is not valid. Please subscribe again.</p>", 404)

    @router.get("/unsubscribe", response_class=HTMLResponse)
    def unsubscribe_page(token: str = Query("", max_length=200)):
        # GET never unsubscribes (mail scanners prefetch links); the button POSTs, like the RFC 8058 one-click.
        action = f"?token={html.escape(token, quote=True)}"
        return _page("Unsubscribe", (
            "<p>Stop all Undertow emails to this address?</p>"
            f'<form method="post" action="{action}">'
            '<button type="submit" style="padding:10px 16px;background:#1d5fc0;color:#fff;border:0;border-radius:6px;font-size:14px;cursor:pointer;">'
            "Unsubscribe</button></form>"))

    @router.post("/unsubscribe", response_class=HTMLResponse)
    def unsubscribe(token: str = Query("", max_length=200), session: Session = Depends(get_session)):
        """RFC 8058 one-click target (body `List-Unsubscribe=One-Click` is accepted and ignored) and the page's button."""
        result = service.unsubscribe(session, token)
        if result == "invalid":
            return _page("Link not valid", "<p>This unsubscribe link is not valid.</p>", 404)
        return _page("Unsubscribed", "<p>You're unsubscribed and won't receive further emails from us.</p>")

    @router.post("/subscription/daily")
    def subscription_daily(token: str = Query("", max_length=200), on: bool = Query(...), session: Session = Depends(get_session)):
        value = service.set_daily(session, token, on)
        if value is None:
            raise HTTPException(404, "Subscription not found")
        return {"wants_daily": value}

    @router.get("/delivery/status")
    def delivery_status():
        return {"enabled": settings().enabled}

    return router


router = make_router()
