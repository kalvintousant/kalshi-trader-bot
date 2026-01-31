#!/usr/bin/env python3
"""
Performance Metrics Dashboard - Comprehensive trading analytics

Usage: python3 performance_dashboard.py [--period=all|today|week|month] [--source=api|csv]

Tracks and displays:
- Win rate (overall and by city/strategy)
- Average edge on trades
- Average EV on trades
- P&L by strategy (longshot vs conservative)
- Performance by city
- Performance trends over time

Data sources:
- api (default): Real fills from Kalshi API with NWS-inferred outcomes
- csv: Historical data from outcomes.csv (may contain stale/test data)
"""

import csv
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from dotenv import load_dotenv
load_dotenv()


def load_outcomes_from_api(period: str = 'all') -> List[Dict]:
    """Load real outcomes from Kalshi API with NWS-inferred results."""
    from src.config import Config
    from src.kalshi_client import KalshiClient
    from src.weather_data import WeatherDataAggregator, extract_threshold_from_market

    try:
        Config.validate()
    except Exception as e:
        print(f"Config error: {e}")
        return []

    client = KalshiClient()
    weather_agg = WeatherDataAggregator()

    # Get fills from API
    fills = client.get_fills(limit=500)

    now = datetime.now()
    today = now.date()

    # Period filter
    if period == 'today':
        cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == 'week':
        cutoff = now - timedelta(days=7)
    elif period == 'month':
        cutoff = now - timedelta(days=30)
    else:
        cutoff = None

    # NWS cache for efficiency
    nws_cache = {}

    outcomes = []

    for fill in fills:
        # Parse fill time
        created_time = fill.get('created_time', '')
        if created_time:
            try:
                fill_dt = datetime.fromisoformat(created_time.replace('Z', '+00:00'))
                if fill_dt.tzinfo:
                    fill_dt = fill_dt.astimezone().replace(tzinfo=None)
                if cutoff and fill_dt < cutoff:
                    continue
            except (ValueError, TypeError):
                pass

        # Only count buys
        if (fill.get('action') or 'buy').lower() != 'buy':
            continue

        ticker = fill.get('ticker', '')
        side = (fill.get('side') or 'yes').lower()
        count = int(fill.get('count', 0))
        price = int(fill.get('yes_price') or fill.get('no_price') or 0)

        # Get market info
        try:
            market = client.get_market(ticker)
        except:
            continue

        # Parse date from ticker
        market_date = None
        series_ticker = ''
        if ticker and '-' in ticker:
            parts = ticker.split('-')
            series_ticker = parts[0]
            if len(parts) >= 2:
                date_str = parts[1].upper()
                if len(date_str) >= 7:
                    try:
                        month_map = {'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4, 'MAY': 5, 'JUN': 6,
                                    'JUL': 7, 'AUG': 8, 'SEP': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12}
                        year = 2000 + int(date_str[:2])
                        month = month_map.get(date_str[2:5])
                        day = int(date_str[5:])
                        if month:
                            market_date = datetime(year, month, day).date()
                    except:
                        pass

        # Determine outcome
        status = (market.get('status') or '').lower()
        result = (market.get('result') or '').lower()

        won = None
        outcome_source = 'pending'

        # Check API result first
        if status in ('closed', 'finalized', 'settled') and result in ('yes', 'no'):
            won = (side == result)
            outcome_source = 'api'
        # Use NWS for past/today markets
        elif market_date and market_date <= today and series_ticker:
            # Get observed temp from NWS
            is_high = series_ticker.startswith('KXHIGH')
            cache_key = (series_ticker, market_date, 'high' if is_high else 'low')

            if cache_key not in nws_cache:
                if is_high:
                    obs = weather_agg.get_observed_high_for_date(series_ticker, market_date) if market_date != today else weather_agg.get_todays_observed_high(series_ticker)
                else:
                    obs = weather_agg.get_observed_low_for_date(series_ticker, market_date) if market_date != today else weather_agg.get_todays_observed_low(series_ticker)
                nws_cache[cache_key] = obs

            obs = nws_cache[cache_key]
            if obs:
                observed_temp = obs[0]
                # Get threshold from market
                threshold = extract_threshold_from_market(market)
                if threshold is None:
                    # Parse from ticker suffix
                    if len(parts) >= 3:
                        suf = parts[-1].upper()
                        try:
                            if suf.startswith('B'):
                                threshold = float(suf[1:])
                                is_above = False
                            elif suf.startswith('T'):
                                threshold = float(suf[1:])
                                is_above = True
                        except:
                            pass
                    else:
                        threshold = None
                        is_above = None
                else:
                    title = (market.get('title') or '').lower()
                    is_above = 'above' in title or '>' in title

                if threshold is not None:
                    if isinstance(threshold, tuple):
                        low, high = threshold
                        nws_result = 'yes' if low <= observed_temp < high else 'no'
                    elif is_above:
                        nws_result = 'yes' if observed_temp > threshold else 'no'
                    else:
                        nws_result = 'yes' if observed_temp < threshold else 'no'

                    won = (side == nws_result)
                    outcome_source = 'nws'

        # Skip pending trades for P&L calculation
        if won is None:
            continue

        # Calculate P&L
        if won:
            pnl = count * (100 - price) / 100.0
        else:
            pnl = -count * price / 100.0

        # Build outcome record
        outcomes.append({
            'timestamp': created_time,
            'market_ticker': ticker,
            'city': series_ticker,
            'side': side,
            'contracts': str(count),
            'entry_price': str(price),
            'won': 'YES' if won else 'NO',
            'profit_loss': f"{pnl:.2f}",
            'outcome_source': outcome_source,
        })

    return outcomes


