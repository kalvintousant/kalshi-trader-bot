"""
Drawdown Protector - Progressive loss protection system

Reduces position sizes and tightens edge thresholds as consecutive
losses accumulate. Pauses trading entirely after severe drawdowns.

Levels:
  1 (3 consecutive losses):  75% position size
  2 (5 consecutive losses):  50% position size, +20% edge threshold
  3 (8 consecutive losses):  25% position size
  4 (10+ consecutive losses): trading paused
"""

import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class DrawdownProtector:
    """Progressive loss protection that scales with consecutive losses."""

    LEVELS = [
        {'consecutive': 3, 'size_mult': 0.75, 'edge_mult': 1.0, 'label': 'Level 1'},
        {'consecutive': 5, 'size_mult': 0.50, 'edge_mult': 1.2, 'label': 'Level 2'},
        {'consecutive': 8, 'size_mult': 0.25, 'edge_mult': 1.2, 'label': 'Level 3'},
        {'consecutive': 10, 'size_mult': 0.0, 'edge_mult': 1.0, 'label': 'Level 4 (PAUSED)'},
    ]

    def __init__(self, state_path: str = "data/drawdown_state.json"):
        self.state_file = Path(state_path)
        self.state_file.parent.mkdir(exist_ok=True)
        self.consecutive_losses = 0
        self.total_losses_today = 0
        self.last_reset_date = None
        self._load_state()

    def _load_state(self):
        if not self.state_file.exists():
            return
        try:
            with open(self.state_file, 'r') as f:
                data = json.load(f)
            self.consecutive_losses = data.get('consecutive_losses', 0)
            self.total_losses_today = data.get('total_losses_today', 0)
            self.last_reset_date = data.get('last_reset_date')
            if self.consecutive_losses > 0:
                logger.info(f"📉 Drawdown protector: {self.consecutive_losses} consecutive losses loaded")
        except Exception as e:
            logger.warning(f"Could not load drawdown state: {e}")

    def _save_state(self):
        try:
            data = {
                'consecutive_losses': self.consecutive_losses,
                'total_losses_today': self.total_losses_today,
                'last_reset_date': self.last_reset_date,
                'updated_at': datetime.now().isoformat(),
            }
            with open(self.state_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning(f"Could not save drawdown state: {e}")

    def record_outcome(self, won: bool):
        """Record a trade outcome and update consecutive loss counter."""
        today = datetime.now().date().isoformat()
        if self.last_reset_date != today:
            self.total_losses_today = 0
            self.last_reset_date = today

        if won:
            if self.consecutive_losses > 0:
                logger.info(f"✅ Win breaks {self.consecutive_losses}-loss streak, resetting drawdown protector")
            self.consecutive_losses = 0
        else:
            self.consecutive_losses += 1
            self.total_losses_today += 1
            level = self._get_current_level()
            if level:
                logger.warning(f"📉 Drawdown {level['label']}: {self.consecutive_losses} consecutive losses | "
                             f"size={level['size_mult']:.0%}, edge_mult={level['edge_mult']:.1f}x")

        self._save_state()

    def _get_current_level(self):
        """Get the active drawdown level (highest matching)."""
        active = None
        for level in self.LEVELS:
            if self.consecutive_losses >= level['consecutive']:
                active = level
        return active

    def get_position_multiplier(self) -> float:
        """Get position size multiplier (1.0 = normal, 0.0 = paused)."""
        level = self._get_current_level()
        return level['size_mult'] if level else 1.0

    def get_edge_multiplier(self) -> float:
        """Get edge threshold multiplier (1.0 = normal, >1.0 = stricter)."""
        level = self._get_current_level()
        return level['edge_mult'] if level else 1.0

    def is_trading_paused(self) -> bool:
        """Check if trading is paused due to drawdown."""
        return self.get_position_multiplier() == 0.0

    def get_status(self) -> dict:
        """Return current drawdown status for dashboard."""
        level = self._get_current_level()
        return {
            'consecutive_losses': self.consecutive_losses,
            'level': level['label'] if level else 'Normal',
            'size_multiplier': self.get_position_multiplier(),
            'edge_multiplier': self.get_edge_multiplier(),
            'paused': self.is_trading_paused(),
        }
