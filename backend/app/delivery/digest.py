"""Daily signal digest: one ET calendar day of small-cap signal filings with their historical Edge Lab stat.

Built only from our own DB (articles, companies, trading halts) and {data_dir}/event_study.json. Facts and
historical statistics only, no prices. Reuses the newsletter's selection and evidence helpers so the digest
and the weekly issue describe a filing identically (app.newsletter.service is read, never modified).
"""

import re
from datetime import date, datetime, time, timedelta, timezone
from urllib.parse import quote

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import TradingHalt
from app.newsletter import service as nl
from app.research.eventstudy import ET

TITLE = "Afterfile daily filing digest"
MIN_SEVERITY = 2
ITEM_LIMIT = 30
INTRO = ("Signal filings from nano-, micro- and small-cap companies filed with the SEC on this day (Eastern Time). "
         "Impersonal facts and historical statistics only; not investment advice.")
NO_EVIDENCE = "No historical Edge Lab statistic for this signal and size yet."


def day_window(day_et: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day_et, time(0), ET).astimezone(timezone.utc)
    end = datetime.combine(day_et + timedelta(days=1), time(0), ET).astimezone(timezone.utc)
    return start, end


def day_label(day_et: date) -> str:
    return f"{day_et:%a %b} {day_et.day}, {day_et.year}"


def build_daily_digest(session: Session, data_dir: str, day_et: date, *, public_base_url: str | None = None) -> dict:
    """Digest dict for `day_et`, with rendered `markdown`/`html` and `flagged_words` (empty when clean)."""
    base = (public_base_url or get_settings().public_base_url).rstrip("/")
    start, end = day_window(day_et)
    evidence = nl._evidence_index(nl._study(data_dir))
    items = [nl._filing_item(a, c, evidence) for a, c in nl._filings(session, start, end)]
    items = [i for i in items if (i["severity"] or 0) >= MIN_SEVERITY]
    items.sort(key=lambda i: i["filed_at"])
    items.sort(key=lambda i: -i["severity"])  # stable: severity 3 first, then oldest first
    for i in items:
        i.pop("public_float", None)  # facts about the filing only; no market figures in the digest
        i["ticker_url"] = f"{base}/ticker/{quote(i['ticker'])}"
        i["evidence_text"] = nl.evidence_text(i)
    serious = nl._halts(session, start, end)
    halts_total = session.scalar(
        select(func.count(TradingHalt.id)).where(TradingHalt.halted_at >= start, TradingHalt.halted_at < end)
    ) or 0
    digest = {
        "day": day_et.isoformat(),
        "title": TITLE,
        "base_url": base,
        "items": items[:ITEM_LIMIT],
        "items_total": len(items),
        "halts_total": halts_total,
        "serious_halts": len(serious),
        "links": {"edge_lab": f"{base}/lab", "methodology": f"{base}/methodology", "disclaimer": f"{base}/legal/disclaimer"},
    }
    digest["markdown"] = render_markdown(digest)
    digest["html"] = render_html(digest)
    digest["flagged_words"] = flagged_words(digest)
    return digest


def is_empty(digest: dict) -> bool:
    return not digest["items_total"] and not digest["halts_total"]


def subject(digest: dict) -> str:
    n = digest["items_total"]
    return f"{TITLE}: {day_label(date.fromisoformat(digest['day']))} ({n} signal filing{'s' if n != 1 else ''})"


def _halts_line(d: dict) -> str:
    return (f"Trading halts on this day: {d['halts_total']} in total, {d['serious_halts']} news-pending or regulatory "
            f"halts for small caps or companies of unknown size.")


def render_markdown(d: dict) -> str:
    L = d["links"]
    out = [f"# {d['title']}: {day_label(date.fromisoformat(d['day']))}", "", f"*{INTRO}*", ""]
    out += ["## Signal filings", ""]
    if not d["items"]:
        out += ["No high- or medium-severity signal filings from small caps on this day.", ""]
    for i in d["items"]:
        sigs = ", ".join(f"{nl.ARROW.get(s['direction'], '◆')} {s['label']}" for s in i["signals"])
        out.append(f"### [{i['ticker']}]({i['ticker_url']}) · {nl._md_escape(i['company'])}")
        out.append(f"{nl.SEV_WORD.get(i['severity'], '')} · {i['size']} cap · Form {i['form'] or 'n/a'} · "
                   f"filed {nl._et(i['filed_at'])} · [EDGAR filing]({i['url']})")
        out += ["", f"Signals: {sigs}", "", f"> {i['evidence_text'] or NO_EVIDENCE}", ""]
    if d["items_total"] > len(d["items"]):
        out += [f"*Plus {d['items_total'] - len(d['items'])} more signal filings.*", ""]
    out += ["## Trading halts", "", _halts_line(d), ""]
    out += ["---", "", f"Edge Lab statistics are historical and hypothetical, not predictions. "
            f"[Methodology]({L['methodology']}) · [Edge Lab]({L['edge_lab']}) · [Disclaimer]({L['disclaimer']})", ""]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip() + "\n"


