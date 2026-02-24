"""
Adaptive City Manager - Self-learning system for autonomous trading optimization

This module tracks city performance and makes real-time decisions to:
1. Disable cities with poor win rates automatically
2. Re-enable cities for trial periods after cooldown
3. Persist learning state across bot restarts
4. Provide city-level statistics for position sizing

Based on outcome data from outcome_tracker.py, this manager closes the feedback
loop by actually ACTING on what the bot learns.
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional
from collections import defaultdict
from .config import extract_city_code

logger = logging.getLogger(__name__)


class AdaptiveCityManager:
    """
    Tracks city performance and makes real-time trading decisions.

    Key features:
    - Auto-disables cities with win rate below threshold
    - Re-enables cities for trial after cooldown period
    - Persists state to JSON for survival across restarts
    - Provides per-city statistics for position sizing
    """

    def __init__(self, data_path: str = "data/adaptive_state.json"):
        self.state_file = Path(data_path)
        self.state_file.parent.mkdir(exist_ok=True)

        # City statistics: {city: {wins, losses, pnl, disabled_until, trial_mode}}
        self.city_stats: Dict[str, Dict] = defaultdict(lambda: {
            'wins': 0,
            'losses': 0,
            'pnl': 0.0,
            'disabled_until': None,
            'trial_mode': False,
            'trial_start': None,
            'last_updated': None
        })

        # Load thresholds from Config (with defaults)
        self._load_config()

        # Load existing state
        self.load_state()

        logger.info(f"📊 AdaptiveCityManager initialized: {len(self.city_stats)} cities tracked")

    def _load_config(self):
        """Load configuration thresholds"""
        try:
            from .config import Config
            self.enabled = getattr(Config, 'ADAPTIVE_ENABLED', True)
            self.min_trades = getattr(Config, 'ADAPTIVE_MIN_TRADES', 20)
            self.disable_win_rate = getattr(Config, 'ADAPTIVE_DISABLE_WIN_RATE', 0.40)
            self.disable_hours = getattr(Config, 'ADAPTIVE_DISABLE_HOURS', 24)
            self.reenable_check_hours = getattr(Config, 'ADAPTIVE_REENABLE_CHECK_HOURS', 6)
        except ImportError:
            # Defaults if Config not available
            self.enabled = True
            self.min_trades = 20
            self.disable_win_rate = 0.40
            self.disable_hours = 24
            self.reenable_check_hours = 6

    def load_state(self):
        """Load persisted state from JSON file"""
        if not self.state_file.exists():
            logger.info("No existing adaptive state found, starting fresh")
            return

        try:
            with open(self.state_file, 'r') as f:
                data = json.load(f)

            # Restore city stats
            for city, stats in data.get('city_stats', {}).items():
                self.city_stats[city] = {
                    'wins': stats.get('wins', 0),
                    'losses': stats.get('losses', 0),
                    'pnl': stats.get('pnl', 0.0),
                    'disabled_until': stats.get('disabled_until'),
                    'trial_mode': stats.get('trial_mode', False),
                    'trial_start': stats.get('trial_start'),
                    'last_updated': stats.get('last_updated')
                }

            logger.info(f"📂 Loaded adaptive state: {len(self.city_stats)} cities")

            # Log any disabled cities
            for city, stats in self.city_stats.items():
                if stats.get('disabled_until'):
                    disabled_until = datetime.fromisoformat(stats['disabled_until'])
                    if disabled_until > datetime.now():
                        remaining = disabled_until - datetime.now()
                        logger.info(f"   📉 {city}: disabled for {remaining.total_seconds()/3600:.1f}h more")

        except Exception as e:
            logger.warning(f"Could not load adaptive state: {e}")

    def save_state(self):
        """Persist current state to JSON file"""
        try:
            # Convert defaultdict to regular dict for JSON serialization
            data = {
                'city_stats': {city: dict(stats) for city, stats in self.city_stats.items()},
                'saved_at': datetime.now().isoformat(),
                'config': {
                    'min_trades': self.min_trades,
                    'disable_win_rate': self.disable_win_rate,
                    'disable_hours': self.disable_hours
                }
            }

            with open(self.state_file, 'w') as f:
                json.dump(data, f, indent=2, default=str)

            logger.debug(f"Saved adaptive state to {self.state_file}")

        except Exception as e:
            logger.error(f"Could not save adaptive state: {e}")

    def _extract_city_from_ticker(self, series_ticker: str) -> str:
        """Extract city code from series ticker (e.g., KXHIGHNY -> NY, KXHIGHTDAL -> DAL)"""
        return extract_city_code(series_ticker)

    def is_city_enabled(self, series_ticker: str) -> bool:
        """
        Check if city should be traded (not disabled due to poor performance).

        Args:
            series_ticker: The series ticker (e.g., KXHIGHNY)

        Returns:
            True if city is enabled for trading, False if disabled
        """
        if not self.enabled:
            return True  # Adaptive management disabled, all cities enabled

        city = self._extract_city_from_ticker(series_ticker)
        stats = self.city_stats.get(city)

        if not stats:
            return True  # No stats yet, city is enabled

        disabled_until = stats.get('disabled_until')
        if not disabled_until:
            return True  # Not disabled

        # Parse disabled_until timestamp
        try:
            disabled_dt = datetime.fromisoformat(disabled_until)
            if datetime.now() >= disabled_dt:
                # Disable period has passed, check for re-enable
                self._check_reenable(city)
                return True
            else:
                return False
        except (ValueError, TypeError):
            return True

    def _check_reenable(self, city: str):
        """Check if a disabled city should be re-enabled for trial"""
        stats = self.city_stats[city]

        if not stats.get('disabled_until'):
            return

        try:
            disabled_dt = datetime.fromisoformat(stats['disabled_until'])
            if datetime.now() >= disabled_dt:
                # Re-enable for trial period
                stats['disabled_until'] = None
                stats['trial_mode'] = True
                stats['trial_start'] = datetime.now().isoformat()

                # Reset trial stats (keep historical for reference)
                stats['trial_wins'] = 0
                stats['trial_losses'] = 0
                stats['trial_pnl'] = 0.0

                logger.info(f"🔄 Re-enabling city {city} for trial period")
                self.save_state()

        except (ValueError, TypeError):
            pass

    def record_outcome(self, city: str, won: bool, pnl: float):
        """
        Update stats after a trade settles and potentially disable city.

        Args:
            city: City code (e.g., 'NY', 'CHI')
            won: Whether the trade won
            pnl: Profit/loss in dollars
        """
        if not self.enabled:
            return

        stats = self.city_stats[city]

        # Update overall stats
        if won:
            stats['wins'] += 1
        else:
            stats['losses'] += 1
        stats['pnl'] += pnl
        stats['last_updated'] = datetime.now().isoformat()

        # Update trial stats if in trial mode
        if stats.get('trial_mode'):
            if won:
                stats['trial_wins'] = stats.get('trial_wins', 0) + 1
            else:
                stats['trial_losses'] = stats.get('trial_losses', 0) + 1
            stats['trial_pnl'] = stats.get('trial_pnl', 0.0) + pnl

            # Check if trial has enough data
            trial_trades = stats.get('trial_wins', 0) + stats.get('trial_losses', 0)
            if trial_trades >= 10:  # Minimum trades for trial evaluation
                trial_win_rate = stats.get('trial_wins', 0) / trial_trades
                if trial_win_rate < self.disable_win_rate:
                    # Trial failed, extend disable period
                    self._disable_city(city, reason="trial period failed")
                else:
                    # Trial succeeded, end trial mode
                    stats['trial_mode'] = False
                    logger.info(f"✅ City {city} passed trial: {trial_win_rate:.1%} win rate ({trial_trades} trades)")

        # Check if city should be disabled
        self._check_and_disable(city)

        # Save state after each outcome
        self.save_state()

    def _check_and_disable(self, city: str) -> bool:
        """
        Check if city should be disabled based on win rate.

        Returns:
            True if city was disabled, False otherwise
        """
        stats = self.city_stats[city]

        # Skip if already disabled
        if stats.get('disabled_until'):
            try:
                disabled_dt = datetime.fromisoformat(stats['disabled_until'])
                if datetime.now() < disabled_dt:
                    return False
            except (ValueError, TypeError):
                pass

        total_trades = stats['wins'] + stats['losses']

        # Need minimum trades before evaluating
        if total_trades < self.min_trades:
            return False

        win_rate = stats['wins'] / total_trades

        if win_rate < self.disable_win_rate:
            self._disable_city(city, reason=f"{win_rate:.0%} win rate")
            return True

        return False

    def _disable_city(self, city: str, reason: str = "poor performance"):
        """Disable a city for the configured period"""
        stats = self.city_stats[city]

        disable_until = datetime.now() + timedelta(hours=self.disable_hours)
        stats['disabled_until'] = disable_until.isoformat()
        stats['trial_mode'] = False

        total_trades = stats['wins'] + stats['losses']
        win_rate = stats['wins'] / total_trades if total_trades > 0 else 0

        logger.info(f"📉 City {city} disabled: {reason}")
        logger.info(f"   Stats: {win_rate:.0%} win rate ({total_trades} trades, ${stats['pnl']:.2f} P&L)")
        logger.info(f"   ⏰ Will re-evaluate at {disable_until.strftime('%Y-%m-%d %H:%M')}")

        self.save_state()

    def get_city_stats(self, city: str) -> Dict:
        """Get statistics for a city"""
        stats = self.city_stats.get(city, {})
        total_trades = stats.get('wins', 0) + stats.get('losses', 0)

        return {
            'wins': stats.get('wins', 0),
            'losses': stats.get('losses', 0),
            'total_trades': total_trades,
            'win_rate': stats.get('wins', 0) / total_trades if total_trades > 0 else 0.5,
            'pnl': stats.get('pnl', 0.0),
            'disabled': self._is_currently_disabled(city),
            'trial_mode': stats.get('trial_mode', False)
        }

    def _is_currently_disabled(self, city: str) -> bool:
        """Check if a city is currently disabled"""
        stats = self.city_stats.get(city, {})
        disabled_until = stats.get('disabled_until')

        if not disabled_until:
            return False

        try:
            disabled_dt = datetime.fromisoformat(disabled_until)
            return datetime.now() < disabled_dt
        except (ValueError, TypeError):
            return False

    def get_position_multiplier(self, series_ticker: str) -> float:
        """
        Get position size multiplier based on city performance.

        High win rate cities get multiplier > 1.0
        Low win rate cities get multiplier < 1.0

        Args:
            series_ticker: The series ticker (e.g., KXHIGHNY)

        Returns:
            Multiplier between 0.5 and 1.5
        """
        if not self.enabled:
            return 1.0

        city = self._extract_city_from_ticker(series_ticker)
        stats = self.get_city_stats(city)

        # Need minimum trades for adjustment
        if stats['total_trades'] < self.min_trades:
            return 1.0

        win_rate = stats['win_rate']

        # Scale multiplier based on win rate
        # 50% win rate = 1.0x
        # 60% win rate = 1.2x
        # 40% win rate = 0.8x
        # Clamped to [0.5, 1.5]
        multiplier = 0.5 + win_rate  # 0% -> 0.5x, 50% -> 1.0x, 100% -> 1.5x
        return max(0.5, min(1.5, multiplier))

    def generate_report(self) -> str:
        """Generate a human-readable performance report"""
        lines = [
            "=" * 60,
            "ADAPTIVE CITY MANAGER REPORT",
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "=" * 60,
            ""
        ]

        if not self.city_stats:
            lines.append("No city data available yet.")
            return "\n".join(lines)

        # Sort cities by P&L
        sorted_cities = sorted(
            self.city_stats.items(),
            key=lambda x: x[1].get('pnl', 0),
            reverse=True
        )

        for city, stats in sorted_cities:
            total_trades = stats.get('wins', 0) + stats.get('losses', 0)
            if total_trades == 0:
                continue

            win_rate = stats.get('wins', 0) / total_trades if total_trades > 0 else 0
            pnl = stats.get('pnl', 0)

            status = "✅ ENABLED"
            if self._is_currently_disabled(city):
                status = "❌ DISABLED"
            elif stats.get('trial_mode'):
                status = "🔄 TRIAL"

            lines.append(f"{city}: {status}")
            lines.append(f"   Win Rate: {win_rate:.1%} ({stats.get('wins', 0)}W-{stats.get('losses', 0)}L)")
            lines.append(f"   P&L: ${pnl:.2f}")
            lines.append(f"   Multiplier: {self.get_position_multiplier(f'KXHIGH{city}'):.2f}x")
            lines.append("")

        return "\n".join(lines)
