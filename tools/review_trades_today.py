#!/usr/bin/env python3
"""
Review today's trades: what we got right vs wrong (and pending).

Usage: python3 review_trades_today.py

Fetches today's fills from Kalshi API. For settled markets uses API result.
For unsettled markets whose date has passed (or today), uses NWS observed
high/low to compute the result and reports right/wrong.
"""

import csv
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from src.config import Config
from src.kalshi_client import KalshiClient
from src.weather_data import WeatherDataAggregator, extract_threshold_from_market


# Parse date from ticker part e.g. "26JAN30" -> Jan 30, 2026
MONTH_MAP = {'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4, 'MAY': 5, 'JUN': 6,
             'JUL': 7, 'AUG': 8, 'SEP': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12}


def parse_date_from_ticker(ticker: str):
    """Return (date, series_ticker) or (None, None)."""
    if not ticker or '-' not in ticker:
        return None, None
    parts = ticker.split('-')
    series_ticker = parts[0].strip()
    if len(parts) < 2:
        return None, series_ticker
    date_str = parts[1].strip().upper()
    if len(date_str) < 7:
        return None, series_ticker
    try:
        year = 2000 + int(date_str[:2])
        month_str = date_str[2:5]
        day = int(date_str[5:])
        if month_str not in MONTH_MAP:
            return None, series_ticker
        return datetime(year, MONTH_MAP[month_str], day).date(), series_ticker
    except (ValueError, IndexError):
        return None, series_ticker


def parse_fill_time(created_time: str):
    """Parse ISO created_time to datetime (naive local)."""
    if not created_time:
        return None
    try:
        dt = datetime.fromisoformat(created_time.replace("Z", "+00:00"))
        if dt.tzinfo:
            dt = dt.astimezone().replace(tzinfo=None)
        return dt
    except (ValueError, TypeError):
        return None


def parse_threshold_from_ticker(ticker: str):
    """Fallback: parse threshold from ticker suffix e.g. B18.5 -> (18.5, False), T45 -> (45, True)."""
    if not ticker or '-' not in ticker:
        return None, None
    parts = ticker.split('-')
    if len(parts) < 3:
        return None, None
    suf = parts[-1].strip().upper()
    try:
        if suf.startswith('B'):
            return float(suf[1:]), False  # below
        if suf.startswith('T'):
            return float(suf[1:]), True   # above
    except ValueError:
        pass
    return None, None


def compute_result_from_nws(
    market: dict,
    market_date,
    series_ticker: str,
    ticker: str,
    weather_agg: WeatherDataAggregator,
    nws_cache: dict,
) -> str:
    """
    Use NWS observed high/low for market_date to determine YES/NO result.
    Returns 'yes', 'no', or '' if cannot determine.
    """
    title = (market.get('title') or '').lower()
    is_high = series_ticker.startswith('KXHIGH')
    is_low = series_ticker.startswith('KXLOW')
    threshold = extract_threshold_from_market(market)
    is_above = 'above' in title or '>' in title
    if threshold is None:
        # Fallback: parse from ticker e.g. B18.5, T45
        th, above = parse_threshold_from_ticker(ticker)
        if th is not None:
            threshold = th
            is_above = above
        else:
            return ''
    is_range = isinstance(threshold, tuple)
    from datetime import datetime as dt_now
    today_date = dt_now.now().date()
    cache_key = (series_ticker, market_date, 'high' if is_high else 'low')
    if cache_key not in nws_cache:
        if is_high:
            # Use today's method when date is today (same code path as summary)
            obs = weather_agg.get_todays_observed_high(series_ticker) if market_date == today_date else weather_agg.get_observed_high_for_date(series_ticker, market_date)
        elif is_low:
            obs = weather_agg.get_todays_observed_low(series_ticker) if market_date == today_date else weather_agg.get_observed_low_for_date(series_ticker, market_date)
        else:
            return ''
        nws_cache[cache_key] = obs
    obs = nws_cache[cache_key]
    if not obs:
        return ''
    observed_temp = obs[0]
    if is_range:
        low, high = threshold
        if low <= observed_temp < high:
            return 'yes'
        return 'no'
    if is_above:
        return 'yes' if observed_temp > threshold else 'no'
    return 'yes' if observed_temp < threshold else 'no'


