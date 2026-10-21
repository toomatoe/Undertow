"""Read a human's thesis notes back from the vault (read-only).

A note counts as a thesis when its frontmatter has `type: thesis` or its `tags` contain `undertow/thesis`
(string or list, with or without '#'). The walk skips Undertow/ (machine output), .obsidian/, .git/, .trash/ and
every other dot-dir, does not follow symlinks, skips files over 1 MB and stops after 5000 files. Frontmatter is
parsed with safe parsing only; nothing in a note is ever executed. A note with malformed frontmatter is skipped.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import date, datetime, timezone

from app.vault import frontmatter as fm
from app.vault.fs import ROOT_NAME

log = logging.getLogger(__name__)

MAX_BYTES = 1_000_000
MAX_FILES = 5000
EXCERPT_CHARS = 600
THESIS_TAG = "undertow/thesis"
SKIP_DIRS = {ROOT_NAME, ".obsidian", ".git", ".trash"}
_WS = re.compile(r"\s+")
_LINK = re.compile(r"^\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]$")


def _tags(value) -> list[str]:
    if value is None:
        return []
    items = value if isinstance(value, list) else re.split(r"[,\s]+", str(value))
    return [str(t).strip().lstrip("#") for t in items if t is not None and str(t).strip().lstrip("#")]


def _tickers(value) -> list[str]:
    items = value if isinstance(value, list) else [value]
    out = []
    for v in items:
        if v is None:
            continue
        if isinstance(v, list):  # YAML reads an unquoted [[ABCD]] as a nested list
            out += _tickers(v)
            continue
        s = str(v).strip()
        if m := _LINK.match(s):
            s = m.group(1).rsplit("/", 1)[-1]
        s = s.strip().lstrip("$").upper()
        if s:
            out.append(s)
    return out


def _iso(v) -> str | None:
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _title(meta: dict, body: str, stem: str) -> str:
    if meta.get("title"):
        return str(meta["title"]).strip()
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return stem


def read_theses(vault_dir: str, ticker: str | None = None, limit: int = 50) -> list[dict]:
    """Thesis notes outside Undertow/, newest `updated` first: [{title, path, ticker, updated, tags, excerpt}]."""
    root = os.path.realpath(os.path.abspath(vault_dir))
    if not os.path.isdir(root):
        return []
    want = (_tickers([ticker]) or [None])[0] if ticker else None
    out: list[dict] = []
    seen = 0
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        rel_dir = os.path.relpath(dirpath, root)
        dirnames[:] = sorted(
            d for d in dirnames
            if not d.startswith(".") and d not in SKIP_DIRS - {ROOT_NAME}
            and not (rel_dir == "." and d == ROOT_NAME)
            and not os.path.islink(os.path.join(dirpath, d))
        )
        for name in sorted(filenames):
            seen += 1
            if seen > MAX_FILES:
                log.warning("Vault read-back stopped after %d files", MAX_FILES)
                break
            if not name.lower().endswith(".md") or name.startswith("."):
                continue
            path = os.path.join(dirpath, name)
            try:
                if os.path.islink(path) or not os.path.isfile(path) or os.path.getsize(path) > MAX_BYTES:
                    continue
                with open(path, "rb") as f:
                    text = f.read().decode("utf-8", errors="replace")
                meta, body = fm.read(text)
            except (OSError, fm.FrontmatterError) as exc:
                log.info("Vault read-back skipped %s: %s", name, exc)
                continue
            if not meta:
                continue
            tags = _tags(meta.get("tags"))
            if str(meta.get("type") or "").strip().lower() != "thesis" and THESIS_TAG not in [t.lower() for t in tags]:
                continue
            tickers = _tickers(meta.get("ticker") if meta.get("ticker") is not None else meta.get("tickers"))
            if want and want not in tickers:
                continue
            updated = _iso(meta.get("updated")) or _iso(meta.get("date"))
            if not updated:
                updated = datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc).date().isoformat()
            excerpt = _WS.sub(" ", body).strip()
            if len(excerpt) > EXCERPT_CHARS:
                excerpt = excerpt[:EXCERPT_CHARS].rsplit(" ", 1)[0] + "…"
            out.append({
                "title": _title(meta, body, os.path.splitext(name)[0]),
                "path": os.path.relpath(path, root).replace(os.sep, "/"),
                "ticker": want if want else (tickers[0] if tickers else None),
                "updated": updated,
                "tags": tags,
                "excerpt": excerpt,
            })
        if seen > MAX_FILES:
            break
    out.sort(key=lambda d: (d["updated"] or "", d["path"]), reverse=True)
    return out[: max(0, int(limit))]
