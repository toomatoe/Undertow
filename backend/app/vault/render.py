"""Pure text helpers for vault notes (no I/O, no DB)."""

from __future__ import annotations

import re

from app.pipeline.signals import signal_def

EXCERPT_CHARS = 500
EVIDENCE_LABEL = "Historical event-study result (hypothetical, not a forecast)"
EVIDENCE_KEYS = (
    "bucket", "horizon_days", "n", "mean_abnormal", "excess_vs_baseline", "t_stat", "t_stat_clustered", "significant", "net",
)

_ACC_DASHED = re.compile(r"(\d{10}-\d{2}-\d{6})")
_ACC_PLAIN = re.compile(r"/(\d{18})(?:/|$)")
_ITEMS = re.compile(r"\(items ([^)]*)\)")
_WS = re.compile(r"\s+")


def accession_from_url(url: str | None) -> str | None:
    """EDGAR accession number (0001234567-26-000123) from a filing URL, dashed or as the 18-digit folder."""
    if not url:
        return None
    if m := _ACC_DASHED.search(url):
        return m.group(1)
    if m := _ACC_PLAIN.search(url):
        d = m.group(1)
        return f"{d[:10]}-{d[10:12]}-{d[12:]}"
    return None


def items_from_title(title: str | None) -> list[str]:
    m = _ITEMS.search(title or "")
    return [x.strip() for x in m.group(1).split(",") if x.strip()] if m else []


def signal_label(code: str) -> str:
    sig = signal_def(code)
    return sig.label if sig else code


def signal_direction(code: str) -> str | None:
    sig = signal_def(code)
    return sig.direction if sig else None


def clean_third_party(text: str | None, limit: int = EXCERPT_CHARS) -> str:
    """Whitespace-collapsed excerpt of filing/summary text, at most `limit` chars, with no HTML comment markers."""
    s = _WS.sub(" ", (text or "").replace("<!--", "").replace("-->", "")).strip()
    if len(s) <= limit:
        return s
    cut = s[:limit].rsplit(" ", 1)[0].rstrip(" ,;:")
    return cut + "…"


def cell(text) -> str:
    """Safe Markdown table cell."""
    return _WS.sub(" ", str(text if text is not None else "n/a")).replace("|", "\\|").strip() or "n/a"


def pct(x: float | None, signed: bool = True) -> str:
    if x is None:
        return "n/a"
    return f"{x * 100:+.1f}%" if signed else f"{x * 100:.1f}%"


def money(v: float | int | None) -> str:
    if v is None:
        return "n/a"
    sign = "-" if v < 0 else ""
    a = abs(float(v))
    for div, suf in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= div:
            return f"{sign}${a / div:.1f}{suf}"
    return f"{sign}${a:.0f}"


def _num(v, cast):
    if v is None:
        return None
    try:
        return cast(v)
    except (TypeError, ValueError):
        return None


def normalize_evidence(ev, bucket: str | None) -> dict | None:
    """Evidence row (dict or pydantic model) -> dict with exactly EVIDENCE_KEYS (missing values None)."""
    if ev is None:
        return None
    if hasattr(ev, "model_dump"):
        ev = ev.model_dump()
    if not isinstance(ev, dict):
        return None
    out = {
        "bucket": ev.get("bucket") or bucket,
        "horizon_days": _num(ev.get("horizon_days"), int),
        "n": _num(ev.get("n"), int),
        "mean_abnormal": _num(ev.get("mean_abnormal"), float),
        "excess_vs_baseline": _num(ev.get("excess_vs_baseline"), float),
        "t_stat": _num(ev.get("t_stat"), float),
        "t_stat_clustered": _num(ev.get("t_stat_clustered"), float),
        "significant": bool(ev["significant"]) if ev.get("significant") is not None else None,
        "net": _num(ev.get("net", ev.get("mean_net")), float),
    }
    return out


def evidence_sentence(code: str, ev: dict | None) -> str:
    """One labelled sentence about the historical evidence for a signal in a size bucket."""
    label = signal_label(code)
    if not ev or ev.get("mean_abnormal") is None:
        return f"{EVIDENCE_LABEL}: none available for {label} in this size bucket."
    parts = [f"n={ev['n']}" if ev.get("n") is not None else None,
             f"t={ev['t_stat']:.2f}" if ev.get("t_stat") is not None else None,
             f"firm-clustered t={ev['t_stat_clustered']:.2f}" if ev.get("t_stat_clustered") is not None else None]
    stats = ", ".join(p for p in parts if p)
    sig = ev.get("significant")
    sig_txt = ("significant after multiple-testing correction" if sig else
               "not significant after multiple-testing correction" if sig is not None else "significance not reported")
    text = (f"{EVIDENCE_LABEL}: after past {label} filings by {ev.get('bucket') or 'n/a'} companies, the mean abnormal "
            f"return over {ev.get('horizon_days') or 'n/a'} trading days was {pct(ev['mean_abnormal'])} vs the benchmark "
            f"({stats}; {sig_txt}).")
    if ev.get("excess_vs_baseline") is not None:
        text += f" Versus the same stocks' ordinary days: {pct(ev['excess_vs_baseline'])}."
    if ev.get("net") is not None:
        text += f" After assumed costs, in the signal's expected direction: {pct(ev['net'])}."
    return text
