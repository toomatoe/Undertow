import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_TRACKING_PARAMS = re.compile(r"^(utm_|mc_|fbclid$|gclid$|cmpid$|mod$|.rss$|yptr$|ncid$)", re.I)


def canonical_url(url: str) -> str:
    """Normalize a URL so the same story from different feeds hashes the same."""
    parts = urlsplit(url.strip())
    query = [(k, v) for k, v in parse_qsl(parts.query) if not _TRACKING_PARAMS.match(k)]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower() or "https", parts.netloc.lower(), path, urlencode(sorted(query)), ""))


def url_hash(url: str) -> str:
    return hashlib.sha1(canonical_url(url).encode()).hexdigest()


def title_hash(title: str) -> str:
    """Hash of the headline's words, ignoring case/punctuation. Catches syndicated copies."""
    words = re.findall(r"[a-z0-9]+", title.lower())
    return hashlib.sha1(" ".join(words).encode()).hexdigest()
