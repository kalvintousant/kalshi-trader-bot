"""
Cooldown Timer — Time-based pause after losses.

Pauses trading for a configurable duration after each loss.
After N consecutive losses, pauses for the rest of the day.
Resets daily and on wins.

Follows the same pattern as DrawdownProtector for consistency.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from .config import Config

logger = logging.getLogger(__name__)


class CooldownTimer:
    """Time-based trading pause after losses."""

    def __init__(self, state_path: str = "data/cooldown_state.json"):
        self.state_file = Path(state_path)
        self.state_file.parent.mkdir(exist_ok=True)

        self.last_loss_time = None  # ISO string
        self.consecutive_losses = 0
        self.session_paused = False
        self.last_reset_date = None
        self._load_state()

    def _load_state(self):
        if not self.state_file.exists():
            return
        try:
            with open(self.state_file, 'r') as f:
                data = json.load(f)
            self.last_loss_time = data.get('last_loss_time')
            self.consecutive_losses = data.get('consecutive_losses', 0)
            self.session_paused = data.get('session_paused', False)
            self.last_reset_date = data.get('last_reset_date')

            # Daily reset
            today = datetime.now().date().isoformat()
            if self.last_reset_date != today:
                self.consecutive_losses = 0
                self.session_paused = False
                self.last_loss_time = None
                self.last_reset_date = today
                self._save_state()

            if self.consecutive_losses > 0:
                logger.info(f"⏱ Cooldown timer: {self.consecutive_losses} consecutive losses loaded")
        except Exception as e:
            logger.warning(f"Could not load cooldown state: {e}")

    def _save_state(self):
        try:
            data = {
                'last_loss_time': self.last_loss_time,
                'consecutive_losses': self.consecutive_losses,
                'session_paused': self.session_paused,
                'last_reset_date': self.last_reset_date or datetime.now().date().isoformat(),
                'updated_at': datetime.now().isoformat(),
            }
            with open(self.state_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning(f"Could not save cooldown state: {e}")

    def record_outcome(self, won: bool):
        """Record a trade outcome."""
        today = datetime.now().date().isoformat()
        if self.last_reset_date != today:
            self.consecutive_losses = 0
            self.session_paused = False
            self.last_reset_date = today

        if won:
            if self.consecutive_losses > 0:
                logger.info(f"✅ Win resets cooldown ({self.consecutive_losses} consecutive losses cleared)")
            self.consecutive_losses = 0
            self.last_loss_time = None
            self.session_paused = False
        else:
            self.consecutive_losses += 1
            self.last_loss_time = datetime.now().isoformat()

            if self.consecutive_losses >= Config.COOLDOWN_SESSION_PAUSE_LOSSES:
                self.session_paused = True
                logger.warning(f"⏱ COOLDOWN: {self.consecutive_losses} consecutive losses — pausing for rest of day")
            else:
                logger.info(f"⏱ COOLDOWN: Loss #{self.consecutive_losses} — pausing for {Config.COOLDOWN_MINUTES} minutes")

        self._save_state()

    def is_on_cooldown(self) -> bool:
        """Check if trading is currently paused due to cooldown."""
        # Daily reset check
        today = datetime.now().date().isoformat()
        if self.last_reset_date != today:
            self.consecutive_losses = 0
            self.session_paused = False
            self.last_loss_time = None
            self.last_reset_date = today
            self._save_state()
            return False

        # Session paused (rest of day)
        if self.session_paused:
            return True

        # Time-based cooldown
        if self.last_loss_time:
            try:
                loss_time = datetime.fromisoformat(self.last_loss_time)
                elapsed_minutes = (datetime.now() - loss_time).total_seconds() / 60.0
                if elapsed_minutes < Config.COOLDOWN_MINUTES:
                    return True
            except (ValueError, TypeError):
                pass

        return False

    def get_remaining_minutes(self) -> float:
        """Get remaining cooldown time in minutes. 0 if not on cooldown."""
        if self.session_paused:
            return float('inf')  # Paused until tomorrow
        if not self.last_loss_time:
            return 0.0
        try:
            loss_time = datetime.fromisoformat(self.last_loss_time)
            elapsed = (datetime.now() - loss_time).total_seconds() / 60.0
            remaining = Config.COOLDOWN_MINUTES - elapsed
            return max(0.0, remaining)
        except (ValueError, TypeError):
            return 0.0

    def get_status(self) -> dict:
        """Return current cooldown status for dashboard."""
        return {
            'enabled': Config.COOLDOWN_ENABLED,
            'on_cooldown': self.is_on_cooldown(),
            'consecutive_losses': self.consecutive_losses,
            'session_paused': self.session_paused,
            'remaining_minutes': round(self.get_remaining_minutes(), 1),
            'cooldown_minutes': Config.COOLDOWN_MINUTES,
            'pause_threshold': Config.COOLDOWN_SESSION_PAUSE_LOSSES,
        }