def render_html(d: dict) -> str:
    """Email-safe HTML in the newsletter's style: one 640px table column, inline styles only."""
    L = d["links"]
    e, a, row, p = nl._e, nl._a, nl._row, nl._p
    rows = [
        row(f'<div style="font-size:12px;color:{nl.C_MUTED};text-transform:uppercase;letter-spacing:.05em;">Afterfile daily</div>'
            f'<h1 style="margin:4px 0 2px;font-size:22px;color:{nl.C_TEXT};">{e(d["title"])}</h1>'
            f'<div style="font-size:14px;color:{nl.C_MUTED};">{e(day_label(date.fromisoformat(d["day"])))}</div>', "24px 24px 12px"),
        row(p(e(INTRO), muted=True, size=12)),
        nl._h2("Signal filings"),
    ]
    if not d["items"]:
        rows.append(row(p("No high- or medium-severity signal filings from small caps on this day.", muted=True)))
    for i in d["items"]:
        sigs = " &nbsp; ".join(f"{nl._arrow(s['direction'])} {e(s['label'])}" for s in i["signals"])
        rows.append(row(
            f'<div style="font-size:15px;font-weight:700;">{a(i["ticker_url"], i["ticker"])} '
            f'<span style="font-weight:400;color:{nl.C_TEXT};">{e(i["company"])}</span></div>'
            f'<div style="font-size:12px;color:{nl.C_MUTED};margin:2px 0 4px;">{e(nl.SEV_WORD.get(i["severity"], ""))} · {e(i["size"])} cap · '
            f'Form {e(i["form"] or "n/a")} · filed {e(nl._et(i["filed_at"]))} · {a(i["url"], "EDGAR filing")}</div>'
            f'<div style="font-size:13px;">{sigs}</div>'
            f'<div style="font-size:12px;color:{nl.C_MUTED};margin-top:4px;padding-left:8px;border-left:3px solid {nl.C_BORDER};">'
            f'{e(i["evidence_text"] or NO_EVIDENCE)}</div>', "0 24px 14px"))
    if d["items_total"] > len(d["items"]):
        rows.append(row(p(f"Plus {d['items_total'] - len(d['items'])} more signal filings.", muted=True, size=12)))
    rows.append(nl._h2("Trading halts"))
    rows.append(row(p(e(_halts_line(d)), size=13)))
    links = " · ".join(a(L[k], t) for k, t in (("methodology", "Methodology"), ("edge_lab", "Edge Lab"), ("disclaimer", "Disclaimer")))
    rows.append(row(f'<div style="border-top:1px solid {nl.C_BORDER};padding-top:12px;font-size:13px;">'
                    f'Edge Lab statistics are historical and hypothetical, not predictions. {links}</div>', "8px 24px 24px"))
    return (
        '<!DOCTYPE html>\n<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{e(d['title'])}: {e(day_label(date.fromisoformat(d['day'])))}</title></head>\n"
        '<body style="margin:0;padding:0;background:#f4f5f7;">\n'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f4f5f7;">'
        '<tr><td align="center" style="padding:24px 8px;">\n'
        '<table role="presentation" width="640" cellpadding="0" cellspacing="0" border="0" '
        f'style="width:100%;max-width:640px;background:#ffffff;border:1px solid {nl.C_BORDER};border-radius:8px;">\n'
        + "\n".join(rows)
        + "\n</table>\n</td></tr></table>\n</body></html>\n"
    )


def flagged_words(d: dict) -> list[str]:
    """The newsletter's advice-word check on both renderings, with third-party names and tickers blanked."""
    scrubbed = {**d, "items": [{**i, "company": "X", "ticker": "X", "ticker_url": f"{d['base_url']}/ticker/X"} for i in d["items"]]}
    return sorted(set(nl.banned_words(render_markdown(scrubbed))) | set(nl.banned_words(render_html(scrubbed))))
