#!/usr/bin/env python3
"""
Unified Analysis Dashboard

Runs all the Goldman-grade analysis tools:
1. Backtesting & Performance Metrics
2. Performance Attribution
3. Forecast Accuracy Analysis
4. Portfolio Risk Report

Usage:
    python run_analysis.py              # Run all reports
    python run_analysis.py attribution  # Run attribution only
    python run_analysis.py risk         # Run risk report only
    python run_analysis.py forecast     # Run forecast accuracy only
    python run_analysis.py backtest     # Run backtest only
"""

import sys
import os

# Add src to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.kalshi_client import KalshiClient


def run_attribution():
    """Run performance attribution analysis"""
    print("\n" + "="*70)
    print("  PERFORMANCE ATTRIBUTION ANALYSIS")
    print("="*70)

    try:
        from src.attribution import get_attribution
        attr = get_attribution()
        attr.print_report()
    except Exception as e:
        print(f"  Error running attribution: {e}")
        print("  (This requires trade history in data/historical.db)")


def run_risk_report():
    """Run portfolio risk analysis"""
    print("\n" + "="*70)
    print("  PORTFOLIO RISK ANALYSIS")
    print("="*70)

    try:
        client = KalshiClient()
        from src.portfolio_risk import get_risk_manager
        risk_mgr = get_risk_manager(client)
        risk_mgr.print_risk_report()
    except Exception as e:
        print(f"  Error running risk report: {e}")


def run_forecast_accuracy():
    """Run forecast accuracy analysis"""
    print("\n" + "="*70)
    print("  FORECAST ACCURACY ANALYSIS")
    print("="*70)

    try:
        from src.forecast_weighting import get_forecast_tracker
        tracker = get_forecast_tracker()
        tracker.print_accuracy_report()
    except Exception as e:
        print(f"  Error running forecast accuracy: {e}")
        print("  (This requires forecast history in data/forecasts.db)")


def run_backtest():
    """Run backtest analysis"""
    print("\n" + "="*70)
    print("  BACKTEST PERFORMANCE ANALYSIS")
    print("="*70)

    try:
        from src.backtester import get_data_store, PerformanceMetrics

        data_store = get_data_store()
        trades = data_store.get_all_trades()

        if not trades:
            print("  No trade history found. Trade data will accumulate over time.")
            return

        report = PerformanceMetrics.generate_report(trades)

        print(f"\n  OVERALL PERFORMANCE:")
        print(f"  {'-'*66}")
        print(f"  Total Trades: {report['total_trades']}")
        print(f"  Settled Trades: {report['settled_trades']}")
        print(f"  Total P&L: ${report['total_pnl']:.2f}")
        print(f"  Return: {report['return_pct']:.1f}%")
        print(f"\n  Win Rate: {report['win_rate']:.1f}% ({report['wins']}W / {report['losses']}L)")
        print(f"  Avg Win: ${report['avg_win']:.2f}")
        print(f"  Avg Loss: ${report['avg_loss']:.2f}")
        print(f"  Profit Factor: {report['profit_factor']:.2f}")
        print(f"  Expectancy: ${report['expectancy']:.4f}/trade")
        print(f"\n  RISK METRICS:")
        print(f"  {'-'*66}")
        print(f"  Sharpe Ratio: {report['sharpe_ratio']:.2f}")
        print(f"  Sortino Ratio: {report['sortino_ratio']:.2f}")
        print(f"  Max Drawdown: {report['max_drawdown_pct']:.1f}%")

    except Exception as e:
        print(f"  Error running backtest: {e}")


def run_current_status():
    """Run current portfolio status"""
    print("\n" + "="*70)
    print("  CURRENT PORTFOLIO STATUS")
    print("="*70)

    try:
        client = KalshiClient()

        # Get portfolio
        portfolio = client.get_portfolio()
        balance = portfolio.get('balance', 0) / 100.0
        portfolio_value = portfolio.get('portfolio_value', 0) / 100.0

        print(f"\n  ACCOUNT:")
        print(f"  {'-'*66}")
        print(f"  Cash Balance: ${balance:.2f}")
        print(f"  Position Value: ${portfolio_value:.2f}")
        print(f"  Total Value: ${balance + portfolio_value:.2f}")

        # Get positions
        positions = client.get_positions()
        active_positions = [p for p in positions if p.get('position', 0) != 0]

        print(f"\n  POSITIONS ({len(active_positions)} active):")
        print(f"  {'-'*66}")

        by_city = {}
        for pos in active_positions:
            ticker = pos.get('ticker', '')
            contracts = pos.get('position', 0)
            exposure = pos.get('market_exposure', 0) / 100.0

            # Extract city
            import re
            match = re.match(r'KX(HIGH|LOW)(\w+)-', ticker)
            city = match.group(2) if match else 'Other'

            if city not in by_city:
                by_city[city] = {'count': 0, 'exposure': 0}
            by_city[city]['count'] += abs(contracts)
            by_city[city]['exposure'] += exposure

        for city, data in sorted(by_city.items(), key=lambda x: x[1]['exposure'], reverse=True):
            print(f"  {city}: {data['count']} contracts, ${data['exposure']:.2f} exposure")

        # Get resting orders
        orders = client.get_orders(status='resting', use_cache=False)
        print(f"\n  RESTING ORDERS ({len(orders)}):")
        print(f"  {'-'*66}")
        for o in orders[:10]:
            ticker = o.get('ticker', '')
            side = o.get('side', '').upper()
            price = o.get('yes_price') if o.get('side') == 'yes' else o.get('no_price', 0)
            remaining = o.get('remaining_count', 0)
            print(f"  {ticker}: {side} {remaining}@{price}¢")

        if len(orders) > 10:
            print(f"  ... and {len(orders) - 10} more")

    except Exception as e:
        print(f"  Error getting status: {e}")


def main():
    print("\n" + "="*70)
    print("  KALSHI TRADING BOT - ANALYSIS DASHBOARD")
    print("  Goldman-Grade Analytics Suite")
    print("="*70)

    # Parse arguments
    if len(sys.argv) > 1:
        command = sys.argv[1].lower()
        if command == 'attribution':
            run_attribution()
        elif command == 'risk':
            run_risk_report()
        elif command == 'forecast':
            run_forecast_accuracy()
        elif command == 'backtest':
            run_backtest()
        elif command == 'status':
            run_current_status()
        else:
            print(f"Unknown command: {command}")
            print("Valid commands: attribution, risk, forecast, backtest, status")
    else:
        # Run all reports
        run_current_status()
        run_risk_report()
        run_backtest()
        run_attribution()
        run_forecast_accuracy()

    print("\n" + "="*70)
    print("  Analysis complete.")
    print("="*70 + "\n")


if __name__ == '__main__':
    main()
