"""YAML frontmatter: a small deterministic EMITTER plus safe PARSING.

Emitting is done here by hand (never yaml.dump) so a note's bytes depend only on its values: keys in the order
given, strings always double-quoted (JSON escaping is valid YAML), ISO dates unquoted, floats in plain decimal
notation, lists as block lists. Parsing uses `yaml.safe_load` when PyYAML is importable (it is, via
uvicorn[standard]) and otherwise a minimal parser for the subset this module emits plus the usual hand-written
`key: value`, `key: [a, b]` and `- item` forms. Nothing here ever executes note content.

Frontmatter is also handled as raw *chunks* (one top-level key with its continuation lines), so a writer can
copy a human's keys, or a journal note's sealed keys, byte for byte.
"""

from __future__ import annotations

import json
import math
import re
from datetime import date, datetime, timezone

try:  # PyYAML is installed transitively (uvicorn[standard]); the package must not hard-depend on it
    import yaml as _yaml
except Exception:  # pragma: no cover - exercised only in images without PyYAML
    _yaml = None

FENCE = "---"
_KEY_LINE = re.compile(r"^([A-Za-z0-9_][A-Za-z0-9_\-]*)\s*:(.*)$")


class FrontmatterError(ValueError):
    """Frontmatter present but not parseable."""


# --- emitting --------------------------------------------------------------------------------------------------


def iso_utc(dt: datetime) -> str:
    """UTC timestamp `YYYY-MM-DDTHH:MM:SSZ` (naive values are treated as UTC; microseconds dropped)."""
    dt = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def quote(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


def _float(x: float) -> str:
    if math.isnan(x) or math.isinf(x):
        return "null"
    s = repr(round(x, 10))
    if "e" in s or "E" in s:  # YAML 1.1 (PyYAML) reads 1e-05 as a string: always write plain decimals
        s = format(x, ".12f").rstrip("0")
        if s.endswith("."):
            s += "0"
    return s


def scalar(v) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return _float(v)
    if isinstance(v, datetime):
        return iso_utc(v)
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, str):
        return quote(v)
    raise TypeError(f"unsupported frontmatter value {type(v).__name__}")


def emit_key(key: str, value) -> str:
    """One top-level key as text (ends with a newline)."""
    if not _KEY_LINE.match(f"{key}:"):
        raise ValueError(f"bad frontmatter key {key!r}")
    if isinstance(value, (list, tuple)):
        if not value:
            return f"{key}: []\n"
        return f"{key}:\n" + "".join(f"  - {scalar(x)}\n" for x in value)
    return f"{key}: {scalar(value)}\n"


def emit(fields: list[tuple[str, object]] | dict) -> str:
    """Frontmatter block including both `---` fences, in the given key order."""
    items = fields.items() if isinstance(fields, dict) else fields
    return FENCE + "\n" + "".join(emit_key(k, v) for k, v in items) + FENCE + "\n"


def wikilink(target: str) -> str:
    return f"[[{target}]]"


# --- splitting ---------------------------------------------------------------------------------------------------


def split(text: str) -> tuple[str | None, str]:
    """(frontmatter text without fences, body). (None, text) when the note has no frontmatter."""
    if not text.startswith(FENCE + "\n") and not text.startswith(FENCE + "\r\n"):
        return None, text
    lines = text.splitlines(keepends=True)
    for i in range(1, len(lines)):
        if lines[i].rstrip("\r\n") == FENCE:
            return "".join(lines[1:i]), "".join(lines[i + 1:])
    return None, text  # an opening fence without a closing one: treat the whole thing as body


def chunks(fm_text: str) -> list[tuple[str | None, str]]:
    """Raw top-level chunks [(key, text)], in file order. Leading comment/blank lines get key None."""
    out: list[tuple[str | None, str]] = []
    for line in fm_text.splitlines(keepends=True):
        m = _KEY_LINE.match(line) if line[:1] not in (" ", "\t", "-", "#") else None
        if m:
            out.append((m.group(1), line))
        elif out:
            out[-1] = (out[-1][0], out[-1][1] + line)
        else:
            out.append((None, line))
    return out


# --- parsing -----------------------------------------------------------------------------------------------------


def _mini_scalar(s: str):
    s = s.strip()
    if s == "" or s in ("null", "~", "Null", "NULL"):
        return None
    if s in ("true", "True", "TRUE"):
        return True
    if s in ("false", "False", "FALSE"):
        return False
    if s.startswith('"') and s.endswith('"') and len(s) >= 2:
        try:
            return json.loads(s)
        except ValueError:
            return s[1:-1]
    if s.startswith("'") and s.endswith("'") and len(s) >= 2:
        return s[1:-1].replace("''", "'")
    if re.fullmatch(r"-?\d+", s):
        return int(s)
    if re.fullmatch(r"-?\d+\.\d*", s):
        return float(s)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        try:
            return date.fromisoformat(s)
        except ValueError:
            return s
    return s


def _mini_parse(fm_text: str) -> dict:
    """Minimal fallback: `key: scalar`, `key: [a, b]`, `key:` followed by `- item` lines."""
    data: dict = {}
    current: str | None = None
    for raw in fm_text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        stripped = raw.strip()
        if stripped.startswith("- ") or stripped == "-":
            if current is None or not isinstance(data.get(current), list):
                raise FrontmatterError("list item without a key")
            data[current].append(_mini_scalar(stripped[1:]))
            continue
        m = _KEY_LINE.match(raw)
        if not m:
            raise FrontmatterError(f"unparseable line {raw!r}")
        key, rest = m.group(1), m.group(2).strip()
        current = key
        if rest == "":
            data[key] = []
        elif rest.startswith("[") and rest.endswith("]"):
            inner = rest[1:-1].strip()
            data[key] = [_mini_scalar(x) for x in inner.split(",")] if inner else []
        else:
            data[key] = _mini_scalar(rest)
    return data


def parse(fm_text: str) -> dict:
    """Frontmatter text -> dict, safely (never constructs arbitrary objects). Raises FrontmatterError."""
    if _yaml is not None:
        try:
            data = _yaml.safe_load(fm_text)
        except Exception as exc:  # yaml.YAMLError and friends
            raise FrontmatterError(str(exc)) from exc
    else:
        data = _mini_parse(fm_text)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise FrontmatterError("frontmatter is not a mapping")
    return data


def read(text: str) -> tuple[dict | None, str]:
    """(frontmatter dict or None when absent, body). Raises FrontmatterError when present but malformed."""
    fm_text, body = split(text)
    if fm_text is None:
        return None, body
    return parse(fm_text), body
