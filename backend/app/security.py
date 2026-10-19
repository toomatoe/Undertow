"""Platform security: one admin policy for every mutating endpoint, and a per-client rate limiter.

Admin policy (`admin_policy`, `admin_dependency`):
- A configured ADMIN_TOKEN (or the older RESEARCH_ADMIN_TOKEN) always wins: the request needs
  `Authorization: Bearer <token>`, compared in constant time (hmac.compare_digest). Missing/wrong -> 401.
- Without a token: the explicit env flag decides (RESEARCH_JOBS_ENABLED for research launches, falling back to
  MUTATIONS_ENABLED; MUTATIONS_ENABLED for everything else). Disabled -> 403.
- Without a token or flag: allowed only when PUBLIC_BASE_URL is a local origin (localhost, 127.0.0.1, ::1,
  *.localhost), so a public deployment is closed by default.

Rate limiter (`RateLimiter`, `RateLimitMiddleware`): in-memory sliding window per client key, two tiers
(all requests; writes). Over the limit -> 429 with Retry-After and a JSON detail. /api/stream (SSE) and
/api/health are exempt, as are CORS preflights. Memory is bounded: idle keys are evicted and the key table has a cap.
The state is per process; the API runs one worker.
"""

import hmac
import ipaddress
import json
import math
import time
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlsplit

from fastapi import HTTPException, Request

from app.config import AdminSettings

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}

# (403 when disabled, 401 when the token is missing or wrong). The research texts predate this module; keep them.
MESSAGES = {
    "research": (
        "Research runs are disabled on this server. Run them from the command line, "
        "or set RESEARCH_ADMIN_TOKEN to allow authorized launches.",
        "A valid admin token is required to start research runs.",
    ),
    "mutations": (
        "Changes are disabled on this server. The operator can set ADMIN_TOKEN to allow authorized changes.",
        "Admin token required: a valid admin token is needed for this action.",
    ),
}


def is_local_origin(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return host in LOCAL_HOSTS or host.endswith(".localhost")


@dataclass(frozen=True)
class AdminPolicy:
    enabled: bool
    token: str | None  # never returned by the API

    @property
    def protected(self) -> bool:
        return self.token is not None


def admin_policy(cfg: AdminSettings, public_base_url: str, scope: str = "mutations") -> AdminPolicy:
    """A token always wins; otherwise the scope's env flag; otherwise only local deployments are open."""
    token = cfg.admin_token.get_secret_value().strip() if cfg.admin_token is not None else ""
    if token:
        return AdminPolicy(True, token)
    flag = cfg.mutations_enabled
    if scope == "research" and cfg.research_jobs_enabled is not None:
        flag = cfg.research_jobs_enabled
    if flag is not None:
        return AdminPolicy(flag, None)
    return AdminPolicy(is_local_origin(public_base_url), None)


def bearer_matches(authorization: str, token: str) -> bool:
    scheme, _, supplied = authorization.partition(" ")
    return scheme.lower() == "bearer" and hmac.compare_digest(supplied.strip().encode(), token.encode())


def check_admin(request: Request, policy: AdminPolicy, scope: str) -> None:
    disabled, unauthorized = MESSAGES.get(scope, MESSAGES["mutations"])
    if not policy.enabled:
        raise HTTPException(403, disabled)
    if policy.token is None:
        return
    if not bearer_matches(request.headers.get("authorization", ""), policy.token):
        raise HTTPException(401, unauthorized, headers={"WWW-Authenticate": "Bearer"})


def admin_dependency(get_policy: Callable[[str], AdminPolicy]) -> Callable[[str], Callable[[Request], None]]:
    """Build `require_admin(scope)`. `get_policy(scope)` is looked up per request, so tests can swap settings."""

    def require_admin(scope: str = "mutations") -> Callable[[Request], None]:
        def dependency(request: Request) -> None:
            check_admin(request, get_policy(scope), scope)

        dependency.__name__ = f"require_admin_{scope}"
        return dependency

    return require_admin


# --- Rate limiting -----------------------------------------------------------------------------

EXEMPT_PATHS = frozenset({"/api/stream", "/api/health"})
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
# Covered by WRITE_METHODS already; listed so the write tier for these public POSTs is explicit.
WRITE_PATHS = frozenset({"/api/newsletter/preview", "/api/subscribe"})
# Starlette's TestClient peer. A real socket peer is an IP address, so no real client can use this key.
EXEMPT_CLIENTS = frozenset({"testclient"})
MAX_KEY_LENGTH = 64


class SlidingWindow:
    """Sliding-window log per key: at most `limit` hits in any `window` seconds.

    Memory: each key keeps at most `limit` timestamps; keys idle for a whole window are evicted, and the table
    never holds more than `max_keys` keys (least recently seen dropped first).
    """

    def __init__(self, limit: int, window: float = 60.0, max_keys: int = 10_000, clock: Callable[[], float] = time.monotonic):
        self.limit, self.window, self.max_keys, self.clock = limit, window, max_keys, clock
        self.hits: OrderedDict[str, deque[float]] = OrderedDict()

    def _evict_idle(self, now: float) -> None:
        # Ordered by last hit, so idle keys are at the front.
        while self.hits:
            key, q = next(iter(self.hits.items()))
            if q and q[-1] > now - self.window:
                break
            self.hits.popitem(last=False)

    def retry_after(self, key: str, now: float) -> float | None:
        """Seconds until `key` may make another request, or None if it may now. Records nothing."""
        if self.limit <= 0:
            return None
        q = self.hits.get(key)
        if not q:
            return None
        while q and q[0] <= now - self.window:
            q.popleft()
        if len(q) < self.limit:
            return None
        return max(q[0] + self.window - now, 0.001)

    def record(self, key: str, now: float) -> None:
        if self.limit <= 0:
            return
        self._evict_idle(now)
        q = self.hits.pop(key, None) or deque()
        q.append(now)
        while len(q) > self.limit:
            q.popleft()
        self.hits[key] = q
        while len(self.hits) > self.max_keys:
            self.hits.popitem(last=False)


class RateLimiter:
    """Two tiers per client key: every request (`per_minute`) and writes (`write_per_minute`). 0 disables a tier."""

    def __init__(self, per_minute: int, write_per_minute: int, *, trust_proxy: bool = False,
                 clock: Callable[[], float] = time.monotonic, max_keys: int = 10_000, window: float = 60.0):
        self.trust_proxy = trust_proxy
        self.clock = clock
        self.all = SlidingWindow(per_minute, window, max_keys, clock)
        self.write = SlidingWindow(write_per_minute, window, max_keys, clock)

    def check(self, key: str, is_write: bool) -> float | None:
        """Record a request; return seconds to wait if it is over a limit (a rejected request is not counted)."""
        now = self.clock()
        tiers = [self.all, self.write] if is_write else [self.all]
        waits = [w for w in (t.retry_after(key, now) for t in tiers) if w is not None]
        if waits:
            return max(waits)
        for t in tiers:
            t.record(key, now)
        return None

    def key_count(self) -> int:
        return max(len(self.all.hits), len(self.write.hits))


# Where our own reverse proxies live (Docker networks, LAN, loopback). Deliberately not ipaddress.is_private,
# which also covers documentation and other special ranges.
TRUSTED_PROXY_NETS = tuple(ipaddress.ip_network(n) for n in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8", "::1/128", "fc00::/7",
))


