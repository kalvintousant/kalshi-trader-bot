"""
Post-Mortem Generator — Structured analysis of each settled trade.

Generates a detailed post-mortem for every settlement, recording:
- What was traded (side, price, contracts, strategy)
- Why (our_prob, edge, EV, mean_forecast, threshold)
- What happened (won, P&L, actual_temp, forecast_error)
- Per-source accuracy breakdown

Stored as JSONL in data/postmortems.jsonl (one JSON object per line).
"""

import csv
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from .config import Config

logger = logging.getLogger(__name__)


class PostMortemGenerator:
    """Generate and store structured post-mortem analysis for settled trades."""

    def __init__(self):
        self.output_file = Path("data/postmortems.jsonl")
        self.output_file.parent.mkdir(exist_ok=True)
        self.source_forecasts_file = Path("data/source_forecasts.csv")

    def generate(self, market_ticker: str, trade_details: dict, outcome_data: dict,
                 source_forecasts: Optional[List[dict]] = None) -> dict:
        """Generate a post-mortem for a settled trade.

        Args:
            market_ticker: The market ticker
            trade_details: From _lookup_trade_details() — our_probability, market_price, edge, ev, strategy_mode
            outcome_data: Settlement result — won (bool), pnl (float), side, contracts, entry_price,
                         actual_temp, predicted_temp, forecast_error, result, threshold
            source_forecasts: Optional per-source forecast data

        Returns:
            Post-mortem dict
        """
        actual_temp = outcome_data.get('actual_temp')
        predicted_temp = outcome_data.get('predicted_temp')
        forecast_error = outcome_data.get('forecast_error')

        # Per-source accuracy
        source_accuracy = []
        if source_forecasts and actual_temp is not None:
            for sf in source_forecasts:
                source_temp = sf.get('temperature')
                source_name = sf.get('source', 'unknown')
                if source_temp is not None:
                    try:
                        error = float(source_temp) - float(actual_temp)
                        source_accuracy.append({
                            'source': source_name,
                            'forecast': float(source_temp),
                            'error': round(error, 2),
                            'abs_error': round(abs(error), 2),
                        })
                    except (ValueError, TypeError):
                        pass

        # Sort by absolute error (best first)
        source_accuracy.sort(key=lambda x: x['abs_error'])

        our_prob = trade_details.get('our_probability', '')
        market_price = trade_details.get('market_price', '')
        edge = trade_details.get('edge', '')
        ev = trade_details.get('ev', '')

        postmortem = {
            'timestamp': datetime.now().isoformat(),
            'market_ticker': market_ticker,
            # What was traded
            'trade': {
                'side': outcome_data.get('side', ''),
                'contracts': outcome_data.get('contracts', 0),
                'entry_price': outcome_data.get('entry_price', 0),
                'strategy_mode': trade_details.get('strategy_mode', ''),
            },
            # Why we traded
            'reasoning': {
                'our_probability': _safe_float(our_prob),
                'market_price': _safe_float(market_price),
                'edge': _safe_float(edge),
                'ev': _safe_float(ev),
                'mean_forecast': predicted_temp,
                'threshold': outcome_data.get('threshold'),
            },
            # What happened
            'outcome': {
                'won': outcome_data.get('won', False),
                'result': outcome_data.get('result', ''),
                'pnl': outcome_data.get('pnl', 0.0),
                'actual_temp': actual_temp,
                'forecast_error': forecast_error,
            },
            # Per-source accuracy
            'source_accuracy': source_accuracy,
        }

        return postmortem

    def store(self, postmortem: dict):
        """Append post-mortem to JSONL file."""
        try:
            with open(self.output_file, 'a') as f:
                f.write(json.dumps(postmortem) + '\n')
            logger.debug(f"Stored post-mortem for {postmortem.get('market_ticker', '?')}")
        except Exception as e:
            logger.warning(f"Could not store post-mortem: {e}")

    def load(self, limit: int = 50, city: str = None) -> List[dict]:
        """Load post-mortems from JSONL file.

        Args:
            limit: Maximum number to return (most recent first)
            city: Optional city filter (matches in market_ticker)

        Returns:
            List of post-mortem dicts, most recent first
        """
        if not self.output_file.exists():
            return []

        postmortems = []
        try:
            with open(self.output_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        pm = json.loads(line)
                        if city:
                            ticker = pm.get('market_ticker', '')
                            if city.upper() not in ticker.upper():
                                continue
                        postmortems.append(pm)
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.warning(f"Error loading post-mortems: {e}")

        # Most recent first, limited
        postmortems.reverse()
        return postmortems[:limit]

    def _lookup_source_forecasts(self, market_ticker: str) -> List[dict]:
        """Look up per-source forecast data for a market ticker.

        Reads from the forecast metadata stored during get_all_forecasts().
        Returns list of {source, temperature} dicts.
        """
        if not self.source_forecasts_file.exists():
            return []

        results = []
        try:
            with open(self.source_forecasts_file, 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get('market_ticker', '') == market_ticker or row.get('series_ticker', '') in market_ticker:
                        results.append({
                            'source': row.get('source', ''),
                            'temperature': _safe_float(row.get('temperature', '')),
                        })
        except Exception:
            pass
        return results


def _safe_float(val) -> Optional[float]:
    """Convert to float, return None if empty/invalid."""
    if val is None or val == '':
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None
