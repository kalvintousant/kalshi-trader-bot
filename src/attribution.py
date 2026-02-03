"""
Performance Attribution Engine

Analyzes trading P&L by various dimensions:
- City
- Threshold type (HIGH vs LOW, Below vs Above)
- Time to settlement
- Entry price bucket
- Forecast source accuracy
- Strategy mode (conservative vs longshot)
- Day of week / Hour of day
"""

import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
import logging
import re

logger = logging.getLogger(__name__)


class PerformanceAttribution:
    """Analyze trading performance by various dimensions"""

    def __init__(self, db_path: str = "data/historical.db"):
        self.db_path = db_path

    def _get_trades(self, start_date: str = None, end_date: str = None,
                    settled_only: bool = True) -> List[Dict]:
        """Get trades from database"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        try:
            query = "SELECT * FROM trades WHERE 1=1"
            params = []

            if settled_only:
                query += " AND settled = 1"
            if start_date:
                query += " AND timestamp >= ?"
                params.append(start_date)
            if end_date:
                query += " AND timestamp <= ?"
                params.append(end_date)

            query += " ORDER BY timestamp"
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def _parse_ticker(self, ticker: str) -> Dict:
        """
        Parse ticker into components

        Example: KXHIGHNY-26FEB04-B32.5
        Returns: {city: 'NY', type: 'HIGH', date: '26FEB04', threshold_type: 'B', threshold: 32.5}
        """
        result = {
            'city': None,
            'market_type': None,
            'date': None,
            'threshold_type': None,
            'threshold': None
        }

        # Match pattern like KXHIGHNY-26FEB04-B32.5 or KXLOWCHI-26FEB03-T25
        match = re.match(r'KX(HIGH|LOW)(\w+)-(\w+)-([BT])(\d+\.?\d*)', ticker)
        if match:
            result['market_type'] = match.group(1)  # HIGH or LOW
            result['city'] = match.group(2)  # NY, CHI, MIA, etc.
            result['date'] = match.group(3)  # 26FEB04
            result['threshold_type'] = match.group(4)  # B (below) or T (at/above)
            result['threshold'] = float(match.group(5))

        return result

    def _bucket_price(self, price: int) -> str:
        """Bucket entry price"""
        if price <= 15:
            return "1-15¢"
        elif price <= 25:
            return "16-25¢"
        elif price <= 35:
            return "26-35¢"
        elif price <= 50:
            return "36-50¢"
        elif price <= 75:
            return "51-75¢"
        else:
            return "76-100¢"

    def _bucket_edge(self, edge: float) -> str:
        """Bucket edge percentage"""
        if edge is None:
            return "Unknown"
        elif edge < 10:
            return "0-10%"
        elif edge < 20:
            return "10-20%"
        elif edge < 30:
            return "20-30%"
        else:
            return "30%+"

    def by_city(self, start_date: str = None, end_date: str = None) -> Dict[str, Dict]:
        """
        Analyze P&L by city

        Returns:
            Dict mapping city -> {trades, wins, losses, pnl, win_rate, avg_pnl}
        """
        trades = self._get_trades(start_date, end_date)
        results = defaultdict(lambda: {'trades': 0, 'wins': 0, 'losses': 0, 'pnl': 0.0})

        for trade in trades:
            parsed = self._parse_ticker(trade['ticker'])
            city = parsed.get('city', 'Unknown')

            results[city]['trades'] += 1
            results[city]['pnl'] += trade.get('pnl', 0) or 0

            if trade.get('pnl', 0) > 0:
                results[city]['wins'] += 1
            elif trade.get('pnl', 0) < 0:
                results[city]['losses'] += 1

        # Calculate derived metrics
        for city, data in results.items():
            total = data['wins'] + data['losses']
            data['win_rate'] = round(data['wins'] / total * 100, 1) if total > 0 else 0
            data['avg_pnl'] = round(data['pnl'] / data['trades'], 4) if data['trades'] > 0 else 0
            data['pnl'] = round(data['pnl'], 2)

        return dict(sorted(results.items(), key=lambda x: x[1]['pnl'], reverse=True))

    def by_market_type(self, start_date: str = None, end_date: str = None) -> Dict[str, Dict]:
        """
        Analyze P&L by market type (HIGH vs LOW)

        Returns:
            Dict mapping type -> performance metrics
        """
        trades = self._get_trades(start_date, end_date)
        results = defaultdict(lambda: {'trades': 0, 'wins': 0, 'losses': 0, 'pnl': 0.0})

        for trade in trades:
            parsed = self._parse_ticker(trade['ticker'])
            market_type = parsed.get('market_type', 'Unknown')

            results[market_type]['trades'] += 1
            results[market_type]['pnl'] += trade.get('pnl', 0) or 0

            if trade.get('pnl', 0) > 0:
                results[market_type]['wins'] += 1
            elif trade.get('pnl', 0) < 0:
                results[market_type]['losses'] += 1

        for mtype, data in results.items():
            total = data['wins'] + data['losses']
            data['win_rate'] = round(data['wins'] / total * 100, 1) if total > 0 else 0
            data['avg_pnl'] = round(data['pnl'] / data['trades'], 4) if data['trades'] > 0 else 0
            data['pnl'] = round(data['pnl'], 2)

        return dict(results)

    def by_threshold_type(self, start_date: str = None, end_date: str = None) -> Dict[str, Dict]:
        """
        Analyze P&L by threshold type (Below vs At/Above)

        B = Below threshold (YES wins if temp < threshold)
        T = At or above threshold (YES wins if temp >= threshold)
        """
        trades = self._get_trades(start_date, end_date)
        results = defaultdict(lambda: {'trades': 0, 'wins': 0, 'losses': 0, 'pnl': 0.0})

        for trade in trades:
            parsed = self._parse_ticker(trade['ticker'])
            threshold_type = parsed.get('threshold_type', 'Unknown')
            label = 'Below (B)' if threshold_type == 'B' else 'At/Above (T)' if threshold_type == 'T' else 'Unknown'

            results[label]['trades'] += 1
            results[label]['pnl'] += trade.get('pnl', 0) or 0

            if trade.get('pnl', 0) > 0:
                results[label]['wins'] += 1
            elif trade.get('pnl', 0) < 0:
                results[label]['losses'] += 1

        for label, data in results.items():
            total = data['wins'] + data['losses']
            data['win_rate'] = round(data['wins'] / total * 100, 1) if total > 0 else 0
            data['avg_pnl'] = round(data['pnl'] / data['trades'], 4) if data['trades'] > 0 else 0
            data['pnl'] = round(data['pnl'], 2)

        return dict(results)

    def by_entry_price(self, start_date: str = None, end_date: str = None) -> Dict[str, Dict]:
        """
        Analyze P&L by entry price bucket

        This is crucial - shows which price ranges are profitable.
        """
        trades = self._get_trades(start_date, end_date)
        results = defaultdict(lambda: {'trades': 0, 'wins': 0, 'losses': 0, 'pnl': 0.0})

        for trade in trades:
            bucket = self._bucket_price(trade.get('price', 50))

            results[bucket]['trades'] += 1
            results[bucket]['pnl'] += trade.get('pnl', 0) or 0

            if trade.get('pnl', 0) > 0:
                results[bucket]['wins'] += 1
            elif trade.get('pnl', 0) < 0:
                results[bucket]['losses'] += 1

        for bucket, data in results.items():
            total = data['wins'] + data['losses']
            data['win_rate'] = round(data['wins'] / total * 100, 1) if total > 0 else 0
            data['avg_pnl'] = round(data['pnl'] / data['trades'], 4) if data['trades'] > 0 else 0
            data['pnl'] = round(data['pnl'], 2)

        # Sort by price bucket order
        bucket_order = ["1-15¢", "16-25¢", "26-35¢", "36-50¢", "51-75¢", "76-100¢"]
        return {k: results[k] for k in bucket_order if k in results}

    def by_strategy_mode(self, start_date: str = None, end_date: str = None) -> Dict[str, Dict]:
        """
        Analyze P&L by strategy mode (conservative vs longshot)
        """
        trades = self._get_trades(start_date, end_date)
        results = defaultdict(lambda: {'trades': 0, 'wins': 0, 'losses': 0, 'pnl': 0.0})

        for trade in trades:
            mode = trade.get('strategy_mode', 'unknown')

            results[mode]['trades'] += 1
            results[mode]['pnl'] += trade.get('pnl', 0) or 0

            if trade.get('pnl', 0) > 0:
                results[mode]['wins'] += 1
            elif trade.get('pnl', 0) < 0:
                results[mode]['losses'] += 1

        for mode, data in results.items():
            total = data['wins'] + data['losses']
            data['win_rate'] = round(data['wins'] / total * 100, 1) if total > 0 else 0
            data['avg_pnl'] = round(data['pnl'] / data['trades'], 4) if data['trades'] > 0 else 0
            data['pnl'] = round(data['pnl'], 2)

        return dict(results)

    def by_edge_bucket(self, start_date: str = None, end_date: str = None) -> Dict[str, Dict]:
        """
        Analyze P&L by edge percentage bucket

        Shows if higher edge trades actually perform better.
        """
        trades = self._get_trades(start_date, end_date)
        results = defaultdict(lambda: {'trades': 0, 'wins': 0, 'losses': 0, 'pnl': 0.0})

        for trade in trades:
            bucket = self._bucket_edge(trade.get('edge'))

            results[bucket]['trades'] += 1
            results[bucket]['pnl'] += trade.get('pnl', 0) or 0

            if trade.get('pnl', 0) > 0:
                results[bucket]['wins'] += 1
            elif trade.get('pnl', 0) < 0:
                results[bucket]['losses'] += 1

        for bucket, data in results.items():
            total = data['wins'] + data['losses']
            data['win_rate'] = round(data['wins'] / total * 100, 1) if total > 0 else 0
            data['avg_pnl'] = round(data['pnl'] / data['trades'], 4) if data['trades'] > 0 else 0
            data['pnl'] = round(data['pnl'], 2)

        # Sort by edge bucket order
        bucket_order = ["0-10%", "10-20%", "20-30%", "30%+", "Unknown"]
        return {k: results[k] for k in bucket_order if k in results}

    def by_side(self, start_date: str = None, end_date: str = None) -> Dict[str, Dict]:
        """
        Analyze P&L by side (YES vs NO)
        """
        trades = self._get_trades(start_date, end_date)
        results = defaultdict(lambda: {'trades': 0, 'wins': 0, 'losses': 0, 'pnl': 0.0})

        for trade in trades:
            side = trade.get('side', 'unknown').upper()

            results[side]['trades'] += 1
            results[side]['pnl'] += trade.get('pnl', 0) or 0

            if trade.get('pnl', 0) > 0:
                results[side]['wins'] += 1
            elif trade.get('pnl', 0) < 0:
                results[side]['losses'] += 1

        for side, data in results.items():
            total = data['wins'] + data['losses']
            data['win_rate'] = round(data['wins'] / total * 100, 1) if total > 0 else 0
            data['avg_pnl'] = round(data['pnl'] / data['trades'], 4) if data['trades'] > 0 else 0
            data['pnl'] = round(data['pnl'], 2)

        return dict(results)

    def by_hour_of_day(self, start_date: str = None, end_date: str = None) -> Dict[int, Dict]:
        """
        Analyze P&L by hour of day (when trade was placed)

        Shows if certain times of day are more profitable.
        """
        trades = self._get_trades(start_date, end_date)
        results = defaultdict(lambda: {'trades': 0, 'wins': 0, 'losses': 0, 'pnl': 0.0})

        for trade in trades:
            try:
                ts = datetime.fromisoformat(trade['timestamp'].replace('Z', '+00:00'))
                hour = ts.hour
            except:
                hour = -1

            results[hour]['trades'] += 1
            results[hour]['pnl'] += trade.get('pnl', 0) or 0

            if trade.get('pnl', 0) > 0:
                results[hour]['wins'] += 1
            elif trade.get('pnl', 0) < 0:
                results[hour]['losses'] += 1

        for hour, data in results.items():
            total = data['wins'] + data['losses']
            data['win_rate'] = round(data['wins'] / total * 100, 1) if total > 0 else 0
            data['avg_pnl'] = round(data['pnl'] / data['trades'], 4) if data['trades'] > 0 else 0
            data['pnl'] = round(data['pnl'], 2)

        return dict(sorted(results.items()))

    def by_day_of_week(self, start_date: str = None, end_date: str = None) -> Dict[str, Dict]:
        """
        Analyze P&L by day of week
        """
        trades = self._get_trades(start_date, end_date)
        results = defaultdict(lambda: {'trades': 0, 'wins': 0, 'losses': 0, 'pnl': 0.0})
        days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

        for trade in trades:
            try:
                ts = datetime.fromisoformat(trade['timestamp'].replace('Z', '+00:00'))
                day = days[ts.weekday()]
            except:
                day = 'Unknown'

            results[day]['trades'] += 1
            results[day]['pnl'] += trade.get('pnl', 0) or 0

            if trade.get('pnl', 0) > 0:
                results[day]['wins'] += 1
            elif trade.get('pnl', 0) < 0:
                results[day]['losses'] += 1

        for day, data in results.items():
            total = data['wins'] + data['losses']
            data['win_rate'] = round(data['wins'] / total * 100, 1) if total > 0 else 0
            data['avg_pnl'] = round(data['pnl'] / data['trades'], 4) if data['trades'] > 0 else 0
            data['pnl'] = round(data['pnl'], 2)

        return {d: results[d] for d in days if d in results}

    def generate_full_report(self, start_date: str = None, end_date: str = None) -> Dict:
        """
        Generate comprehensive attribution report

        Returns:
            Dictionary with all attribution breakdowns
        """
        return {
            'by_city': self.by_city(start_date, end_date),
            'by_market_type': self.by_market_type(start_date, end_date),
            'by_threshold_type': self.by_threshold_type(start_date, end_date),
            'by_entry_price': self.by_entry_price(start_date, end_date),
            'by_strategy_mode': self.by_strategy_mode(start_date, end_date),
            'by_edge_bucket': self.by_edge_bucket(start_date, end_date),
            'by_side': self.by_side(start_date, end_date),
            'by_hour_of_day': self.by_hour_of_day(start_date, end_date),
            'by_day_of_week': self.by_day_of_week(start_date, end_date)
        }

    def print_report(self, start_date: str = None, end_date: str = None):
        """Print formatted attribution report"""
        report = self.generate_full_report(start_date, end_date)

        def print_section(title: str, data: Dict):
            print(f"\n{'='*60}")
            print(f"  {title}")
            print(f"{'='*60}")
            if not data:
                print("  No data")
                return

            # Header
            print(f"  {'Category':<15} {'Trades':>7} {'Win%':>7} {'P&L':>10} {'Avg P&L':>10}")
            print(f"  {'-'*15} {'-'*7} {'-'*7} {'-'*10} {'-'*10}")

            for category, metrics in data.items():
                cat_str = str(category)[:15]
                print(f"  {cat_str:<15} {metrics['trades']:>7} {metrics['win_rate']:>6.1f}% ${metrics['pnl']:>9.2f} ${metrics['avg_pnl']:>9.4f}")

        print_section("BY CITY", report['by_city'])
        print_section("BY MARKET TYPE (HIGH/LOW)", report['by_market_type'])
        print_section("BY THRESHOLD TYPE (Below/At)", report['by_threshold_type'])
        print_section("BY ENTRY PRICE", report['by_entry_price'])
        print_section("BY STRATEGY MODE", report['by_strategy_mode'])
        print_section("BY EDGE BUCKET", report['by_edge_bucket'])
        print_section("BY SIDE (YES/NO)", report['by_side'])
        print_section("BY DAY OF WEEK", report['by_day_of_week'])


# Convenience function
def get_attribution() -> PerformanceAttribution:
    """Get a performance attribution instance"""
    return PerformanceAttribution()
