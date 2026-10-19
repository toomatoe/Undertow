"""Mail transports. Sends are blocking: async callers wrap fan-out calls in asyncio.to_thread."""

import smtplib
import ssl
from email.message import EmailMessage
from typing import Protocol

from app.delivery.settings import DeliverySettings


class Transport(Protocol):
    def send(self, msg: EmailMessage) -> None: ...


class SmtpTransport:
    """smtplib over STARTTLS (or implicit TLS on port 465) with a timeout.

    The connection is opened lazily and reused across send() calls until close(), so one fan-out run uses
    one SMTP session. Usable as a context manager.
    """

    def __init__(self, settings: DeliverySettings):
        self.s = settings
        self._conn: smtplib.SMTP | None = None

    def _connect(self) -> smtplib.SMTP:
        s = self.s
        if not s.smtp_host:
            raise RuntimeError("SMTP_HOST is not set")
        ctx = ssl.create_default_context()
        if s.smtp_port == 465:
            conn: smtplib.SMTP = smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=s.smtp_timeout_seconds, context=ctx)
        else:
            conn = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=s.smtp_timeout_seconds)
            if s.smtp_starttls:
                conn.starttls(context=ctx)
        if s.smtp_username and s.smtp_password:
            conn.login(s.smtp_username, s.smtp_password.get_secret_value())
        return conn

    def send(self, msg: EmailMessage) -> None:
        if self._conn is None:
            self._conn = self._connect()
        try:
            self._conn.send_message(msg)
        except smtplib.SMTPServerDisconnected:  # idle timeout between sends: reconnect once
            self._conn = self._connect()
            self._conn.send_message(msg)

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.quit()
            except smtplib.SMTPException:
                pass
            except OSError:
                pass
            self._conn = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class FakeTransport:
    """Records messages instead of sending them (tests). `fail_for` addresses raise, to test failure rows."""

    def __init__(self, fail_for: set[str] | None = None):
        self.sent: list[EmailMessage] = []
        self.fail_for = {e.lower() for e in (fail_for or set())}

    def send(self, msg: EmailMessage) -> None:
        if str(msg["To"]).lower() in self.fail_for:
            raise smtplib.SMTPRecipientsRefused({str(msg["To"]): (550, b"rejected")})
        self.sent.append(msg)

    def close(self) -> None:
        pass
