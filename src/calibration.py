"""
Calibration Tracker — Brier score and calibration curve computation.

Joins trades.csv (has our_probability) with outcomes.csv (has won) on market_ticker
to measure how well-calibrated our probability estimates are.

Brier score = mean((prob - outcome)²) where outcome = 1 if won, 0 if lost.
Perfect calibration: Brier = 0. Random guessing at 50%: Brier = 0.25.
"""

import csv
import logging
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

from .config import Config

logger = logging.getLogger(__name__)


class CalibrationTracker:
    """Compute Brier score and calibration buckets from trade history."""

    def __init__(self):
        self.outcomes_file = Path("data/paper_outcomes.csv") if Config.PAPER_TRADING else Path("data/outcomes.csv")
        self.trades_file = Path("data/trades.csv")

    def _load_joined_data(self) -> List[dict]:
        """Join outcomes with trade probabilities.

        Returns list of dicts with keys: market_ticker, our_probability, won, city, strategy_mode.
        """
        # Load trade probabilities keyed by (ticker, side)
        trade_probs = {}
        if self.trades_file.exists():
            try:
                with open(self.trades_file, 'r') as f:
                    for row in csv.DictReader(f):
                        key = (row.get('market_ticker', ''), row.get('side', '').lower())
                        prob = row.get('our_probability', '')
                        if prob:
                            trade_probs[key] = {
                                'our_probability': float(prob),
                                'strategy_mode': row.get('strategy_mode', ''),
                            }
            except Exception as e:
                logger.warning(f"Error loading trades for calibration: {e}")

        # Load outcomes and join
        joined = []
        if not self.outcomes_file.exists():
            return joined

        try:
            with open(self.outcomes_file, 'r') as f:
                for row in csv.DictReader(f):
                    ticker = row.get('market_ticker', '')
                    side = row.get('side', '').lower()
                    won_str = row.get('won', '')
                    if won_str not in ('YES', 'NO'):
                        continue

                    won = 1 if won_str == 'YES' else 0

                    # Get probability from outcome row first, then trades
                    prob_str = row.get('our_probability', '')
                    strategy = row.get('strategy_mode', '')
                    if prob_str:
                        prob = float(prob_str) if float(prob_str) <= 1.0 else float(prob_str) / 100.0
                    elif (ticker, side) in trade_probs:
                        td = trade_probs[(ticker, side)]
                        prob = td['our_probability']
                        if prob > 1.0:
                            prob = prob / 100.0
                        strategy = strategy or td['strategy_mode']
                    else:
                        continue  # Can't compute Brier without probability

                    city = row.get('city', '')
                    joined.append({
                        'market_ticker': ticker,
                        'our_probability': prob,
                        'won': won,
                        'city': city,
                        'strategy_mode': strategy,
                    })
        except Exception as e:
            logger.warning(f"Error loading outcomes for calibration: {e}")

        return joined

    def compute(self) -> dict:
        """Compute Brier score, calibration buckets, and breakdowns.

        Returns:
            {
                brier_score: float,
                n_trades: int,
                buckets: [{bucket: str, predicted_avg: float, actual_rate: float, count: int}],
                by_city: {city: {brier_score, n_trades}},
                by_strategy: {strategy: {brier_score, n_trades}},
            }
        """
        data = self._load_joined_data()
        if not data:
            return {'brier_score': None, 'n_trades': 0, 'buckets': [], 'by_city': {}, 'by_strategy': {}}

        # Overall Brier score
        brier_sum = sum((d['our_probability'] - d['won']) ** 2 for d in data)
        brier_score = brier_sum / len(data)

        # Calibration buckets (10 bins: 0-10%, 10-20%, ..., 90-100%)
        bucket_data = defaultdict(lambda: {'predicted_sum': 0.0, 'actual_sum': 0, 'count': 0})
        for d in data:
            bucket_idx = min(int(d['our_probability'] * 10), 9)
            bucket_label = f"{bucket_idx * 10}-{(bucket_idx + 1) * 10}%"
            bucket_data[bucket_label]['predicted_sum'] += d['our_probability']
            bucket_data[bucket_label]['actual_sum'] += d['won']
            bucket_data[bucket_label]['count'] += 1

        buckets = []
        for i in range(10):
            label = f"{i * 10}-{(i + 1) * 10}%"
            bd = bucket_data.get(label, {'predicted_sum': 0.0, 'actual_sum': 0, 'count': 0})
            if bd['count'] > 0:
                buckets.append({
                    'bucket': label,
                    'predicted_avg': bd['predicted_sum'] / bd['count'],
                    'actual_rate': bd['actual_sum'] / bd['count'],
                    'count': bd['count'],
                })
            else:
                buckets.append({'bucket': label, 'predicted_avg': (i * 10 + 5) / 100.0, 'actual_rate': None, 'count': 0})

        # By city
        by_city = defaultdict(lambda: {'brier_sum': 0.0, 'count': 0})
        for d in data:
            city = d['city'] or 'unknown'
            by_city[city]['brier_sum'] += (d['our_probability'] - d['won']) ** 2
            by_city[city]['count'] += 1
        by_city_result = {
            city: {'brier_score': v['brier_sum'] / v['count'], 'n_trades': v['count']}
            for city, v in by_city.items()
        }

        # By strategy
        by_strategy = defaultdict(lambda: {'brier_sum': 0.0, 'count': 0})
        for d in data:
            strat = d['strategy_mode'] or 'unknown'
            by_strategy[strat]['brier_sum'] += (d['our_probability'] - d['won']) ** 2
            by_strategy[strat]['count'] += 1
        by_strategy_result = {
            strat: {'brier_score': v['brier_sum'] / v['count'], 'n_trades': v['count']}
            for strat, v in by_strategy.items()
        }

        return {
            'brier_score': round(brier_score, 4),
            'n_trades': len(data),
            'buckets': buckets,
            'by_city': by_city_result,
            'by_strategy': by_strategy_result,
        }
