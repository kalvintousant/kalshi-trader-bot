"""
Backtesting Framework for Kalshi Weather Trading

Provides:
- Historical data storage and retrieval
- Strategy replay engine
- Performance metrics (Sharpe, Sortino, max drawdown, etc.)
"""

import json
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import math
import logging

logger = logging.getLogger(__name__)


class HistoricalDataStore:
    """SQLite-based storage for historical market data, forecasts, and outcomes"""

    def __init__(self, db_path: str = "data/historical.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

    def _init_db(self):
        """Initialize database schema"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Market snapshots - orderbook state at a point in time
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS market_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                ticker TEXT NOT NULL,
                yes_price INTEGER,
                no_price INTEGER,
                yes_bid INTEGER,
                yes_ask INTEGER,
                no_bid INTEGER,
                no_ask INTEGER,
                volume INTEGER,
                open_interest INTEGER,
                UNIQUE(timestamp, ticker)
            )
        """)

        # Forecasts - what we predicted
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS forecasts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                ticker TEXT NOT NULL,
                city TEXT NOT NULL,
                target_date TEXT NOT NULL,
                source TEXT NOT NULL,
                forecast_temp REAL NOT NULL,
                forecast_low REAL,
                forecast_high REAL,
                ensemble_std REAL,
                UNIQUE(timestamp, ticker, source)
            )
        """)

        # Actual outcomes - what actually happened
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS outcomes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL UNIQUE,
                city TEXT NOT NULL,
                target_date TEXT NOT NULL,
                threshold REAL,
                threshold_type TEXT,
                actual_temp REAL NOT NULL,
                settled_price INTEGER,
                settlement_time TEXT
            )
        """)

        # Trades - what we executed
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                ticker TEXT NOT NULL,
                side TEXT NOT NULL,
                action TEXT NOT NULL,
                count INTEGER NOT NULL,
                price INTEGER NOT NULL,
                edge REAL,
                ev REAL,
                strategy_mode TEXT,
                forecast_temp REAL,
                market_price INTEGER,
                outcome TEXT,
                pnl REAL,
                settled INTEGER DEFAULT 0
            )
        """)

        # Trade forecasts - link individual forecasts to trades for accuracy analysis
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trade_forecasts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id INTEGER,
                source TEXT NOT NULL,
                forecast_temp REAL NOT NULL,
                weight_used REAL,
                timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (trade_id) REFERENCES trades(id)
            )
        """)

        # Create indexes for faster queries
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_ticker ON market_snapshots(ticker)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_time ON market_snapshots(timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_forecasts_ticker ON forecasts(ticker)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_ticker ON trades(ticker)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_settled ON trades(settled)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_trade_forecasts_trade_id ON trade_forecasts(trade_id)")

        conn.commit()
        conn.close()

    def store_market_snapshot(self, ticker: str, snapshot: Dict):
        """Store a market snapshot"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute("""
                INSERT OR REPLACE INTO market_snapshots
                (timestamp, ticker, yes_price, no_price, yes_bid, yes_ask, no_bid, no_ask, volume, open_interest)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                datetime.utcnow().isoformat(),
                ticker,
                snapshot.get('yes_price'),
                snapshot.get('no_price'),
                snapshot.get('yes_bid'),
                snapshot.get('yes_ask'),
                snapshot.get('no_bid'),
                snapshot.get('no_ask'),
                snapshot.get('volume'),
                snapshot.get('open_interest')
            ))
            conn.commit()
        finally:
            conn.close()

    def store_forecast(self, ticker: str, city: str, target_date: str, source: str,
                       forecast_temp: float, forecast_low: float = None,
                       forecast_high: float = None, ensemble_std: float = None):
        """Store a forecast"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute("""
                INSERT OR REPLACE INTO forecasts
                (timestamp, ticker, city, target_date, source, forecast_temp, forecast_low, forecast_high, ensemble_std)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                datetime.utcnow().isoformat(),
                ticker,
                city,
                target_date,
                source,
                forecast_temp,
                forecast_low,
                forecast_high,
                ensemble_std
            ))
            conn.commit()
        finally:
            conn.close()

    def store_outcome(self, ticker: str, city: str, target_date: str,
                      threshold: float, threshold_type: str, actual_temp: float,
                      settled_price: int = None):
        """Store an actual outcome"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute("""
                INSERT OR REPLACE INTO outcomes
                (ticker, city, target_date, threshold, threshold_type, actual_temp, settled_price, settlement_time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                ticker,
                city,
                target_date,
                threshold,
                threshold_type,
                actual_temp,
                settled_price,
                datetime.utcnow().isoformat()
            ))
            conn.commit()
        finally:
            conn.close()

    def store_trade(self, ticker: str, side: str, action: str, count: int,
                    price: int, edge: float = None, ev: float = None,
                    strategy_mode: str = None, forecast_temp: float = None,
                    market_price: int = None):
        """Store a trade"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute("""
                INSERT INTO trades
                (timestamp, ticker, side, action, count, price, edge, ev, strategy_mode, forecast_temp, market_price)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                datetime.utcnow().isoformat(),
                ticker,
                side,
                action,
                count,
                price,
                edge,
                ev,
                strategy_mode,
                forecast_temp,
                market_price
            ))
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    def update_trade_outcome(self, trade_id: int, outcome: str, pnl: float):
        """Update a trade with its outcome"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute("""
                UPDATE trades SET outcome = ?, pnl = ?, settled = 1
                WHERE id = ?
            """, (outcome, pnl, trade_id))
            conn.commit()
        finally:
            conn.close()

    def get_unsettled_trades(self) -> List[Dict]:
        """Get all unsettled trades"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        try:
            cursor.execute("SELECT * FROM trades WHERE settled = 0")
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def get_all_trades(self, start_date: str = None, end_date: str = None) -> List[Dict]:
        """Get all trades, optionally filtered by date range"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        try:
            query = "SELECT * FROM trades WHERE 1=1"
            params = []

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

    def get_forecasts_for_ticker(self, ticker: str) -> List[Dict]:
        """Get all forecasts for a ticker"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        try:
            cursor.execute(
                "SELECT * FROM forecasts WHERE ticker = ? ORDER BY timestamp",
                (ticker,)
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def get_outcome(self, ticker: str) -> Optional[Dict]:
        """Get outcome for a ticker"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        try:
            cursor.execute("SELECT * FROM outcomes WHERE ticker = ?", (ticker,))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def store_trade_forecast(self, trade_id: int, source: str, forecast_temp: float,
                             weight_used: float = None) -> Optional[int]:
        """
        Store an individual forecast that contributed to a trade decision.
        Links forecasts to trades for later accuracy analysis.

        Args:
            trade_id: ID of the trade this forecast contributed to
            source: Forecast source name (e.g., 'nws', 'open_meteo_ecmwf')
            forecast_temp: Temperature forecast in Fahrenheit
            weight_used: Weight applied to this forecast (0-1)

        Returns:
            ID of the inserted record, or None on error
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute("""
                INSERT INTO trade_forecasts (trade_id, source, forecast_temp, weight_used)
                VALUES (?, ?, ?, ?)
            """, (trade_id, source, forecast_temp, weight_used))
            conn.commit()
            return cursor.lastrowid
        except Exception as e:
            logger.debug(f"Error storing trade forecast: {e}")
            return None
        finally:
            conn.close()

    def get_trade_forecasts(self, trade_id: int) -> List[Dict]:
        """Get all forecasts associated with a trade"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        try:
            cursor.execute(
                "SELECT * FROM trade_forecasts WHERE trade_id = ? ORDER BY source",
                (trade_id,)
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()


class PerformanceMetrics:
    """Calculate trading performance metrics"""

    @staticmethod
    def calculate_returns(trades: List[Dict]) -> List[float]:
        """Calculate returns from trades"""
        returns = []
        for trade in trades:
            if trade.get('pnl') is not None and trade.get('price'):
                # Return = PnL / Cost
                cost = (trade['count'] * trade['price']) / 100.0
                if cost > 0:
                    ret = trade['pnl'] / cost
                    returns.append(ret)
        return returns

    @staticmethod
    def calculate_sharpe_ratio(returns: List[float], risk_free_rate: float = 0.0,
                                periods_per_year: int = 365) -> float:
        """
        Calculate annualized Sharpe ratio

        Args:
            returns: List of returns (can be daily, per-trade, etc.)
            risk_free_rate: Annual risk-free rate (default 0)
            periods_per_year: Number of periods in a year

        Returns:
            Annualized Sharpe ratio
        """
        if len(returns) < 2:
            return 0.0

        mean_return = sum(returns) / len(returns)
        variance = sum((r - mean_return) ** 2 for r in returns) / (len(returns) - 1)
        std_dev = math.sqrt(variance) if variance > 0 else 0.0001

        if std_dev == 0:
            return 0.0

        # Annualize
        excess_return = mean_return - (risk_free_rate / periods_per_year)
        sharpe = (excess_return / std_dev) * math.sqrt(periods_per_year)

        return sharpe

    @staticmethod
    def calculate_sortino_ratio(returns: List[float], risk_free_rate: float = 0.0,
                                 periods_per_year: int = 365) -> float:
        """
        Calculate annualized Sortino ratio (uses downside deviation only)

        Args:
            returns: List of returns
            risk_free_rate: Annual risk-free rate
            periods_per_year: Number of periods in a year

        Returns:
            Annualized Sortino ratio
        """
        if len(returns) < 2:
            return 0.0

        mean_return = sum(returns) / len(returns)
        target_return = risk_free_rate / periods_per_year

        # Calculate downside deviation (only negative returns)
        downside_returns = [min(0, r - target_return) for r in returns]
        downside_variance = sum(r ** 2 for r in downside_returns) / len(returns)
        downside_std = math.sqrt(downside_variance) if downside_variance > 0 else 0.0001

        if downside_std == 0:
            return float('inf') if mean_return > target_return else 0.0

        excess_return = mean_return - target_return
        sortino = (excess_return / downside_std) * math.sqrt(periods_per_year)

        return sortino

    @staticmethod
    def calculate_max_drawdown(equity_curve: List[float]) -> Tuple[float, int, int]:
        """
        Calculate maximum drawdown

        Args:
            equity_curve: List of portfolio values over time

        Returns:
            (max_drawdown_pct, peak_idx, trough_idx)
        """
        if len(equity_curve) < 2:
            return 0.0, 0, 0

        peak = equity_curve[0]
        peak_idx = 0
        max_dd = 0.0
        max_dd_peak_idx = 0
        max_dd_trough_idx = 0

        for i, value in enumerate(equity_curve):
            if value > peak:
                peak = value
                peak_idx = i

            dd = (peak - value) / peak if peak > 0 else 0

            if dd > max_dd:
                max_dd = dd
                max_dd_peak_idx = peak_idx
                max_dd_trough_idx = i

        return max_dd, max_dd_peak_idx, max_dd_trough_idx

    @staticmethod
    def calculate_win_rate(trades: List[Dict]) -> Tuple[float, int, int]:
        """
        Calculate win rate

        Returns:
            (win_rate, wins, losses)
        """
        wins = sum(1 for t in trades if t.get('pnl', 0) > 0)
        losses = sum(1 for t in trades if t.get('pnl', 0) < 0)
        total = wins + losses

        win_rate = wins / total if total > 0 else 0.0
        return win_rate, wins, losses

    @staticmethod
    def calculate_profit_factor(trades: List[Dict]) -> float:
        """
        Calculate profit factor (gross profit / gross loss)

        Returns:
            Profit factor (>1 is profitable)
        """
        gross_profit = sum(t.get('pnl', 0) for t in trades if t.get('pnl', 0) > 0)
        gross_loss = abs(sum(t.get('pnl', 0) for t in trades if t.get('pnl', 0) < 0))

        if gross_loss == 0:
            return float('inf') if gross_profit > 0 else 0.0

        return gross_profit / gross_loss

    @staticmethod
    def calculate_expectancy(trades: List[Dict]) -> float:
        """
        Calculate expectancy (average P&L per trade)

        Returns:
            Average P&L per trade
        """
        settled_trades = [t for t in trades if t.get('pnl') is not None]
        if not settled_trades:
            return 0.0

        total_pnl = sum(t['pnl'] for t in settled_trades)
        return total_pnl / len(settled_trades)

    @classmethod
    def generate_report(cls, trades: List[Dict], initial_capital: float = 100.0) -> Dict:
        """
        Generate comprehensive performance report

        Args:
            trades: List of trade dictionaries
            initial_capital: Starting capital

        Returns:
            Dictionary with all performance metrics
        """
        settled_trades = [t for t in trades if t.get('pnl') is not None]

        if not settled_trades:
            return {
                'total_trades': len(trades),
                'settled_trades': 0,
                'pending_trades': len(trades),
                'error': 'No settled trades to analyze'
            }

        # Build equity curve
        equity = [initial_capital]
        for trade in sorted(settled_trades, key=lambda x: x.get('timestamp', '')):
            equity.append(equity[-1] + trade['pnl'])

        returns = cls.calculate_returns(settled_trades)
        win_rate, wins, losses = cls.calculate_win_rate(settled_trades)
        max_dd, peak_idx, trough_idx = cls.calculate_max_drawdown(equity)

        total_pnl = sum(t['pnl'] for t in settled_trades)
        avg_win = sum(t['pnl'] for t in settled_trades if t['pnl'] > 0) / wins if wins > 0 else 0
        avg_loss = sum(t['pnl'] for t in settled_trades if t['pnl'] < 0) / losses if losses > 0 else 0

        return {
            'total_trades': len(trades),
            'settled_trades': len(settled_trades),
            'pending_trades': len(trades) - len(settled_trades),
            'total_pnl': round(total_pnl, 2),
            'win_rate': round(win_rate * 100, 1),
            'wins': wins,
            'losses': losses,
            'avg_win': round(avg_win, 2),
            'avg_loss': round(avg_loss, 2),
            'profit_factor': round(cls.calculate_profit_factor(settled_trades), 2),
            'expectancy': round(cls.calculate_expectancy(settled_trades), 4),
            'sharpe_ratio': round(cls.calculate_sharpe_ratio(returns), 2),
            'sortino_ratio': round(cls.calculate_sortino_ratio(returns), 2),
            'max_drawdown_pct': round(max_dd * 100, 1),
            'final_equity': round(equity[-1], 2),
            'return_pct': round((equity[-1] - initial_capital) / initial_capital * 100, 1)
        }


class Backtester:
    """
    Strategy backtesting engine

    Replays historical data through a strategy to calculate performance.
    """

    def __init__(self, data_store: HistoricalDataStore):
        self.data_store = data_store
        self.trades = []
        self.equity_curve = []

    def run_backtest(self, strategy_func, start_date: str, end_date: str,
                     initial_capital: float = 100.0) -> Dict:
        """
        Run a backtest

        Args:
            strategy_func: Function that takes (market_data, forecast_data) and returns trade decision
            start_date: Start date (ISO format)
            end_date: End date (ISO format)
            initial_capital: Starting capital

        Returns:
            Performance report dictionary
        """
        # This is a simplified backtester - in production you'd replay tick-by-tick
        trades = self.data_store.get_all_trades(start_date, end_date)

        if not trades:
            return {'error': 'No trades found in date range'}

        return PerformanceMetrics.generate_report(trades, initial_capital)

    def walk_forward_analysis(self, strategy_func, start_date: str, end_date: str,
                               train_window_days: int = 30, test_window_days: int = 7) -> List[Dict]:
        """
        Perform walk-forward analysis

        Trains on N days, tests on M days, walks forward.

        Returns:
            List of performance reports for each test period
        """
        results = []
        current_start = datetime.fromisoformat(start_date)
        final_end = datetime.fromisoformat(end_date)

        while current_start + timedelta(days=train_window_days + test_window_days) <= final_end:
            train_end = current_start + timedelta(days=train_window_days)
            test_end = train_end + timedelta(days=test_window_days)

            # In a real implementation, you'd train the strategy on training data
            # and then test on test data

            test_report = self.run_backtest(
                strategy_func,
                train_end.isoformat(),
                test_end.isoformat()
            )
            test_report['train_start'] = current_start.isoformat()
            test_report['train_end'] = train_end.isoformat()
            test_report['test_start'] = train_end.isoformat()
            test_report['test_end'] = test_end.isoformat()

            results.append(test_report)
            current_start = train_end  # Walk forward

        return results


# Convenience function to get a global data store instance
_data_store = None

def get_data_store() -> HistoricalDataStore:
    """Get the global data store instance"""
    global _data_store
    if _data_store is None:
        _data_store = HistoricalDataStore()
    return _data_store
