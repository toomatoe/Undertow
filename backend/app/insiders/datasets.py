"""SEC Insider Transactions Data Sets: download (cached) and load with the csv module.

Each quarterly zip ({year}q{q}_form345.zip, https://www.sec.gov/dera/data/form-345) holds flattened
Form 3/4/5 tables as tab-separated files. We use three, joined on ACCESSION_NUMBER:

- SUBMISSION: one row per filing (FILING_DATE, DOCUMENT_TYPE, ISSUERCIK, ISSUERTRADINGSYMBOL, and
  AFF10B5ONE on newer quarters);
- REPORTINGOWNER: one row per reporting owner (RPTOWNERCIK, RPTOWNER_RELATIONSHIP, RPTOWNER_TITLE);
- NONDERIV_TRANS: one row per non-derivative transaction (TRANS_DATE, TRANS_CODE, TRANS_SHARES,
  TRANS_PRICEPERSHARE, TRANS_ACQUIRED_DISP_CD, ...).

Column names are checked against REQUIRED_COLUMNS (taken from the SEC readme for the data sets) every
time a file is read; a missing column raises SchemaError naming the table and columns, so a format change
fails loudly instead of silently producing wrong rows. No pandas: SUBMISSION and REPORTINGOWNER are held
in dicts keyed by accession, NONDERIV_TRANS is streamed.

offline=True never touches the network: a quarter that is not cached is recorded with
snapshot.record_miss and download_quarter returns None.
"""

import csv
import io
import logging
import os
import sys
import time
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable, Iterator

import httpx

from app.insiders.form4 import plausible_price
from app.research import snapshot

log = logging.getLogger("insiders.datasets")

DATASET_URL = "https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/{year}q{q}_form345.zip"
# SEC moved newer quarters (2026q2 onward, as of Oct 2026) to a different folder; older ones stay put.
# Same files, same format: only the location differs, so trying both doesn't change the study design.
DATASET_URLS = (
    DATASET_URL,
    "https://www.sec.gov/files/datastandardsinnovation/data/insider-transactions-data-sets/{year}q{q}_form345.zip",
)
CACHE_SUBDIR = "insider_datasets"
MIN_INTERVAL = 0.125  # seconds between SEC requests: at most 8 per second
README_URL = "https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/insider_transactions_readme.pdf"

REQUIRED_COLUMNS: dict[str, tuple[str, ...]] = {
    "SUBMISSION": ("ACCESSION_NUMBER", "FILING_DATE", "PERIOD_OF_REPORT", "DOCUMENT_TYPE", "ISSUERCIK",
                   "ISSUERNAME", "ISSUERTRADINGSYMBOL"),
    "REPORTINGOWNER": ("ACCESSION_NUMBER", "RPTOWNERCIK", "RPTOWNERNAME", "RPTOWNER_RELATIONSHIP",
                       "RPTOWNER_TITLE"),
    "NONDERIV_TRANS": ("ACCESSION_NUMBER", "SECURITY_TITLE", "TRANS_DATE", "TRANS_CODE", "TRANS_SHARES",
                       "TRANS_PRICEPERSHARE", "TRANS_ACQUIRED_DISP_CD", "SHRS_OWND_FOLWNG_TRANS",
                       "DIRECT_INDIRECT_OWNERSHIP"),
}
OPTIONAL_COLUMNS = {"SUBMISSION": ("AFF10B5ONE",)}  # Rule 10b5-1 checkbox, only on 2023+ quarters
_TRUE = {"1", "true", "y", "yes", "x"}
_last_request = 0.0


class SchemaError(RuntimeError):
    """A data-set file does not have the columns the SEC readme documents."""


@dataclass(frozen=True)
class Owner:
    cik: int
    name: str
    is_director: bool
    is_officer: bool
    is_ten_percent: bool
    title: str