def compute_single_fill_pnl(
    client: KalshiClient,
    weather_agg: WeatherDataAggregator,
    fill: dict,
    as_of_date,
    nws_cache: dict,
):
    """
    Compute P&L for one fill. Uses API result if settled, NWS if past/today and unsettled.
    Returns (pnl, source) where source is 'API', 'NWS', or (None, 'pending') if outcome unknown.
    """
    ticker = fill.get("ticker") or fill.get("market_ticker") or "?"
    side = (fill.get("side") or "yes").lower()
    count = int(fill.get("count", 0))
    price = int(fill.get("yes_price") or fill.get("no_price") or fill.get("price", 0))
    try:
        market = client.get_market(ticker)
    except Exception:
        return (None, "pending")
    market_date, series_ticker = parse_date_from_ticker(ticker)
    status = (market.get("status") or "").lower()
    result = (market.get("result") or "").lower()
    if status in ("closed", "finalized", "settled") and result in ("yes", "no"):
        won = side == result
        pnl = count * (100 - price) / 100.0 if won else -count * price / 100.0
        return (pnl, "API")
    if market_date and market_date > as_of_date:
        return (None, "pending")
    if market_date and market_date <= as_of_date and series_ticker:
        result_nws = compute_result_from_nws(
            market, market_date, series_ticker, ticker, weather_agg, nws_cache
        )
        if result_nws:
            won = side == result_nws
            pnl = count * (100 - price) / 100.0 if won else -count * price / 100.0
            return (pnl, "NWS")
    return (None, "pending")


def compute_today_fill_pnl(client: KalshiClient, weather_agg: WeatherDataAggregator):
    """
    Compute today's P&L from fills using API result (settled) + NWS inferred (past/today).
    Pending (future or no data) is excluded from P&L.

    Returns:
        (pnl_total, n_right, n_wrong, n_pending, right_list, wrong_list, pending_list, nws_used)
        where pnl_total = sum of right PnL + sum of wrong PnL only (pending not included).
    """
    today = datetime.now().date()
    nws_cache = {}
    fills = client.get_fills(limit=200)
    today_fills = []
    for f in fills:
        created = parse_fill_time(f.get("created_time"))
        if not created or created.date() != today:
            continue
        if (f.get("action") or "buy").lower() != "buy":
            continue
        today_fills.append(f)

    right = []
    wrong = []
    pending = []
    nws_used = 0

    for f in today_fills:
        ticker = f.get("ticker") or f.get("market_ticker") or "?"
        side = (f.get("side") or "yes").lower()
        count = int(f.get("count", 0))
        price = int(f.get("yes_price") or f.get("no_price") or f.get("price", 0))
        try:
            market = client.get_market(ticker)
        except Exception:
            pending.append((f, ticker, side, "?", "could not fetch market", None))
            continue

        market_date, series_ticker = parse_date_from_ticker(ticker)
        status = (market.get("status") or "").lower()
        result = (market.get("result") or "").lower()

        # 1) Already settled on API
        if status in ("closed", "finalized", "settled") and result in ("yes", "no"):
            won = (side == result)
            pnl = count * (100 - price) / 100.0 if won else -count * price / 100.0
            if won:
                right.append((f, ticker, side, result, pnl, "API"))
            else:
                wrong.append((f, ticker, side, result, pnl, "API"))
            continue

        # 2) Future date: can't know yet
        if market_date and market_date > today:
            pending.append((f, ticker, side, "-", "future date", None))
            continue

        # 3) Past or today: compute from NWS
        if market_date and market_date <= today and series_ticker:
            result_nws = compute_result_from_nws(market, market_date, series_ticker, ticker, weather_agg, nws_cache)
            if result_nws:
                nws_used += 1
                won = (side == result_nws)
                pnl = count * (100 - price) / 100.0 if won else -count * price / 100.0
                if won:
                    right.append((f, ticker, side, result_nws, pnl, "NWS"))
                else:
                    wrong.append((f, ticker, side, result_nws, pnl, "NWS"))
                continue

        pending.append((f, ticker, side, "-", "no NWS data or unknown format", None))

    pnl_right = sum(x[4] for x in right)
    pnl_wrong = sum(x[4] for x in wrong)
    pnl_total = pnl_right + pnl_wrong  # Pending is never included in P&L
    n_right = len(right)
    n_wrong = len(wrong)
    n_pending = len(pending)
    return (pnl_total, n_right, n_wrong, n_pending, right, wrong, pending, nws_used)


