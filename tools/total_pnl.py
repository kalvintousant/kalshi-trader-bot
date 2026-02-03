#!/usr/bin/env python3
"""
Total return for base weather markets from a start date.
Sums the "total return" (revenue − cost − fees) for each settlement, same as Kalshi portfolio history.

Usage:
  python3 total_pnl.py
  python3 total_pnl.py --since 2026-01-27
"""

import argparse
import os
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

from src.config import Config
from src.kalshi_client import KalshiClient


DEFAULT_SINCE = "2026-01-27"


def _series_from_ticker(ticker: str) -> Optional[str]:
    if not ticker or "-" not in ticker:
        return None
    return ticker.split("-")[0].strip()


def total_pnl_from_settlements(since_date: str) -> dict:
    """Fetch settlements since date, filter to weather markets, sum total return per row."""
    try:
        Config.validate()
    except Exception as e:
        return {"total_pnl": 0.0, "n_settlements": 0, "error": str(e)}
    try:
        since_dt = datetime.strptime(since_date, "%Y-%m-%d")
    except ValueError:
        since_dt = datetime.strptime(DEFAULT_SINCE, "%Y-%m-%d")
    since_ts = int(since_dt.replace(tzinfo=timezone.utc).timestamp() * 1000)
    weather_series = set(Config.WEATHER_SERIES)

    client = KalshiClient()
    settlements = client.get_all_settlements(since_ts=since_ts)

    total = 0.0
    count = 0
    for s in settlements:
        ticker = (s.get("ticker") or "").strip()
        series = _series_from_ticker(ticker)
        if series not in weather_series:
            continue
        try:
            yes_cost = int(s.get("yes_total_cost") or 0)
            no_cost = int(s.get("no_total_cost") or 0)
            yes_count = int(s.get("yes_count") or 0)
            no_count = int(s.get("no_count") or 0)
            market_result = s.get("market_result", "")
            fee_cost = float(s.get("fee_cost") or 0)

            # Calculate actual payout based on market result
            if market_result == "yes":
                payout = yes_count * 100  # cents
            elif market_result == "no":
                payout = no_count * 100  # cents
            else:
                payout = 0

            # Total return = payout − costs − fees
            total += (payout - yes_cost - no_cost) / 100.0 - fee_cost
            count += 1
        except (TypeError, ValueError):
            pass
    return {"total_pnl": total, "n_settlements": count, "error": None}


def main():
    parser = argparse.ArgumentParser(description="Total return for weather markets (Kalshi history)")
    parser.add_argument("--since", default=os.environ.get("TOTAL_PNL_SINCE", DEFAULT_SINCE), help="Start date YYYY-MM-DD")
    args = parser.parse_args()
    since = args.since
    try:
        datetime.strptime(since, "%Y-%m-%d")
    except ValueError:
        since = DEFAULT_SINCE
    result = total_pnl_from_settlements(since)
    if result.get("error"):
        print(f"\n   Error: {result['error']}\n")
        return
    print("\n📊 Total return (base weather markets)")
    print(f"   Since: {since}  |  Settlements: {result['n_settlements']}")
    print(f"   Total return: ${result['total_pnl']:.2f}\n")


if __name__ == "__main__":
    main()