@dataclass(frozen=True)
class TransactionRow:
    """One NONDERIV_TRANS row joined with its filing and reporting owners."""

    accession: str
    filing_date: date | None
    document_type: str
    issuer_cik: int | None
    issuer_ticker: str
    aff10b5one: bool | None  # None when the quarter has no AFF10B5ONE column (or it is blank)
    owners: tuple[Owner, ...]
    security_title: str
    trans_date: date | None
    code: str
    acquired_disposed: str
    shares: float | None
    price: float | None  # None when missing, <= 0 or > 1e6
    shares_after: float | None
    direct_indirect: str

    @property
    def value(self) -> float:
        return (self.shares or 0.0) * (self.price or 0.0)


# --- Download --------------------------------------------------------------------


def throttle() -> None:
    """Keep SEC requests at or below 8 per second (shared by every insiders module)."""
    global _last_request
    wait = _last_request + MIN_INTERVAL - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _last_request = time.monotonic()


def quarter_path(data_dir: str, year: int, q: int) -> str:
    return os.path.join(data_dir, CACHE_SUBDIR, f"{year}q{q}_form345.zip")


def quarters_between(first: tuple[int, int], last: tuple[int, int]) -> list[tuple[int, int]]:
    out, (y, q) = [], first
    while (y, q) <= last:
        out.append((y, q))
        y, q = (y, q + 1) if q < 4 else (y + 1, 1)
    return out


def download_quarter(year: int, q: int, data_dir: str, user_agent: str, *, offline: bool = False) -> str | None:
    """Path of the cached zip for a quarter, downloading it once. None if unavailable.

    offline=True only reads the cache (a miss is recorded, nothing is fetched).
    """
    path = quarter_path(data_dir, year, q)
    if os.path.exists(path):
        snapshot.record_read(path)
        return path
    if offline:
        snapshot.record_miss(path)
        return None
    for template in DATASET_URLS:
        url = template.format(year=year, q=q)
        for attempt in range(3):
            throttle()
            try:
                resp = httpx.get(url, headers={"User-Agent": user_agent}, timeout=120, follow_redirects=True)
                if resp.status_code == 404:
                    break  # not at this location: try the next one
                resp.raise_for_status()
                if not resp.content.startswith(b"PK"):
                    raise httpx.HTTPError(f"{url} did not return a zip")
                os.makedirs(os.path.dirname(path), exist_ok=True)
                tmp = path + ".part"
                with open(tmp, "wb") as f:
                    f.write(resp.content)
                os.replace(tmp, path)
                snapshot.record_read(path)
                return path
            except httpx.HTTPError as exc:
                log.warning("Retry %s for %s: %s", attempt, url, exc)
                time.sleep(5 * (attempt + 1))
    log.warning("No data set for %sq%s at any known SEC location", year, q)
    return None


# --- Parsing ---------------------------------------------------------------------


def parse_date(text: str | None) -> date | None:
    """Data-set dates are DD-MON-YYYY (e.g. 15-JAN-2024); ISO dates are accepted too."""
    text = (text or "").strip()
    if not text:
        return None
    for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(text[:11] if fmt == "%d-%b-%Y" else text[:10], fmt).date()
        except ValueError:
            continue
    return None


def _float(text: str | None) -> float | None:
    text = (text or "").strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _int(text: str | None) -> int | None:
    text = (text or "").strip()
    try:
        return int(text) if text else None
    except ValueError:
        return None


def _flag(text: str | None) -> bool | None:
    text = (text or "").strip().lower()
    if not text:
        return None
    return text in _TRUE


def parse_relationship(text: str) -> tuple[bool, bool, bool]:
    """(is_director, is_officer, is_ten_percent) from e.g. 'Director,Officer,TenPercentOwner'."""
    tokens = {t.strip().lower().replace(" ", "").replace("%", "percent") for t in (text or "").split(",")}
    director = "director" in tokens
    officer = "officer" in tokens
    ten = any(t in tokens for t in ("tenpercentowner", "10percentowner", "tenpercent"))
    return director, officer, ten


