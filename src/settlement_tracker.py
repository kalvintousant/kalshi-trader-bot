"""
Settlement Tracker - Track forecast probability vs actual outcome divergence

After each settlement, records how far off our forecast probability was from
the actual binary outcome. Tracks mean divergence and stddev per city to
detect systematic forecast biases and adjust confidence accordingly.
"""

import json
import logging
import math
from datetime import datetime
from pathlib import Path
from collections import defaultdict

logger = logging.getLogger(__name__)


class SettlementTracker:
    """Track forecast vs outcome divergence per city."""

    def __init__(self, state_path: str = "data/settlement_divergence.json"):
        self.state_file = Path(state_path)
        self.state_file.parent.mkdir(exist_ok=True)

        # {city: [{'prob': float, 'won': bool, 'ticker': str, 'timestamp': str}, ...]}
        self.records = defaultdict(list)
        self._load_state()

    def _load_state(self):
        if not self.state_file.exists():
            return
        try:
            with open(self.state_file, 'r') as f:
                data = json.load(f)
            for city, records in data.get('records', {}).items():
                self.records[city] = records
            total = sum(len(v) for v in self.records.values())
            if total > 0:
                logger.info(f"📊 Settlement tracker: {total} records across {len(self.records)} cities")
        except Exception as e:
            logger.warning(f"Could not load settlement tracker state: {e}")

    def _save_state(self):
        try:
            data = {
                'records': dict(self.records),
                'updated_at': datetime.now().isoformat(),
            }
            with open(self.state_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning(f"Could not save settlement tracker state: {e}")

    def record_settlement(self, city: str, our_probability: float, won: bool,
                          ticker: str = ''):
        """
        Record a settlement for divergence tracking.

        Args:
            city: City code (e.g., 'NY', 'CHI')
            our_probability: Our forecast probability for the side we traded (0-1)
            won: Whether we won the trade
            ticker: Market ticker for reference
        """
        self.records[city].append({
            'prob': our_probability,
            'won': won,
            'ticker': ticker,
            'timestamp': datetime.now().isoformat(),
        })

        # Keep only last 200 records per city to prevent unbounded growth
        if len(self.records[city]) > 200:
            self.records[city] = self.records[city][-200:]

        self._save_state()

    def get_city_divergence(self, city: str) -> dict:
        """
        Calculate divergence stats for a city.

        Returns:
            dict with mean_divergence, std_divergence, n_records, confidence_adjustment
        """
        records = self.records.get(city, [])
        if len(records) < 5:
            return {
                'mean_divergence': 0.0,
                'std_divergence': 0.0,
                'n_records': len(records),
                'confidence_adjustment': 1.0,
            }

        # Divergence = our_probability - actual_outcome (1 if won, 0 if lost)
        # Positive divergence = we're systematically overconfident
        # Negative divergence = we're systematically underconfident
        divergences = []
        for r in records:
            actual = 1.0 if r['won'] else 0.0
            divergences.append(r['prob'] - actual)

        mean_div = sum(divergences) / len(divergences)
        variance = sum((d - mean_div) ** 2 for d in divergences) / len(divergences)
        std_div = math.sqrt(variance)

        # Confidence adjustment: if mean divergence is significantly positive
        # (overconfident), reduce confidence. Range: [0.5, 1.0]
        # A mean divergence of 0.2 (20% overconfident) → 0.8 adjustment
        if mean_div > 0.05:  # Only adjust if meaningfully overconfident
            adjustment = max(0.5, 1.0 - mean_div)
        else:
            adjustment = 1.0

        return {
            'mean_divergence': mean_div,
            'std_divergence': std_div,
            'n_records': len(records),
            'confidence_adjustment': adjustment,
        }

    def get_all_divergences(self) -> dict:
        """Get divergence stats for all cities."""
        return {city: self.get_city_divergence(city) for city in self.records}

    def generate_report(self) -> str:
        """Generate human-readable divergence report."""
        lines = ["Settlement Divergence Report", "=" * 40, ""]

        if not self.records:
            lines.append("No settlement data yet.")
            return "\n".join(lines)

        for city in sorted(self.records.keys()):
            stats = self.get_city_divergence(city)
            direction = "overconfident" if stats['mean_divergence'] > 0 else "underconfident"
            lines.append(f"{city}: {stats['n_records']} settlements")
            lines.append(f"  Mean divergence: {stats['mean_divergence']:+.3f} ({direction})")
            lines.append(f"  Std divergence:  {stats['std_divergence']:.3f}")
            lines.append(f"  Confidence adj:  {stats['confidence_adjustment']:.2f}x")
            lines.append("")

        return "\n".join(lines)
