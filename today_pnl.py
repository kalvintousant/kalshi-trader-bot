#!/usr/bin/env python3
"""
Report today's net P&L from filled orders.

Usage: python3 today_pnl.py

P&L is computed from outcomes only (settled via API + NWS-inferred for past/today).
Pending (future or no data) is excluded from P&L.
"""

import csv
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from src.config import Config
from src.kalshi_client import KalshiClient
from src.weather_data import WeatherDataAggregator


def pnl_from_outcomes_csv_today() -> tuple[float, int]:
    """
    Sum profit_loss from data/outcomes.csv for rows with timestamp date = today (local).
    Returns (total_pnl, num_outcomes).
    """
    path = Path("data/outcomes.csv")
    if not path.exists():
        return (0.0, 0)
    today_str = datetime.now().date().isoformat()
    total = 0.0
    n = 0
    with open(path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts = (row.get("timestamp") or "").strip()
            if not ts or not ts.startswith(today_str):
                continue
            try:
                total += float(row.get("profit_loss") or 0)
            except ValueError:
                pass
            n += 1
    return (total, n)


def main():
    print("\n📊 Today's P&L Report")
    print(f"   Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")

    try:
        Config.validate()
    except Exception as e:
        print(f"   Config error (set .env): {e}\n")
        return

    # P&L from today's fills: settled (API) + NWS-inferred (past/today). Pending excluded.
    try:
        from review_trades_today import compute_today_fill_pnl
        client = KalshiClient()
        weather_agg = WeatherDataAggregator()
        pnl_fills, n_right, n_wrong, n_pending, _, _, _, _ = compute_today_fill_pnl(client, weather_agg)
        n_settled_or_inferred = n_right + n_wrong
        print("   From today's fills (outcome-based, excludes pending):")
        print(f"   Settled + NWS inferred: {n_settled_or_inferred}  |  Pending (excluded): {n_pending}")
        print(f"   Net P&L (excludes pending): ${pnl_fills:.2f}\n")
    except Exception as e:
        print(f"   Could not compute fill P&L: {e}\n")
        pnl_fills = 0.0
        n_settled_or_inferred = 0
        n_pending = 0

    # Optional: from data/outcomes.csv (logged by outcome_tracker when markets settle)
    pnl_csv, n_csv = pnl_from_outcomes_csv_today()
    if n_csv > 0:
        print("   From data/outcomes.csv (logged today):")
        print(f"   Outcomes: {n_csv}  |  Net P&L: ${pnl_csv:.2f}\n")
    else:
        print("   No rows for today in data/outcomes.csv.\n")

    # Single combined line: use fill-based P&L as the canonical "today's P&L" (excludes pending)
    if n_settled_or_inferred > 0 or n_csv > 0:
        total_today = pnl_fills if n_settled_or_inferred > 0 else pnl_csv
        print("   ---")
        print(f"   Today's P&L (excludes pending): ${total_today:.2f}\n")


if __name__ == "__main__":
    main()