def main():
    today = datetime.now().date()
    print("\n" + "=" * 70)
    print(f"📋 TRADE REVIEW — {today}  (NWS used for unsettled past/today)")
    print("=" * 70)

    try:
        Config.validate()
    except Exception as e:
        print(f"\n❌ Config error: {e}\n")
        return

    try:
        client = KalshiClient()
    except Exception as e:
        print(f"\n❌ Could not create API client: {e}\n")
        return

    weather_agg = WeatherDataAggregator()
    pnl_total, n_right, n_wrong, n_pending, right, wrong, pending, nws_used = compute_today_fill_pnl(client, weather_agg)

    if n_right + n_wrong + n_pending == 0:
        print("\n   No buys today.\n")
        return

    # Summary — P&L includes only settled + NWS inferred; pending excluded
    print(f"\n   Today's buys: {n_right + n_wrong + n_pending}")
    print(f"   ✅ Right (won):  {n_right}  |  P&L: ${sum(x[4] for x in right):.2f}")
    print(f"   ❌ Wrong (lost): {n_wrong}  |  P&L: ${sum(x[4] for x in wrong):.2f}")
    print(f"   ⏳ Pending:      {n_pending}  (excluded from P&L)")
    if n_right + n_wrong > 0:
        print(f"   Net P&L (excludes pending): ${pnl_total:.2f}")
    if nws_used:
        print(f"   (NWS used for {nws_used} unsettled past/today markets)")

    # NWS report summary for all cities (today)
    from src.config import Config as C
    today = datetime.now().date()
    print("\n   --- NWS OBSERVED (today, local) ---")
    for series in C.WEATHER_SERIES:
        if series.startswith("KXHIGH"):
            obs = weather_agg.get_observed_high_for_date(series, today)
            city = series.replace("KXHIGH", "").replace("KXLOW", "")
            if obs:
                print(f"      {series}: high {obs[0]:.1f}°F (at {obs[1].strftime('%H:%M')} local)")
            else:
                print(f"      {series}: high — no data")
        elif series.startswith("KXLOW"):
            obs = weather_agg.get_observed_low_for_date(series, today)
            if obs:
                print(f"      {series}: low  {obs[0]:.1f}°F (at {obs[1].strftime('%H:%M')} local)")
            else:
                print(f"      {series}: low  — no data")

    # Infer longshot vs conservative from fill price (longshot typically ≤10¢)
    def _mode(fill_tuple):
        f = fill_tuple[0]
        price = int(f.get("yes_price") or f.get("no_price") or f.get("price") or 0)
        return "longshot" if price <= 10 else "conservative"
    if right:
        print("\n   --- RIGHT ---")
        for r in right:
            ticker, side, result, pnl, source = r[1], r[2], r[3], r[4], r[5]
            mode = _mode(r)
            print(f"      ✅ {ticker}  {side.upper()} → {result.upper()}  P&L ${pnl:.2f}  ({source}, {mode})")
    if wrong:
        print("\n   --- WRONG ---")
        n_wrong_longshot = sum(1 for w in wrong if _mode(w) == "longshot")
        n_wrong_conv = len(wrong) - n_wrong_longshot
        if wrong:
            print(f"      (Longshot losses: {n_wrong_longshot}  |  Conservative losses: {n_wrong_conv})")
        for w in wrong:
            ticker, side, result, pnl, source = w[1], w[2], w[3], w[4], w[5]
            mode = _mode(w)
            print(f"      ❌ {ticker}  {side.upper()} → {result.upper()}  P&L ${pnl:.2f}  ({source}, {mode})")
    if pending:
        print("\n   --- PENDING ---")
        for _, ticker, side, _, reason, _ in pending[:20]:
            print(f"      ⏳ {ticker}  {side.upper()}  ({reason})")
        if len(pending) > 20:
            print(f"      ... and {len(pending) - 20} more")

    print("\n" + "=" * 70 + "\n")


if __name__ == "__main__":
    main()
