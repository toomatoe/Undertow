"""Pre-fetch SEC submissions and prices for both periods (slow once, cached after)."""

import logging
import os

from app.backtest.universe import PERIODS, PRICE_END, PRICE_START, build_universe
from app.config import get_settings
from app.research.prices import load_prices


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    s = get_settings()
    price_dir = os.path.join(s.data_dir, "prices")
    for p in ["IWM", "SPY"]:
        load_prices(p, PRICE_START, PRICE_END, price_dir)
    for period in PERIODS.values():
        events, coverage = build_universe(period, s.data_dir, s.sec_user_agent)
        logging.info("%s universe: %s", period.key, coverage)
        tickers = sorted({e.ticker for e in events})
        missing = sum(1 for t in tickers if load_prices(t, PRICE_START, PRICE_END, price_dir) is None)
        logging.info("%s: %d tickers, %d without prices", period.key, len(tickers), missing)


if __name__ == "__main__":
    main()