def load_outcomes_from_csv(period: str = 'all') -> List[Dict]:
    """Load outcomes from CSV, optionally filtered by time period."""
    path = Path("data/outcomes.csv")
    if not path.exists():
        return []

    outcomes = []
    now = datetime.now()

    # Define period filter
    if period == 'today':
        cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == 'week':
        cutoff = now - timedelta(days=7)
    elif period == 'month':
        cutoff = now - timedelta(days=30)
    else:
        cutoff = None

    with open(path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Parse timestamp
            ts_str = row.get('timestamp', '')
            if ts_str:
                try:
                    ts = datetime.fromisoformat(ts_str)
                    if cutoff and ts < cutoff:
                        continue
                except (ValueError, TypeError):
                    pass
            outcomes.append(row)

    return outcomes


def classify_strategy(row: Dict) -> str:
    """Classify trade as longshot or conservative based on entry price."""
    try:
        price = int(row.get('entry_price', 0) or 0)
        # Longshot: entry price <= 10 cents
        return 'longshot' if price <= 10 else 'conservative'
    except (ValueError, TypeError):
        return 'unknown'


def extract_city(row: Dict) -> str:
    """Extract city code from market ticker or city field."""
    city = row.get('city', '')
    if city:
        # Extract just the city code (e.g., 'NY' from 'KXHIGHNY')
        for code in ['NY', 'CHI', 'MIA', 'AUS', 'LAX', 'DEN']:
            if code in city.upper():
                return code
    return city or 'Unknown'


def calculate_metrics(outcomes: List[Dict]) -> Dict:
    """Calculate comprehensive performance metrics."""
    if not outcomes:
        return {'error': 'No data available'}

    metrics = {
        'overall': {
            'total_trades': 0,
            'wins': 0,
            'losses': 0,
            'win_rate': 0.0,
            'total_pnl': 0.0,
            'avg_pnl_per_trade': 0.0,
            'total_edge': 0.0,
            'avg_edge': 0.0,
            'total_ev': 0.0,
            'avg_ev': 0.0,
            'trades_with_edge': 0,
            'trades_with_ev': 0,
        },
        'by_strategy': defaultdict(lambda: {
            'trades': 0, 'wins': 0, 'losses': 0, 'pnl': 0.0,
            'edge_sum': 0.0, 'edge_count': 0, 'ev_sum': 0.0, 'ev_count': 0
        }),
        'by_city': defaultdict(lambda: {
            'trades': 0, 'wins': 0, 'losses': 0, 'pnl': 0.0,
            'forecast_errors': []
        }),
        'by_side': defaultdict(lambda: {
            'trades': 0, 'wins': 0, 'losses': 0, 'pnl': 0.0
        }),
        'by_price_bucket': defaultdict(lambda: {
            'trades': 0, 'wins': 0, 'losses': 0, 'pnl': 0.0
        }),
        'winning_trades': [],
        'losing_trades': [],
    }

    for row in outcomes:
        # Skip rows without P&L data
        pnl_str = row.get('profit_loss', '')
        if not pnl_str:
            continue

        try:
            pnl = float(pnl_str)
        except (ValueError, TypeError):
            continue

        # Determine win/loss
        won = row.get('won', '').upper() == 'YES' or pnl > 0

        # Overall metrics
        metrics['overall']['total_trades'] += 1
        metrics['overall']['total_pnl'] += pnl

        if won:
            metrics['overall']['wins'] += 1
            metrics['winning_trades'].append((pnl, row))
        else:
            metrics['overall']['losses'] += 1
            metrics['losing_trades'].append((pnl, row))

        # Edge tracking
        edge_str = row.get('edge', '')
        if edge_str:
            try:
                edge = float(edge_str)
                metrics['overall']['total_edge'] += edge
                metrics['overall']['trades_with_edge'] += 1
            except (ValueError, TypeError):
                pass

        # EV tracking
        ev_str = row.get('ev', '')
        if ev_str:
            try:
                ev = float(ev_str)
                metrics['overall']['total_ev'] += ev
                metrics['overall']['trades_with_ev'] += 1
            except (ValueError, TypeError):
                pass

        # By strategy
        strategy = classify_strategy(row)
        metrics['by_strategy'][strategy]['trades'] += 1
        metrics['by_strategy'][strategy]['pnl'] += pnl
        if won:
            metrics['by_strategy'][strategy]['wins'] += 1
        else:
            metrics['by_strategy'][strategy]['losses'] += 1
        if edge_str:
            try:
                metrics['by_strategy'][strategy]['edge_sum'] += float(edge_str)
                metrics['by_strategy'][strategy]['edge_count'] += 1
            except (ValueError, TypeError):
                pass
        if ev_str:
            try:
                metrics['by_strategy'][strategy]['ev_sum'] += float(ev_str)
                metrics['by_strategy'][strategy]['ev_count'] += 1
            except (ValueError, TypeError):
                pass

        # By city
        city = extract_city(row)
        metrics['by_city'][city]['trades'] += 1
        metrics['by_city'][city]['pnl'] += pnl
        if won:
            metrics['by_city'][city]['wins'] += 1
        else:
            metrics['by_city'][city]['losses'] += 1

        # Track forecast errors by city
        forecast_error = row.get('forecast_error', '')
        if forecast_error:
            try:
                metrics['by_city'][city]['forecast_errors'].append(float(forecast_error))
            except (ValueError, TypeError):
                pass

        # By side (YES/NO)
        side = row.get('side', '').upper()
        if side in ('YES', 'NO'):
            metrics['by_side'][side]['trades'] += 1
            metrics['by_side'][side]['pnl'] += pnl
            if won:
                metrics['by_side'][side]['wins'] += 1
            else:
                metrics['by_side'][side]['losses'] += 1

        # By price bucket
        try:
            price = int(row.get('entry_price', 0) or 0)
            if price <= 10:
                bucket = '0-10¢'
            elif price <= 25:
                bucket = '11-25¢'
            elif price <= 50:
                bucket = '26-50¢'
            elif price <= 75:
                bucket = '51-75¢'
            else:
                bucket = '76-100¢'

            metrics['by_price_bucket'][bucket]['trades'] += 1
            metrics['by_price_bucket'][bucket]['pnl'] += pnl
            if won:
                metrics['by_price_bucket'][bucket]['wins'] += 1
            else:
                metrics['by_price_bucket'][bucket]['losses'] += 1
        except (ValueError, TypeError):
            pass

    # Calculate derived metrics
    total = metrics['overall']['total_trades']
    if total > 0:
        metrics['overall']['win_rate'] = metrics['overall']['wins'] / total
        metrics['overall']['avg_pnl_per_trade'] = metrics['overall']['total_pnl'] / total

    if metrics['overall']['trades_with_edge'] > 0:
        metrics['overall']['avg_edge'] = (
            metrics['overall']['total_edge'] / metrics['overall']['trades_with_edge']
        )

    if metrics['overall']['trades_with_ev'] > 0:
        metrics['overall']['avg_ev'] = (
            metrics['overall']['total_ev'] / metrics['overall']['trades_with_ev']
        )

    # Calculate win rates for sub-categories
    for strategy, stats in metrics['by_strategy'].items():
        if stats['trades'] > 0:
            stats['win_rate'] = stats['wins'] / stats['trades']
            stats['avg_pnl'] = stats['pnl'] / stats['trades']
            if stats['edge_count'] > 0:
                stats['avg_edge'] = stats['edge_sum'] / stats['edge_count']
            if stats['ev_count'] > 0:
                stats['avg_ev'] = stats['ev_sum'] / stats['ev_count']

    for city, stats in metrics['by_city'].items():
        if stats['trades'] > 0:
            stats['win_rate'] = stats['wins'] / stats['trades']
            stats['avg_pnl'] = stats['pnl'] / stats['trades']
            if stats['forecast_errors']:
                stats['avg_forecast_error'] = sum(stats['forecast_errors']) / len(stats['forecast_errors'])

    for side, stats in metrics['by_side'].items():
        if stats['trades'] > 0:
            stats['win_rate'] = stats['wins'] / stats['trades']
            stats['avg_pnl'] = stats['pnl'] / stats['trades']

    for bucket, stats in metrics['by_price_bucket'].items():
        if stats['trades'] > 0:
            stats['win_rate'] = stats['wins'] / stats['trades']
            stats['avg_pnl'] = stats['pnl'] / stats['trades']

    # Sort winning/losing trades by P&L
    metrics['winning_trades'].sort(key=lambda x: x[0], reverse=True)
    metrics['losing_trades'].sort(key=lambda x: x[0])

    return metrics


def print_dashboard(metrics: Dict, period: str):
    """Print formatted dashboard."""
    if 'error' in metrics:
        print(f"\n❌ {metrics['error']}\n")
        return

    period_label = {
        'all': 'All Time',
        'today': 'Today',
        'week': 'Last 7 Days',
        'month': 'Last 30 Days'
    }.get(period, period)

    print("\n" + "=" * 70)
    print(f"📊 PERFORMANCE DASHBOARD — {period_label}")
    print("=" * 70)

    # Overall Summary
    o = metrics['overall']
    print(f"\n{'─' * 35}")
    print("OVERALL SUMMARY")
    print(f"{'─' * 35}")
    print(f"  Total Trades:     {o['total_trades']}")
    print(f"  Wins / Losses:    {o['wins']} / {o['losses']}")
    print(f"  Win Rate:         {o['win_rate']:.1%}")
    print(f"  Total P&L:        ${o['total_pnl']:.2f}")
    print(f"  Avg P&L/Trade:    ${o['avg_pnl_per_trade']:.3f}")
    if o['avg_edge'] != 0:
        print(f"  Avg Edge:         {o['avg_edge']:.1f}%")
    if o['avg_ev'] != 0:
        print(f"  Avg EV:           ${o['avg_ev']:.3f}")

    # By Strategy
    if metrics['by_strategy']:
        print(f"\n{'─' * 35}")
        print("BY STRATEGY")
        print(f"{'─' * 35}")
        for strategy, stats in sorted(metrics['by_strategy'].items()):
            win_rate = stats.get('win_rate', 0)
            avg_edge = stats.get('avg_edge', 0)
            print(f"  {strategy.upper():12} | {stats['trades']:4} trades | "
                  f"{stats['wins']:3}W/{stats['losses']:3}L | "
                  f"{win_rate:.1%} | ${stats['pnl']:+.2f}")

    # By City
    if metrics['by_city']:
        print(f"\n{'─' * 35}")
        print("BY CITY")
        print(f"{'─' * 35}")
        # Sort by P&L descending
        sorted_cities = sorted(metrics['by_city'].items(), key=lambda x: x[1]['pnl'], reverse=True)
        for city, stats in sorted_cities:
            win_rate = stats.get('win_rate', 0)
            forecast_err = stats.get('avg_forecast_error')
            err_str = f" | Err: {forecast_err:.1f}°" if forecast_err else ""
            print(f"  {city:6} | {stats['trades']:4} trades | "
                  f"{stats['wins']:3}W/{stats['losses']:3}L | "
                  f"{win_rate:.1%} | ${stats['pnl']:+.2f}{err_str}")

    # By Side (YES/NO)
    if metrics['by_side']:
        print(f"\n{'─' * 35}")
        print("BY SIDE")
        print(f"{'─' * 35}")
        for side in ['YES', 'NO']:
            if side in metrics['by_side']:
                stats = metrics['by_side'][side]
                win_rate = stats.get('win_rate', 0)
                print(f"  {side:4} | {stats['trades']:4} trades | "
                      f"{stats['wins']:3}W/{stats['losses']:3}L | "
                      f"{win_rate:.1%} | ${stats['pnl']:+.2f}")

    # By Price Bucket
    if metrics['by_price_bucket']:
        print(f"\n{'─' * 35}")
        print("BY ENTRY PRICE")
        print(f"{'─' * 35}")
        bucket_order = ['0-10¢', '11-25¢', '26-50¢', '51-75¢', '76-100¢']
        for bucket in bucket_order:
            if bucket in metrics['by_price_bucket']:
                stats = metrics['by_price_bucket'][bucket]
                win_rate = stats.get('win_rate', 0)
                print(f"  {bucket:8} | {stats['trades']:4} trades | "
                      f"{stats['wins']:3}W/{stats['losses']:3}L | "
                      f"{win_rate:.1%} | ${stats['pnl']:+.2f}")

    # Top Winners & Losers
    if metrics['winning_trades'] or metrics['losing_trades']:
        print(f"\n{'─' * 35}")
        print("TOP 5 WINNERS")
        print(f"{'─' * 35}")
        for pnl, row in metrics['winning_trades'][:5]:
            ticker = row.get('market_ticker', 'Unknown')[:35]
            side = row.get('side', '?').upper()
            print(f"  ${pnl:+.2f} | {side:3} | {ticker}")

        print(f"\n{'─' * 35}")
        print("TOP 5 LOSERS")
        print(f"{'─' * 35}")
        for pnl, row in metrics['losing_trades'][:5]:
            ticker = row.get('market_ticker', 'Unknown')[:35]
            side = row.get('side', '?').upper()
            print(f"  ${pnl:+.2f} | {side:3} | {ticker}")

    # Insights
    print(f"\n{'─' * 35}")
    print("INSIGHTS")
    print(f"{'─' * 35}")

    # Best/worst city
    if metrics['by_city']:
        sorted_cities = sorted(metrics['by_city'].items(), key=lambda x: x[1].get('win_rate', 0), reverse=True)
        best_city = sorted_cities[0]
        worst_city = sorted_cities[-1]
        print(f"  Best City:   {best_city[0]} ({best_city[1].get('win_rate', 0):.1%} win rate)")
        print(f"  Worst City:  {worst_city[0]} ({worst_city[1].get('win_rate', 0):.1%} win rate)")

    # Best/worst strategy
    if metrics['by_strategy']:
        sorted_strats = sorted(metrics['by_strategy'].items(), key=lambda x: x[1].get('win_rate', 0), reverse=True)
        best_strat = sorted_strats[0]
        print(f"  Best Strat:  {best_strat[0]} ({best_strat[1].get('win_rate', 0):.1%} win rate)")

    # YES vs NO performance
    if 'YES' in metrics['by_side'] and 'NO' in metrics['by_side']:
        yes_wr = metrics['by_side']['YES'].get('win_rate', 0)
        no_wr = metrics['by_side']['NO'].get('win_rate', 0)
        if yes_wr > no_wr + 0.1:
            print(f"  Side Bias:   YES side outperforming ({yes_wr:.1%} vs {no_wr:.1%})")
        elif no_wr > yes_wr + 0.1:
            print(f"  Side Bias:   NO side outperforming ({no_wr:.1%} vs {yes_wr:.1%})")

    # Price bucket insights
    if metrics['by_price_bucket']:
        best_bucket = max(metrics['by_price_bucket'].items(),
                         key=lambda x: x[1].get('win_rate', 0))
        worst_bucket = min(metrics['by_price_bucket'].items(),
                          key=lambda x: x[1].get('win_rate', 0))
        print(f"  Best Price:  {best_bucket[0]} ({best_bucket[1].get('win_rate', 0):.1%} win rate)")
        print(f"  Worst Price: {worst_bucket[0]} ({worst_bucket[1].get('win_rate', 0):.1%} win rate)")

    print("\n" + "=" * 70 + "\n")


def main():
    parser = argparse.ArgumentParser(description='Performance Metrics Dashboard')
    parser.add_argument('--period', '-p', default='all',
                       choices=['all', 'today', 'week', 'month'],
                       help='Time period to analyze (default: all)')
    parser.add_argument('--source', '-s', default='api',
                       choices=['api', 'csv'],
                       help='Data source: api (real Kalshi fills) or csv (outcomes.csv)')
    args = parser.parse_args()

    if args.source == 'api':
        print("\n📡 Loading data from Kalshi API (with NWS-inferred outcomes)...")
        outcomes = load_outcomes_from_api(args.period)
        if not outcomes:
            print(f"\n❌ No fills found from Kalshi API\n")
            return
    else:
        outcomes = load_outcomes_from_csv(args.period)
        if not outcomes:
            print(f"\n❌ No outcome data found in data/outcomes.csv\n")
            return

    metrics = calculate_metrics(outcomes)
    print_dashboard(metrics, args.period)


if __name__ == "__main__":
    main()
