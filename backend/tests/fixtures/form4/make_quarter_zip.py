"""Regenerate 2024q1_form345.zip: a tiny synthetic SEC Insider Transactions Data Set quarter.

    python tests/fixtures/form4/make_quarter_zip.py      (from backend/, e.g. in the api image)

Column layout follows the SEC readme (subset of the real columns, same names and order). Companies,
people and accession numbers are invented. Scenarios (what test_insiders.py expects):

issuer 1001 AAA
  A1 0000002001-24-000001 10-JAN-2024 director 2001: P 600@15 + P 400@15 (matches form4_two_purchases.xml)
  A2 0000002002-24-000001 10-JAN-2024 officer 2002:  P 500@10          -> day total 20,000, cluster (2 insiders)
  A3 0000002003-24-000001 22-JAN-2024 10%-owner only: P 10000@10       -> excluded (not director/officer)
  A4 0000002001-24-000002 25-JAN-2024 Form 4/A:       P 1000@15        -> excluded (amendment)
  A5 0000002002-24-000002 01-FEB-2024 officer 2002:  P 100@50          -> qualifies, below $10,000
  A6 0000002004-24-000001 05-FEB-2024 director 2004: P 2000@10, AFF10B5ONE=1 -> excluded
  A7 0000002004-24-000002 08-FEB-2024 director 2004: P 2000@10 (+ an S row) -> event, cluster with A5
  A8 0000002001-24-000003 15-MAR-2024 director 2001: A grant at 0, P at price 0 -> excluded
issuer 1002 BBB
  B1 0000002005-24-000001 12-FEB-2024 joint filing: 2005 director+officer, 2006 10% owner:
     P 600@10 + P 600@10 -> event (one insider: 2005), no cluster
issuer 1003 CCC
  C1 0000002007-24-000001 20-FEB-2024 director 2007: P with acquired/disposed D -> excluded
plus one NONDERIV_TRANS row whose accession has no SUBMISSION row (orphan, skipped).
"""

import os
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))

SUBMISSION_COLS = ["ACCESSION_NUMBER", "FILING_DATE", "PERIOD_OF_REPORT", "DATE_OF_ORIG_SUB", "NO_SECURITIES_OWNED",
                   "NOT_SUBJECT_SEC16", "FORM3_HOLDINGS_REPORTED", "FORM4_TRANS_REPORTED", "DOCUMENT_TYPE",
                   "ISSUERCIK", "ISSUERNAME", "ISSUERTRADINGSYMBOL", "REMARKS", "AFF10B5ONE"]
OWNER_COLS = ["ACCESSION_NUMBER", "RPTOWNERCIK", "RPTOWNERNAME", "RPTOWNER_RELATIONSHIP", "RPTOWNER_TITLE",
              "RPTOWNER_TXT", "RPTOWNER_STREET1", "RPTOWNER_STREET2", "RPTOWNER_CITY", "RPTOWNER_STATE",
              "RPTOWNER_ZIPCODE", "RPTOWNER_STATE_DESC", "FILE_NUMBER"]
TRANS_COLS = ["ACCESSION_NUMBER", "NONDERIV_TRANS_SK", "SECURITY_TITLE", "SECURITY_TITLE_FN", "TRANS_DATE",
              "TRANS_DATE_FN", "DEEMED_EXECUTION_DATE", "DEEMED_EXECUTION_DATE_FN", "TRANS_FORM_TYPE", "TRANS_CODE",
              "EQUITY_SWAP_INVOLVED", "EQUITY_SWAP_TRANS_CD_FN", "TRANS_TIMELINESS", "TRANS_TIMELINESS_FN",
              "TRANS_SHARES", "TRANS_SHARES_FN", "TRANS_PRICEPERSHARE", "TRANS_PRICEPERSHARE_FN",
              "TRANS_ACQUIRED_DISP_CD", "TRANS_ACQUIRED_DISP_CD_FN", "SHRS_OWND_FOLWNG_TRANS",
              "SHRS_OWND_FOLWNG_TRANS_FN", "VALU_OWND_FOLWNG_TRANS", "VALU_OWND_FOLWNG_TRANS_FN",
              "DIRECT_INDIRECT_OWNERSHIP", "DIRECT_INDIRECT_OWNERSHIP_FN", "NATURE_OF_OWNERSHIP",
              "NATURE_OF_OWNERSHIP_FN"]

ISSUERS = {1001: ("Alpha Example Corp", "AAA"), 1002: ("Beta Example Inc", "BBB"), 1003: ("Gamma Example Co", "CCC")}

