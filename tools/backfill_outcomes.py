#!/usr/bin/env python3
"""
Backfill empty fields in outcomes.csv by looking up matching trades in trades.csv.

One-time script to populate our_probability, market_price, edge, ev, strategy_mode
for historical outcome rows that were written with empty strings.
"""

import csv
import sys
from collections import defaultdict
from pathlib import Path


def load_trades(trades_path: Path) -> dict:
    """Load trades.csv into a lookup dict keyed by (market_ticker, side)."""
    lookup = {}
    if not trades_path.exists():
        return lookup
    with open(trades_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = (row.get('market_ticker', ''), row.get('side', '').lower())
            # Keep the first trade for each ticker/side (earliest entry)
            if key not in lookup:
                lookup[key] = row
    return lookup


def backfill(outcomes_path: Path, trades_path: Path, dry_run: bool = False):
    """Backfill empty fields in outcomes.csv from trades.csv."""
    if not outcomes_path.exists():
        print(f"No outcomes file found at {outcomes_path}")
        return

    trades = load_trades(trades_path)
    if not trades:
        print(f"No trades found in {trades_path}")
        return

    # Read all outcomes
    rows = []
    with open(outcomes_path, 'r') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    if not rows:
        print("No outcome rows to backfill")
        return

    filled = 0
    for row in rows:
        # Check if trade details are missing
        if row.get('our_probability') or row.get('edge'):
            continue  # Already populated

        ticker = row.get('market_ticker', '')
        side = row.get('side', '').lower()
        key = (ticker, side)

        trade = trades.get(key)
        if not trade:
            continue

        row['our_probability'] = trade.get('our_probability', '')
        row['market_price'] = trade.get('market_price', '')
        row['edge'] = trade.get('edge', '')
        row['ev'] = trade.get('ev', '')
        row['strategy_mode'] = trade.get('strategy_mode', '')

        # Also backfill target_date if missing
        if not row.get('date') and trade.get('target_date'):
            row['date'] = trade['target_date']

        filled += 1

    print(f"Backfilled {filled}/{len(rows)} outcome rows")

    if dry_run:
        print("(dry run — no changes written)")
        return

    # Write back
    with open(outcomes_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Updated {outcomes_path}")


if __name__ == '__main__':
    dry_run = '--dry-run' in sys.argv
    paper = '--paper' in sys.argv

    outcomes = Path("data/paper_outcomes.csv") if paper else Path("data/outcomes.csv")
    trades = Path("data/trades.csv")

    print(f"Backfilling {outcomes} from {trades}")
    backfill(outcomes, trades, dry_run=dry_run)
