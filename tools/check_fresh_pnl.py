#!/usr/bin/env python3
"""
Track P&L since the bot optimizations on Feb 3, 2026.
Run this periodically to see performance with new settings.
"""

import json
from datetime import datetime, timezone
from src.kalshi_client import KalshiClient

def main():
    client = KalshiClient()

    # Load tracking start time
    try:
        with open('data/pnl_tracking_start.json', 'r') as f:
            tracking = json.load(f)
        start_time = tracking['tracking_started']
        print(f"=== P&L TRACKING (since {start_time}) ===\n")
    except:
        print("=== P&L TRACKING ===\n")
        start_time = None

    # Get current portfolio
    portfolio = client.get_portfolio()
    balance = portfolio.get('balance', 0) / 100.0
    portfolio_value = portfolio.get('portfolio_value', 0) / 100.0
    total_value = balance + portfolio_value

    print(f"Current Portfolio:")
    print(f"  Cash Balance: ${balance:.2f}")
    print(f"  Position Value: ${portfolio_value:.2f}")
    print(f"  Total Value: ${total_value:.2f}")

    # Get recent fills
    fills = client.get_fills(limit=100)

    # Count fills and calculate cost
    buy_count = 0
    buy_cost = 0.0
    sell_count = 0
    sell_revenue = 0.0

    for fill in fills:
        action = fill.get('action', 'buy')
        count = fill.get('count', 0)
        price = fill.get('yes_price') or fill.get('no_price', 0)
        cost = (count * price) / 100.0

        if action == 'buy':
            buy_count += count
            buy_cost += cost
        else:
            sell_count += count
            sell_revenue += cost

    print(f"\nRecent Activity (last 100 fills):")
    print(f"  Buys: {buy_count} contracts, ${buy_cost:.2f} spent")
    print(f"  Sells: {sell_count} contracts, ${sell_revenue:.2f} received")

    # Get current positions summary
    positions = client.get_positions()
    pos_count = sum(abs(p.get('position', 0)) for p in positions)
    pos_exposure = sum(p.get('market_exposure', 0) for p in positions) / 100.0

    print(f"\nOpen Positions:")
    print(f"  Total Contracts: {pos_count}")
    print(f"  Total Exposure: ${pos_exposure:.2f}")

    # Get resting orders
    orders = client.get_orders(status='resting', use_cache=False)
    order_count = sum(o.get('remaining_count', 0) for o in orders)
    order_exposure = sum((o.get('remaining_count', 0) * (o.get('yes_price') or o.get('no_price', 0))) / 100.0 for o in orders)

    print(f"\nResting Orders:")
    print(f"  Total Orders: {len(orders)}")
    print(f"  Total Contracts: {order_count}")
    print(f"  Potential Exposure: ${order_exposure:.2f}")

    print(f"\n{'='*50}")
    print("Check back in 24-48 hours to compare performance!")

if __name__ == '__main__':
    main()
