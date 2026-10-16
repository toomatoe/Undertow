"""Archive Interactive Brokers' public shortable-stocks file.

No free historical borrow data exists, which is the biggest unknown in the
backtest. IBKR publishes a current snapshot (fee rate and shares available
per symbol) over anonymous FTP. Saving it every day builds our own history,
so in a few months the backtest's borrow assumptions can be replaced with
measured fees and availability for the names that actually file offerings.

File format (pipe-delimited):
  #BOF|2026.10.16|13:04:30
  #SYM|CUR|NAME|CON|ISIN|REBATERATE|FEERATE|AVAILABLE|FIGI|
  AAPL|USD|APPLE INC|265598|US0378331005|3.33|0.25|>10000000|BBG000B9XRY4|
  #EOF|20024
"""

import ftplib
import glob
import gzip
import io
import logging
import os
from datetime import datetime, timezone

log = logging.getLogger(__name__)

FTP_HOST = "ftp2.interactivebrokers.com"
FTP_USER = "shortstock"
FILE = "usa.txt"


def archive_dir(data_dir: str) -> str:
    return os.path.join(data_dir, "borrow")


def download() -> bytes:
    buf = io.BytesIO()
    with ftplib.FTP(FTP_HOST, timeout=60) as ftp:
        ftp.login(FTP_USER, "")
        ftp.retrbinary(f"RETR {FILE}", buf.write)
    return buf.getvalue()


def parse(raw: bytes) -> dict[str, dict]:
    """symbol -> {fee_rate (annual fraction), available (shares; None means 'plenty')}"""
    out: dict[str, dict] = {}
    for line in raw.decode("utf-8", errors="replace").splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split("|")
        if len(parts) < 8:
            continue
        sym, fee, avail = parts[0].strip(), parts[6].strip(), parts[7].strip()
        try:
            fee_rate = float(fee) / 100 if fee else None
        except ValueError:
            fee_rate = None
        available = None if avail.startswith(">") else (int(avail) if avail.isdigit() else 0)
        out[sym] = {"fee_rate": fee_rate, "available": available}
    return out


def snapshot(data_dir: str, min_hours: float = 12) -> str | None:
    """Save today's file unless a recent snapshot exists. Returns the path written, if any."""
    d = archive_dir(data_dir)
    os.makedirs(d, exist_ok=True)
    existing = sorted(glob.glob(os.path.join(d, "usa_*.txt.gz")))
    if existing and (datetime.now().timestamp() - os.path.getmtime(existing[-1])) < min_hours * 3600:
        return None
    raw = download()
    path = os.path.join(d, f"usa_{datetime.now(timezone.utc):%Y%m%d_%H%M}.txt.gz")
    with gzip.open(path, "wb") as f:
        f.write(raw)
    log.info("Archived IBKR borrow snapshot: %s (%d symbols)", path, len(parse(raw)))
    return path


def status(data_dir: str) -> dict:
    files = sorted(glob.glob(os.path.join(archive_dir(data_dir), "usa_*.txt.gz")))
    days = sorted({os.path.basename(f)[4:12] for f in files})
    return {"snapshots": len(files), "days": len(days), "first": days[0] if days else None, "last": days[-1] if days else None}


def latest(data_dir: str) -> dict[str, dict]:
    files = sorted(glob.glob(os.path.join(archive_dir(data_dir), "usa_*.txt.gz")))
    if not files:
        return {}
    with gzip.open(files[-1], "rb") as f:
        return parse(f.read())
