"""
Dashboard console output for Weather Trader Bot.
Renders a clean summary to the terminal while bot.log retains full detail.
"""
import os
import sys
import time
from collections import deque
from datetime import datetime


class DashboardState:
    """Collects scan stats, account data, and recent events for the dashboard."""

    def __init__(self):
        self.start_time = time.time()

        # Scan stats
        self.total_scans = 0
        self.total_errors = 0
        self.last_scan_time = None  # datetime
        self.last_scan_duration = 0.0
        self.last_scan_markets = 0
        self.last_scan_skipped = 0
        self.last_scan_traded = 0

        # Account data (updated each heartbeat / render)
        self.cash = 0.0
        self.portfolio_value = 0.0
        self.daily_pnl = 0.0
        self.daily_loss_limit = 0.0
        self.weather_exposure = 0.0

        # Positions & orders
        self.active_positions = 0
        self.resting_orders = 0
        self.session_placed = 0
        self.session_filled = 0
        self.session_canceled = 0

        # Recent activity (ring buffer of last 10 entries)
        self.recent_events: deque = deque(maxlen=10)

    # -- helpers to record events --

    def record_scan(self, markets: int, skipped: int, traded: int, duration: float):
        self.total_scans += 1
        self.last_scan_time = datetime.now()
        self.last_scan_duration = duration
        self.last_scan_markets = markets
        self.last_scan_skipped = skipped
        self.last_scan_traded = traded

    def record_error(self):
        self.total_errors += 1

    def record_trade(self, action: str, side: str, count: int, price: int, ticker: str):
        self.session_placed += 1
        ts = datetime.now().strftime('%H:%M')
        self.recent_events.appendleft(
            f"[{ts}] {action.upper()} {side.upper()} {count}x @ {price}c {ticker}"
        )

    def record_fill(self, action: str, side: str, count: int, price: int, ticker: str):
        self.session_filled += 1
        ts = datetime.now().strftime('%H:%M')
        self.recent_events.appendleft(
            f"[{ts}] FILL {side.upper()} {count}x @ {price}c {ticker}"
        )

    def record_cancel(self, order_id: str, reason: str = ''):
        self.session_canceled += 1
        ts = datetime.now().strftime('%H:%M')
        short_id = order_id[:8] if order_id else '?'
        detail = f" ({reason})" if reason else ''
        self.recent_events.appendleft(f"[{ts}] CANCEL {short_id}...{detail}")

    def record_settlement(self, ticker: str, won: bool, pnl: float):
        ts = datetime.now().strftime('%H:%M')
        result = 'WON' if won else 'LOST'
        self.recent_events.appendleft(
            f"[{ts}] SETTLED {ticker} {result} {'+' if pnl >= 0 else ''}{pnl:.2f}"
        )

    def update_account(self, cash: float, portfolio_value: float, daily_pnl: float,
                       daily_loss_limit: float, exposure: float):
        self.cash = cash
        self.portfolio_value = portfolio_value
        self.daily_pnl = daily_pnl
        self.daily_loss_limit = daily_loss_limit
        self.weather_exposure = exposure

    def update_positions(self, active: int, resting: int):
        self.active_positions = active
        self.resting_orders = resting


class Dashboard:
    """Renders the dashboard state to the console."""

    WIDTH = 60

    def __init__(self, state: DashboardState):
        self.state = state
        self._is_tty = sys.stdout.isatty()
        self.last_render_time = 0.0
        self.min_render_interval = 300  # 5 minutes default

    def render(self, force: bool = False):
        """Render the dashboard. Rate-limited unless force=True."""
        now = time.time()
        if not force and (now - self.last_render_time) < self.min_render_interval:
            return
        self.last_render_time = now

        s = self.state
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        uptime_h = (time.time() - s.start_time) / 3600

        sep = '=' * self.WIDTH
        thin = '-' * self.WIDTH

        lines = []
        lines.append(sep)
        lines.append(f"  WEATHER TRADER              {now_str}")
        lines.append(f"  Uptime: {uptime_h:.1f}h | Scans: {s.total_scans} | Errors: {s.total_errors}")
        lines.append(thin)

        # Account
        total = s.cash + s.portfolio_value
        pnl_sign = '+' if s.daily_pnl >= 0 else ''
        lines.append("  ACCOUNT")
        lines.append(f"  Cash: ${s.cash:.2f}  Portfolio: ${s.portfolio_value:.2f}  Total: ${total:.2f}")
        lines.append(f"  P&L: {pnl_sign}${s.daily_pnl:.2f} today                 Limit: -${s.daily_loss_limit:.2f}")
        lines.append(f"  Exposure: ${s.weather_exposure:.2f}")
        lines.append(thin)

        # Positions & Orders
        lines.append("  POSITIONS & ORDERS")
        lines.append(f"  Active: {s.active_positions} positions | Resting: {s.resting_orders} orders")
        lines.append(f"  Session: {s.session_placed} placed, {s.session_filled} filled, {s.session_canceled} canceled")
        lines.append(thin)

        # Last scan
        if s.last_scan_time:
            scan_ts = s.last_scan_time.strftime('%H:%M:%S')
            traded = s.last_scan_traded
            lines.append(f"  LAST SCAN ({scan_ts}, {s.last_scan_duration:.1f}s)")
            lines.append(f"  {s.last_scan_markets} markets | {s.last_scan_skipped} skipped | {traded} traded")
        else:
            lines.append("  LAST SCAN")
            lines.append("  (no scan yet)")
        lines.append(thin)

        # Recent activity
        lines.append("  RECENT ACTIVITY")
        if s.recent_events:
            for event in list(s.recent_events)[:6]:
                lines.append(f"  {event}")
        else:
            lines.append("  (no activity yet)")
        lines.append(sep)

        output = '\n'.join(lines)

        if self._is_tty:
            # Clear screen and move cursor to top
            print('\033[2J\033[H' + output, flush=True)
        else:
            # Non-TTY: just print with separator
            print('\n' + output, flush=True)