def _member(zf: zipfile.ZipFile, table: str) -> str:
    for name in zf.namelist():
        if os.path.basename(name).upper() == f"{table}.TSV":
            return name
    raise SchemaError(f"{zf.filename}: no {table}.tsv in the archive (see {README_URL})")


def _rows(zf: zipfile.ZipFile, table: str) -> Iterator[dict[str, str]]:
    """Stream one table as dicts, after checking its header against REQUIRED_COLUMNS."""
    csv.field_size_limit(min(sys.maxsize, 2**31 - 1))  # REMARKS / footnote text can be long
    with zf.open(_member(zf, table)) as raw:
        text = io.TextIOWrapper(raw, encoding="utf-8", errors="replace", newline="")
        reader = csv.reader(text, delimiter="\t", quoting=csv.QUOTE_NONE)
        header = [h.strip().lstrip("﻿").upper() for h in next(reader, [])]
        missing = [c for c in REQUIRED_COLUMNS[table] if c not in header]
        if missing:
            raise SchemaError(
                f"{zf.filename}: {table}.tsv is missing columns {missing} (found {header}). "
                f"The SEC data-set format changed; update REQUIRED_COLUMNS from {README_URL}"
            )
        for values in reader:
            if not values or values == [""]:
                continue
            yield dict(zip(header, values))


def iter_quarter(path: str, codes: Iterable[str] | None = None) -> Iterator[TransactionRow]:
    """Joined rows of one quarter, streaming NONDERIV_TRANS. codes keeps only those TRANS_CODEs."""
    keep = {c.upper() for c in codes} if codes is not None else None
    with zipfile.ZipFile(path) as zf:
        submissions: dict[str, dict] = {}
        for r in _rows(zf, "SUBMISSION"):
            submissions[r["ACCESSION_NUMBER"].strip()] = {
                "filing_date": parse_date(r["FILING_DATE"]),
                "document_type": r["DOCUMENT_TYPE"].strip().upper(),
                "issuer_cik": _int(r["ISSUERCIK"]),
                "issuer_ticker": r["ISSUERTRADINGSYMBOL"].strip().upper(),
                "aff10b5one": _flag(r.get("AFF10B5ONE")),
            }
        owners: dict[str, list[Owner]] = {}
        for r in _rows(zf, "REPORTINGOWNER"):
            cik = _int(r["RPTOWNERCIK"])
            if cik is None:
                continue
            director, officer, ten = parse_relationship(r["RPTOWNER_RELATIONSHIP"])
            owners.setdefault(r["ACCESSION_NUMBER"].strip(), []).append(
                Owner(cik, r["RPTOWNERNAME"].strip(), director, officer, ten, r["RPTOWNER_TITLE"].strip())
            )
        for r in _rows(zf, "NONDERIV_TRANS"):
            code = r["TRANS_CODE"].strip().upper()
            if keep is not None and code not in keep:
                continue
            acc = r["ACCESSION_NUMBER"].strip()
            sub = submissions.get(acc)
            if sub is None:
                continue  # orphan transaction row: no filing to attach it to
            yield TransactionRow(
                accession=acc,
                owners=tuple(sorted(owners.get(acc, []), key=lambda o: o.cik)),
                security_title=r["SECURITY_TITLE"].strip(),
                trans_date=parse_date(r["TRANS_DATE"]),
                code=code,
                acquired_disposed=r["TRANS_ACQUIRED_DISP_CD"].strip().upper(),
                shares=_float(r["TRANS_SHARES"]),
                price=plausible_price(_float(r["TRANS_PRICEPERSHARE"])),
                shares_after=_float(r["SHRS_OWND_FOLWNG_TRANS"]),
                direct_indirect=r["DIRECT_INDIRECT_OWNERSHIP"].strip().upper(),
                **sub,
            )


def load_quarter(path: str, codes: Iterable[str] | None = None) -> list[TransactionRow]:
    """All joined rows of one quarter (see iter_quarter)."""
    return list(iter_quarter(path, codes))