# accession, filing date, document type, issuer, aff10b5one
FILINGS = [
    ("0000002001-24-000001", "10-JAN-2024", "4", 1001, "0"),
    ("0000002002-24-000001", "10-JAN-2024", "4", 1001, ""),
    ("0000002003-24-000001", "22-JAN-2024", "4", 1001, "0"),
    ("0000002001-24-000002", "25-JAN-2024", "4/A", 1001, "0"),
    ("0000002002-24-000002", "01-FEB-2024", "4", 1001, "0"),
    ("0000002004-24-000001", "05-FEB-2024", "4", 1001, "1"),
    ("0000002004-24-000002", "08-FEB-2024", "4", 1001, "0"),
    ("0000002001-24-000003", "15-MAR-2024", "4", 1001, "0"),
    ("0000002005-24-000001", "12-FEB-2024", "4", 1002, "0"),
    ("0000002007-24-000001", "20-FEB-2024", "4", 1003, "0"),
]

# accession, owner cik, name, relationship, title
OWNERS = [
    ("0000002001-24-000001", 2001, "Doe Jane", "Director", ""),
    ("0000002002-24-000001", 2002, "Poe Pat", "Officer", "Chief Financial Officer"),
    ("0000002003-24-000001", 2003, "Big Holder LP", "TenPercentOwner", ""),
    ("0000002001-24-000002", 2001, "Doe Jane", "Director", ""),
    ("0000002002-24-000002", 2002, "Poe Pat", "Officer", "Chief Financial Officer"),
    ("0000002004-24-000001", 2004, "Loe Lee", "Director", ""),
    ("0000002004-24-000002", 2004, "Loe Lee", "Director", ""),
    ("0000002001-24-000003", 2001, "Doe Jane", "Director", ""),
    ("0000002005-24-000001", 2006, "Roe Family Trust", "TenPercentOwner", ""),
    ("0000002005-24-000001", 2005, "Roe Richard", "Director,Officer", "Chief Executive Officer"),
    ("0000002007-24-000001", 2007, "Moe Max", "Director", ""),
]

# accession, trans date, code, shares, price, acquired/disposed, shares after, direct/indirect
TRANSACTIONS = [
    ("0000002001-24-000001", "08-JAN-2024", "P", "600", "15", "A", "10600", "D"),
    ("0000002001-24-000001", "09-JAN-2024", "P", "400", "15", "A", "11000", "I"),
    ("0000002002-24-000001", "09-JAN-2024", "P", "500", "10", "A", "3500", "D"),
    ("0000002003-24-000001", "19-JAN-2024", "P", "10000", "10", "A", "900000", "D"),
    ("0000002001-24-000002", "09-JAN-2024", "P", "1000", "15", "A", "11000", "D"),
    ("0000002002-24-000002", "30-JAN-2024", "P", "100", "50", "A", "3600", "D"),
    ("0000002004-24-000001", "02-FEB-2024", "P", "2000", "10", "A", "12000", "D"),
    ("0000002004-24-000002", "06-FEB-2024", "P", "2000", "10", "A", "14000", "D"),
    ("0000002004-24-000002", "06-FEB-2024", "S", "100", "12", "D", "13900", "D"),
    ("0000002001-24-000003", "13-MAR-2024", "A", "5000", "0", "A", "16000", "D"),
    ("0000002001-24-000003", "13-MAR-2024", "P", "1000", "0", "A", "17000", "D"),
    ("0000002005-24-000001", "09-FEB-2024", "P", "600", "10", "A", "20600", "D"),
    ("0000002005-24-000001", "09-FEB-2024", "P", "600", "10.00", "A", "21200", "D"),
    ("0000002007-24-000001", "15-FEB-2024", "P", "1000", "20", "D", "5000", "D"),
    ("0000009999-24-000001", "15-FEB-2024", "P", "1000", "20", "A", "5000", "D"),  # orphan
]


def tsv(cols: list[str], rows: list[list[str]]) -> str:
    return "\n".join("\t".join(r) for r in [cols, *rows]) + "\n"


def build() -> dict[str, str]:
    subs = []
    for acc, filed, doc, issuer, aff in FILINGS:
        name, ticker = ISSUERS[issuer]
        subs.append([acc, filed, filed, "", "0", "0", "", "", doc, str(issuer), name, ticker, "", aff])
    owners = [[acc, str(cik), name, rel, title, "", "1 Example Way", "", "Springfield", "IL", "62701", "", ""]
              for acc, cik, name, rel, title in OWNERS]
    trans = []
    for sk, (acc, d, code, sh, px, ad, after, di) in enumerate(TRANSACTIONS, start=1):
        trans.append([acc, str(sk), "Common Stock", "", d, "", "", "", "4", code, "0", "", "", "", sh, "", px, "",
                      ad, "", after, "", "", "", di, "", "", ""])
    return {"SUBMISSION.tsv": tsv(SUBMISSION_COLS, subs), "REPORTINGOWNER.tsv": tsv(OWNER_COLS, owners),
            "NONDERIV_TRANS.tsv": tsv(TRANS_COLS, trans)}


def write(path: str) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, text in build().items():
            info = zipfile.ZipInfo(name, date_time=(2024, 4, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, text)


if __name__ == "__main__":
    write(os.path.join(HERE, "2024q1_form345.zip"))
