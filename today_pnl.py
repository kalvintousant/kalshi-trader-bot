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
from typing import Optional, Set, Tuple

from dotenv import load_dotenv
load_dotenv()

from src.config import Config
from src.kalshi_client import KalshiClient
from src.weather_data import WeatherDataAggregator


def pnl_from_outcomes_csv_today(
    only_today_fills: Optional[Set[Tuple[str, str, str, str]]] = None,
) -> Tuple[float, int]:
    """
    Sum profit_loss from data/outcomes.csv.
    If only_today_fills is provided, only count rows that match those (ticker, entry_price, contracts, side)
    so the CSV number matches "today's P&L" (trades bought today). Otherwise sums all rows with timestamp today
    (can include historical settlements logged today).
    Deduplicates by (market_ticker, entry_price, contracts, side).
    Returns (total_pnl, num_unique_fills).
    """
    path = Path("data/outcomes.csv")
    if not path.exists():
        return (0.0, 0)
    today_str = datetime.now().date().isoformat()
    total = 0.0
    seen: Set[Tuple[str, str, str, str]] = set()
    with open(path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts = (row.get("timestamp") or "").strip()
            if not ts or not ts.startswith(today_str):
                continue
            ticker = (row.get("market_ticker") or "").strip()
            entry = (row.get("entry_price") or "").strip()
            contracts = (row.get("contracts") or "").strip()
            side = (row.get("side") or "").strip()
            try:
                pl = float(row.get("profit_loss") or 0)
            except ValueError:
                continue
            key = (ticker, entry, contracts, side.strip().lower())
            if only_today_fills is not None and key not in only_today_fills:
                continue
            if key not in seen:
                seen.add(key)
                total += pl
    return (total, len(seen))


def main():
    print("\n📊 Today's P&L Report")
    print(f"   Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")

    try:
        Config.validate()
    except Exception as e:
        print(f"   Config error (set .env): {e}\n")
        return

    # P&L from today's fills: settled (API) + NWS-inferred (past/today). Pending excluded.
    today_fill_keys = None
    try:
        from review_trades_today import compute_today_fill_pnl
        client = KalshiClient()
        weather_agg = WeatherDataAggregator()
        pnl_fills, n_right, n_wrong, n_pending, right, wrong, _, _ = compute_today_fill_pnl(client, weather_agg)
        n_settled_or_inferred = n_right + n_wrong
        # Build set of (ticker, entry_price, contracts, side) for today's fills so CSV only counts those
        if n_settled_or_inferred > 0:
            today_fill_keys = set()
            for item in list(right) + list(wrong):
                f, ticker, side, _, _, _ = item
                price = int(f.get("yes_price") or f.get("no_price") or f.get("price") or 0)
                count = int(f.get("count") or 0)
                today_fill_keys.add((ticker.strip(), str(price), str(count), side.strip().lower()))
        print("   From today's fills (outcome-based, excludes pending):")
        print(f"   Settled + NWS inferred: {n_settled_or_inferred}  |  Pending (excluded): {n_pending}")
        print(f"   Net P&L (excludes pending): ${pnl_fills:.2f}\n")
    except Exception as e:
        print(f"   Could not compute fill P&L: {e}\n")
        pnl_fills = 0.0
        n_settled_or_inferred = 0
        n_pending = 0

    # CSV: only count outcomes that match today's fills (same ticker/price/count/side) so it aligns with fill P&L
    pnl_csv, n_csv = pnl_from_outcomes_csv_today(only_today_fills=today_fill_keys)
    if n_csv > 0:
        print("   From data/outcomes.csv (today's trades only):")
        print(f"   Outcomes: {n_csv}  |  Net P&L: ${pnl_csv:.2f}\n")
    elif today_fill_keys and len(today_fill_keys) > 0:
        print("   data/outcomes.csv: no rows yet for today's trades (markets may still be pending).\n")
    else:
        print("   No matching rows in data/outcomes.csv for today's trades.\n")

    # Single combined line: use fill-based P&L as the canonical "today's P&L" (excludes pending)
    if n_settled_or_inferred > 0 or n_csv > 0:
        total_today = pnl_fills if n_settled_or_inferred > 0 else pnl_csv
        print("   ---")
        print(f"   Today's P&L (excludes pending): ${total_today:.2f}\n")


if __name__ == "__main__":
    main()
