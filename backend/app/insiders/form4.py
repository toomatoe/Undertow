"""Parse SEC ownership documents (Form 3/4/5 XML) with the standard library only.

parse_ownership_xml(xml_bytes) returns a plain dict:

    {"document_type": "4", "period": "2024-01-08", "aff10b5one": False | True | None,
     "issuer": {"cik": 1001, "ticker": "AAA", "name": "..."},
     "reporting_owners": [{"cik", "name", "is_director", "is_officer", "officer_title", "is_ten_percent"}],
     "transactions": [{"security_title", "date", "code", "acquired_disposed", "shares", "price",
                       "shares_after", "direct_indirect"}]}

Every <nonDerivativeTransaction> block is returned (filings often carry several). Empty <value/>
elements and <footnoteId/> siblings are tolerated (missing values become None). Implausible prices
(<= 0 or > 1e6) become None.

Security: documents containing a DOCTYPE or ENTITY declaration are rejected before parsing, so entity
expansion ("billion laughs") and external entities cannot occur. Real EDGAR ownership XML has neither.

Used by app.insiders.study for the dataset-vs-XML cross-check; a future live insider alert can reuse
parse_ownership_xml + raw_xml_url unchanged (see AGENTS.md).
"""

import re
import xml.etree.ElementTree as ET
from datetime import date

ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{document}"
MAX_PRICE = 1e6
_FORBIDDEN = re.compile(rb"<!\s*(DOCTYPE|ENTITY)", re.IGNORECASE)
_XSL_PREFIX = re.compile(r"^xslF345X\d+/", re.IGNORECASE)
_TRUE = {"1", "true", "y", "yes", "x"}


class UnsafeXMLError(ValueError):
    """The document contains a DOCTYPE or ENTITY declaration."""


def raw_xml_url(cik: int | str, accession: str, primary_document: str) -> str:
    """Archive URL of the raw XML. submissions' primaryDocument points at the XSL-rendered view
    (`xslF345X05/form4.xml`); stripping that prefix gives the raw document."""
    doc = _XSL_PREFIX.sub("", primary_document.strip())
    return ARCHIVE_URL.format(cik=int(cik), accession=accession.replace("-", ""), document=doc)


def _strip_ns(root: ET.Element) -> None:
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]


def _text(el: ET.Element | None, path: str) -> str | None:
    """Text at path, or at path/value (EDGAR wraps most fields in <value>). Empty -> None."""
    if el is None:
        return None
    node = el.find(path)
    if node is None:
        return None
    value = node.find("value")
    if value is not None:
        node = value
    text = (node.text or "").strip()
    return text or None


def _bool(text: str | None) -> bool | None:
    if text is None:
        return None
    return text.strip().lower() in _TRUE


def _float(text: str | None) -> float | None:
    if text is None:
        return None
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return None


def plausible_price(price: float | None) -> float | None:
    return price if price is not None and 0 < price <= MAX_PRICE else None


def _date(text: str | None) -> str | None:
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        return None


def _int(text: str | None) -> int | None:
    try:
        return int(text) if text else None
    except ValueError:
        return None


def parse_ownership_xml(xml_bytes: bytes) -> dict:
    """Parse one ownershipDocument. Raises UnsafeXMLError on DOCTYPE/ENTITY, ValueError on malformed XML."""
    if isinstance(xml_bytes, str):
        xml_bytes = xml_bytes.encode("utf-8")
    if _FORBIDDEN.search(xml_bytes):
        raise UnsafeXMLError("ownership XML with a DOCTYPE/ENTITY declaration rejected")
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise ValueError(f"malformed ownership XML: {exc}") from exc
    _strip_ns(root)
    if root.tag != "ownershipDocument":
        raise ValueError(f"not an ownershipDocument (root <{root.tag}>)")

    issuer = root.find("issuer")
    owners = []
    for ro in root.findall("reportingOwner"):
        rel = ro.find("reportingOwnerRelationship")
        owners.append({
            "cik": _int(_text(ro, "reportingOwnerId/rptOwnerCik")),
            "name": _text(ro, "reportingOwnerId/rptOwnerName"),
            "is_director": bool(_bool(_text(rel, "isDirector"))),
            "is_officer": bool(_bool(_text(rel, "isOfficer"))),
            "officer_title": _text(rel, "officerTitle"),
            "is_ten_percent": bool(_bool(_text(rel, "isTenPercentOwner"))),
        })

    transactions = []
    for tx in root.iter("nonDerivativeTransaction"):
        transactions.append({
            "security_title": _text(tx, "securityTitle"),
            "date": _date(_text(tx, "transactionDate")),
            "code": _text(tx, "transactionCoding/transactionCode"),
            "acquired_disposed": _text(tx, "transactionAmounts/transactionAcquiredDisposedCode"),
            "shares": _float(_text(tx, "transactionAmounts/transactionShares")),
            "price": plausible_price(_float(_text(tx, "transactionAmounts/transactionPricePerShare"))),
            "shares_after": _float(_text(tx, "postTransactionAmounts/sharesOwnedFollowingTransaction")),
            "direct_indirect": _text(tx, "ownershipNature/directOrIndirectOwnership"),
        })

    ticker = _text(issuer, "issuerTradingSymbol")
    return {
        "document_type": _text(root, "documentType"),
        "period": _date(_text(root, "periodOfReport")),
        "aff10b5one": _bool(_text(root, "aff10b5One")),
        "issuer": {
            "cik": _int(_text(issuer, "issuerCik")),
            "ticker": ticker.upper() if ticker else None,
            "name": _text(issuer, "issuerName"),
        },
        "reporting_owners": owners,
        "transactions": transactions,
    }