def _is_trusted_hop(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return any(ip in net for net in TRUSTED_PROXY_NETS)


def client_key(scope: dict, trust_proxy: bool) -> str | None:
    """Client identity for rate limiting, or None when the request is exempt (test client).

    The peer address is used unless `trust_proxy` is on AND the peer itself is in TRUSTED_PROXY_NETS. Then the
    X-Forwarded-For chain is read right to left and the first hop outside TRUSTED_PROXY_NETS (the
    client as seen by our own proxies) is used. Left-hand entries are client-supplied and never trusted.
    """
    client = scope.get("client")
    peer = client[0] if client else "unknown"
    if peer in EXEMPT_CLIENTS:
        return None
    if trust_proxy and _is_trusted_hop(peer):
        values = [v.decode("latin-1") for k, v in scope.get("headers", []) if k.lower() == b"x-forwarded-for"]
        hops = [h.strip() for h in ",".join(values).split(",") if h.strip()]
        for hop in reversed(hops):
            if not _is_trusted_hop(hop):
                return hop[:MAX_KEY_LENGTH]
        if hops:
            return hops[0][:MAX_KEY_LENGTH]
    return peer[:MAX_KEY_LENGTH]


class RateLimitMiddleware:
    """Pure ASGI middleware (does not buffer streaming responses). `get_limiter()` is called per request so the
    app (or a test) can swap the limiter; returning None disables limiting."""

    def __init__(self, app, get_limiter: Callable[[], RateLimiter | None]):
        self.app = app
        self.get_limiter = get_limiter

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        limiter = self.get_limiter()
        method, path = scope.get("method", "GET"), scope.get("path", "")
        if limiter is None or method == "OPTIONS" or path in EXEMPT_PATHS:
            return await self.app(scope, receive, send)
        key = client_key(scope, limiter.trust_proxy)
        if key is None:
            return await self.app(scope, receive, send)
        wait = limiter.check(key, method in WRITE_METHODS or (method == "POST" and path in WRITE_PATHS))
        if wait is None:
            return await self.app(scope, receive, send)
        seconds = max(1, math.ceil(wait))
        body = json.dumps({"detail": f"Too many requests. Try again in {seconds} seconds."}).encode()
        await send({"type": "http.response.start", "status": 429, "headers": [
            (b"content-type", b"application/json"), (b"retry-after", str(seconds).encode()),
            (b"content-length", str(len(body)).encode()),
        ]})
        await send({"type": "http.response.body", "body": body})
