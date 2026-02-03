#!/usr/bin/env python3
"""
View bot performance and forecast accuracy

Usage: python3 view_performance.py
"""

import json
import csv
from pathlib import Path
from datetime import datetime


def view_outcomes():
    """Display outcomes from CSV"""
    outcomes_file = Path("data/outcomes.csv")
    
    if not outcomes_file.exists():
        print("❌ No outcomes file found yet. Trades need to settle first.")
        return
    
    with open(outcomes_file, 'r') as f:
        reader = csv.DictReader(f)
        outcomes = list(reader)
    
    if not outcomes:
        print("📊 No settled positions yet")
        return
    
    print("\n" + "="*80)
    print("🎯 SETTLED POSITIONS")
    print("="*80)
    
    for outcome in outcomes[-20:]:  # Last 20
        won = outcome['won'] == 'YES'
        symbol = "✅" if won else "❌"
        pnl = float(outcome['profit_loss']) if outcome['profit_loss'] else 0
        
        print(f"{symbol} {outcome['market_ticker']}")
        print(f"   {outcome['side'].upper()} | {'WON' if won else 'LOST'} | P&L: ${pnl:.2f}")
        
        if outcome['actual_temp'] and outcome['predicted_temp']:
            print(f"   Forecast: {float(outcome['predicted_temp']):.1f}° | Actual: {float(outcome['actual_temp']):.1f}° | Error: {float(outcome['forecast_error']):.1f}°")
        print()


def view_performance():
    """Display performance summary"""
    perf_file = Path("data/performance.json")
    
    if not perf_file.exists():
        print("❌ No performance file found yet")
        return
    
    with open(perf_file, 'r') as f:
        report = json.load(f)
    
    overall = report.get('overall', {})
    by_city = report.get('by_city', {})
    
    print("\n" + "="*80)
    print("📊 OVERALL PERFORMANCE")
    print("="*80)
    print(f"Total Trades: {overall.get('total_trades', 0)}")
    print(f"Win Rate: {overall.get('win_rate', 0):.1%} ({overall.get('wins', 0)}W-{overall.get('losses', 0)}L)")
    print(f"Total P&L: ${overall.get('total_pnl', 0):.2f}")
    
    if by_city:
        print("\n" + "="*80)
        print("🏙️  PERFORMANCE BY CITY")
        print("="*80)
        
        for city, stats in sorted(by_city.items()):
            print(f"\n{city}:")
            print(f"  Trades: {stats['trades']}")
            print(f"  Win Rate: {stats['win_rate']:.1%}")
            print(f"  P&L: ${stats['pnl']:.2f}")
            if stats['avg_forecast_error']:
                print(f"  Avg Forecast Error: {stats['avg_forecast_error']:.1f}°")


def view_trades():
    """Display recent trades"""
    trades_file = Path("data/trades.csv")
    
    if not trades_file.exists():
        print("📝 No trades CSV found yet")
        return
    
    with open(trades_file, 'r') as f:
        reader = csv.DictReader(f)
        trades = list(reader)
    
    if not trades:
        return
    
    print("\n" + "="*80)
    print("📝 RECENT TRADES (Last 20)")
    print("="*80)
    
    for trade in trades[-20:]:
        print(f"{trade['timestamp'][:19]} | {trade['market_ticker']}")
        print(f"   {trade['action'].upper()} {trade['count']} {trade['side'].upper()} @ {trade['price']}¢")
        print(f"   Edge: {float(trade['edge']):.1f}% | EV: ${float(trade['ev']):.3f} | Mode: {trade['strategy_mode']}")
        print()


if __name__ == '__main__':
    print("\n🤖 KALSHI TRADING BOT PERFORMANCE REPORT")
    print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    view_performance()
    view_outcomes()
    view_trades()
    
    print("\n" + "="*80)
