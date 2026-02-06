"""
Dashboard console output for Weather Trader Bot.
Renders a clean summary to the terminal while bot.log retains full detail.
Style adapted from Crypto Trader Bot production dashboard.
"""
import os
import sys
import time
from collections import deque
from datetime import datetime


# ANSI color codes (matches Crypto Trader Bot palette)
C = {
    'reset':   '\x1b[0m',
    'bright':  '\x1b[1m',
    'dim':     '\x1b[2m',
    'green':   '\x1b[32m',
    'yellow':  '\x1b[33m',
    'blue':    '\x1b[34m',
    'magenta': '\x1b[35m',
    'cyan':    '\x1b[36m',
    'red':     '\x1b[31m',
    'white':   '\x1b[37m',
}

# Disable colors when not a TTY
if not sys.stdout.isatty():
    C = {k: '' for k in C}

SEPARATOR = f"{C['dim']}{'─' * 70}{C['reset']}"


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

        # Recent activity (ring buffer of last 8 entries)
        # Each entry: (icon, colored_message)
        self.recent_events: deque = deque(maxlen=8)

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
        ts = datetime.now().strftime('%H:%M:%S')
        side_color = C['green'] if side.upper() == 'YES' else C['red']
        self.recent_events.appendleft((
            ts,
            f"{C['green']}\u25b2{C['reset']}",
            f"{action.upper()} {side_color}{C['bright']}{side.upper()}{C['reset']} {count}x @ {price}c {C['dim']}{ticker}{C['reset']}",
        ))

    def record_fill(self, action: str, side: str, count: int, price: int, ticker: str):
        self.session_filled += 1
        ts = datetime.now().strftime('%H:%M:%S')
        self.recent_events.appendleft((
            ts,
            f"{C['green']}\u2713{C['reset']}",
            f"FILL {side.upper()} {count}x @ {price}c {C['dim']}{ticker}{C['reset']}",
        ))

    def record_cancel(self, order_id: str, reason: str = ''):
        self.session_canceled += 1
        ts = datetime.now().strftime('%H:%M:%S')
        short_id = order_id[:8] if order_id else '?'
        detail = f" ({reason})" if reason else ''
        self.recent_events.appendleft((
            ts,
            f"{C['red']}\u2717{C['reset']}",
            f"CANCEL {short_id}...{detail}",
        ))

    def record_settlement(self, ticker: str, won: bool, pnl: float):
        ts = datetime.now().strftime('%H:%M:%S')
        if won:
            icon = f"{C['green']}${C['reset']}"
            result = f"{C['green']}WON{C['reset']}"
            pnl_str = f"{C['green']}+${pnl:.2f}{C['reset']}"
        else:
            icon = f"{C['red']}${C['reset']}"
            result = f"{C['red']}LOST{C['reset']}"
            pnl_str = f"{C['red']}-${abs(pnl):.2f}{C['reset']}"
        self.recent_events.appendleft((
            ts,
            icon,
            f"SETTLED {C['dim']}{ticker}{C['reset']} {result} {pnl_str}",
        ))

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

    def __init__(self, state: DashboardState):
        self.state = state
        self._is_tty = sys.stdout.isatty()
        self.last_render_time = 0.0
        self.min_render_interval = 300  # 5 minutes default

    def _format_elapsed(self, seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        return f"{h}h {m}m {s}s"

    def render(self, force: bool = False):
        """Render the dashboard. Rate-limited unless force=True."""
        now = time.time()
        if not force and (now - self.last_render_time) < self.min_render_interval:
            return
        self.last_render_time = now

        s = self.state
        c = C
        elapsed = self._format_elapsed(now - s.start_time)
        total = s.cash + s.portfolio_value

        # P&L color
        pnl_color = c['green'] if s.daily_pnl >= 0 else c['red']
        pnl_sign = '+' if s.daily_pnl >= 0 else ''

        lines = []

        # ── Header ──
        lines.append(
            f" {c['bright']}{c['cyan']}WEATHER TRADER{c['reset']}"
            f"  {c['dim']}|{c['reset']}"
            f"  {pnl_color}{c['bright']}{pnl_sign}${s.daily_pnl:.2f}{c['reset']} P&L"
            f"  {c['dim']}|{c['reset']}"
            f"  {s.session_placed} trades"
            f"  {c['dim']}|{c['reset']}"
            f"  {s.active_positions} pos"
            f"  {c['dim']}|{c['reset']}"
            f"  {c['dim']}{elapsed}{c['reset']}"
        )
        lines.append(SEPARATOR)

        # ── Account ──
        lines.append(
            f" {c['white']}${s.cash:.2f}{c['reset']} cash"
            f"  {c['white']}${s.portfolio_value:.2f}{c['reset']} portfolio"
            f"  {c['bright']}${total:.2f}{c['reset']} total"
            f"     {c['dim']}Exp:{c['reset']} ${s.weather_exposure:.2f}"
        )
        lines.append(
            f" {c['dim']}Limit:{c['reset']} -${s.daily_loss_limit:.2f}"
            f"              {c['dim']}Resting:{c['reset']} {s.resting_orders} orders"
            f"     {c['dim']}Filled:{c['reset']} {s.session_filled}"
        )
        lines.append(SEPARATOR)

        # ── Last Scan ──
        if s.last_scan_time:
            scan_ts = s.last_scan_time.strftime('%H:%M:%S')
            traded_color = c['green'] if s.last_scan_traded > 0 else c['dim']
            lines.append(
                f" {c['dim']}Scan {s.total_scans}{c['reset']}"
                f"  {scan_ts}"
                f"  {c['dim']}({s.last_scan_duration:.1f}s){c['reset']}"
                f"  {s.last_scan_markets} markets"
                f"  {c['dim']}|{c['reset']} {s.last_scan_skipped} skip"
                f"  {c['dim']}|{c['reset']} {traded_color}{s.last_scan_traded} traded{c['reset']}"
            )
        else:
            lines.append(f" {c['dim']}No scan yet{c['reset']}")
        lines.append(SEPARATOR)

        # ── Event Feed ──
        if s.recent_events:
            for ts, icon, msg in list(s.recent_events)[:8]:
                lines.append(f"  {c['dim']}{ts}{c['reset']}  {icon} {msg}")
        else:
            lines.append(f"  {c['dim']}No activity yet...{c['reset']}")
        lines.append(SEPARATOR)

        # ── Footer ──
        now_str = datetime.now().strftime('%H:%M:%S')
        err_str = ''
        if s.total_errors > 0:
            err_str = f"  {c['dim']}|{c['reset']}  {c['red']}{s.total_errors} errors{c['reset']}"
        lines.append(f"  {c['dim']}{now_str}  |  Ctrl+C to stop{c['reset']}{err_str}")

        output = '\n'.join(lines)

        if self._is_tty:
            print('\033[2J\033[H' + output, flush=True)
        else:
            print('\n' + output, flush=True)
