"""
Dashboard console output for Weather Trader Bot.
Renders a clean summary to the terminal while bot.log retains full detail.
Style matched to Crypto Trader Bot production dashboard.
"""
import sys
import time
from collections import deque
from datetime import datetime
from .config import Config


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

SEP = f"{C['dim']}{'─' * 70}{C['reset']}"

# Strategy mode display labels and colors
MODE_DISPLAY = {
    'conservative': ('CON', 'cyan'),
    'longshot':     ('LSH', 'magenta'),
    'observation':  ('OBS', 'yellow'),
}


class DashboardState:
    """Collects scan stats, account data, and recent events for the dashboard."""

    def __init__(self):
        self.start_time = time.time()

        # Scan stats
        self.total_scans = 0
        self.total_errors = 0
        self.last_scan_time = None
        self.last_scan_duration = 0.0
        self.last_scan_markets = 0
        self.last_scan_skipped = 0
        self.last_scan_traded = 0

        # Account
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

        # Win/loss tracking
        self.session_wins = 0
        self.session_losses = 0

        # Strategy status
        self.drawdown_level = 'NORMAL'
        self.drawdown_consecutive = 0
        self.drawdown_multiplier = 1.0
        self.forecast_sources = 0
        self.cities_enabled = []
        self.cities_disabled = []

        # Per-city stats {city: {wins, losses, pnl}}
        self.city_stats = {}

        # Per-type stats {type: {wins, losses, pnl}} — 'threshold' vs 'range'
        self.type_stats = {'threshold': {'wins': 0, 'losses': 0, 'pnl': 0.0},
                           'range': {'wins': 0, 'losses': 0, 'pnl': 0.0}}

        # Recent activity (ring buffer)
        self.recent_events: deque = deque(maxlen=8)

    # ── record helpers ──

    def record_scan(self, markets: int, skipped: int, traded: int, duration: float):
        self.total_scans += 1
        self.last_scan_time = datetime.now()
        self.last_scan_duration = duration
        self.last_scan_markets = markets
        self.last_scan_skipped = skipped
        self.last_scan_traded = traded

    def record_error(self):
        self.total_errors += 1

    def record_trade(self, action: str, side: str, count: int, price: int,
                     ticker: str, strategy_mode: str = '', edge: float = 0.0):
        self.session_placed += 1
        ts = datetime.now().strftime('%H:%M:%S')
        side_color = C['green'] if side.upper() == 'YES' else C['red']
        mode_label, mode_color_key = MODE_DISPLAY.get(strategy_mode, ('', 'dim'))
        mode_tag = f"{C[mode_color_key]}{mode_label}{C['reset']} " if mode_label else ''
        edge_tag = f" {C['dim']}({edge:.0f}%){C['reset']}" if edge > 0 else ''
        self.recent_events.appendleft((
            ts,
            f"{C['green']}\u25b2{C['reset']}",
            f"{mode_tag}{action.upper()} {side_color}{C['bright']}{side.upper()}{C['reset']}"
            f" {count}x @ {price}c{edge_tag} {C['dim']}{ticker}{C['reset']}",
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
        if won:
            self.session_wins += 1
        else:
            self.session_losses += 1

        # Update per-city stats
        city = ''
        for prefix in ('KXHIGH', 'KXLOW'):
            if ticker.startswith(prefix):
                rest = ticker[len(prefix):]
                city = rest.split('-')[0] if '-' in rest else rest
                break
        if city:
            if city not in self.city_stats:
                self.city_stats[city] = {'wins': 0, 'losses': 0, 'pnl': 0.0}
            cs = self.city_stats[city]
            if won:
                cs['wins'] += 1
            else:
                cs['losses'] += 1
            cs['pnl'] += pnl if won else -abs(pnl)

        # Update per-type stats (threshold vs range)
        parts = ticker.split('-')
        market_type = 'threshold' if len(parts) >= 3 and parts[-1].startswith('T') else 'range'
        ts_stats = self.type_stats[market_type]
        if won:
            ts_stats['wins'] += 1
        else:
            ts_stats['losses'] += 1
        ts_stats['pnl'] += pnl if won else -abs(pnl)

        ts = datetime.now().strftime('%H:%M:%S')
        if won:
            icon = f"{C['green']}${C['reset']}"
            pnl_str = f"{C['green']}WON +${pnl:.2f}{C['reset']}"
        else:
            icon = f"{C['red']}${C['reset']}"
            pnl_str = f"{C['red']}LOST -${abs(pnl):.2f}{C['reset']}"
        self.recent_events.appendleft((
            ts, icon,
            f"SETTLED {C['dim']}{ticker}{C['reset']} {pnl_str}",
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

    def update_strategy_status(self, drawdown_level: str = 'NORMAL',
                               drawdown_consecutive: int = 0,
                               drawdown_multiplier: float = 1.0,
                               forecast_sources: int = 0,
                               cities_enabled: list = None,
                               cities_disabled: list = None):
        self.drawdown_level = drawdown_level
        self.drawdown_consecutive = drawdown_consecutive
        self.drawdown_multiplier = drawdown_multiplier
        self.forecast_sources = forecast_sources
        if cities_enabled is not None:
            self.cities_enabled = cities_enabled
        if cities_disabled is not None:
            self.cities_disabled = cities_disabled


class Dashboard:
    """Renders the dashboard state to the console (Crypto Bot style)."""

    def __init__(self, state: DashboardState):
        self.state = state
        self._is_tty = sys.stdout.isatty()
        self.last_render_time = 0.0
        self.min_render_interval = 300  # seconds

    @staticmethod
    def _elapsed(seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        return f"{h}h {m}m {s}s"

    def render(self, force: bool = False):
        now = time.time()
        if not force and (now - self.last_render_time) < self.min_render_interval:
            return
        self.last_render_time = now

        s = self.state
        c = C
        elapsed = self._elapsed(now - s.start_time)
        total = s.cash + s.portfolio_value
        pnl_c = c['green'] if s.daily_pnl >= 0 else c['red']
        pnl_sign = '+' if s.daily_pnl >= 0 else ''

        lines = []

        # ── Header ──
        paper = f"  {c['yellow']}{c['bright']}[PAPER]{c['reset']}" if Config.PAPER_TRADING else ""
        lines.append(
            f"{c['bright']}{c['cyan']} WEATHER TRADER{c['reset']}{paper}"
            f"  {c['dim']}|{c['reset']}  {pnl_c}{c['bright']}{pnl_sign}${s.daily_pnl:.2f}{c['reset']} P&L"
            f"  {c['dim']}|{c['reset']}  {s.session_placed} trades"
            f"  {c['dim']}|{c['reset']}  {s.active_positions} pos"
            f"  {c['dim']}|{c['reset']}  {c['dim']}{elapsed}{c['reset']}"
        )
        lines.append(SEP)

        # ── Account (one compact block) ──
        lines.append(
            f" {c['white']}${s.cash:.2f}{c['reset']} cash"
            f"  {c['white']}${s.portfolio_value:.2f}{c['reset']} portfolio"
            f"  {c['bright']}${total:.2f}{c['reset']} total"
            f"     {c['dim']}exp{c['reset']} ${s.weather_exposure:.2f}"
        )
        # Win rate inline with limits
        settled = s.session_wins + s.session_losses
        if settled > 0:
            wr = s.session_wins / settled * 100
            wr_c = c['green'] if wr >= 50 else c['red']
            wr_str = f"{wr_c}{wr:.0f}%{c['reset']} ({s.session_wins}W/{s.session_losses}L)"
        else:
            wr_str = f"{c['dim']}0W/0L{c['reset']}"
        lines.append(
            f" {c['dim']}limit{c['reset']} -${s.daily_loss_limit:.2f}"
            f"  {c['dim']}resting{c['reset']} {s.resting_orders}"
            f"  {c['dim']}filled{c['reset']} {s.session_filled}"
            f"  {c['dim']}|{c['reset']}  {c['dim']}win{c['reset']} {wr_str}"
        )

        # ── Per-city lines (like Crypto Bot per-asset) ──
        lines.append(SEP)
        all_cities = sorted(set(s.cities_enabled + s.cities_disabled))
        if not all_cities:
            # Fallback: derive from WEATHER_SERIES
            seen = set()
            for series in Config.WEATHER_SERIES:
                city = series.replace('KXHIGH', '').replace('KXLOW', '')
                if city not in seen:
                    seen.add(city)
                    all_cities.append(city)

        for city in all_cities:
            is_hard_disabled = city.upper() in Config.DISABLED_CITIES
            is_adaptive_disabled = city in s.cities_disabled and not is_hard_disabled
            is_enabled = city in s.cities_enabled

            # City name + status tag
            if is_hard_disabled:
                status_tag = f"{c['red']}OFF{c['reset']}"
            elif is_adaptive_disabled:
                status_tag = f"{c['yellow']}ADAPT{c['reset']}"
            else:
                status_tag = f"{c['green']}ON{c['reset']}"

            # Per-city win/loss/P&L
            cs = s.city_stats.get(city, {})
            wins = cs.get('wins', 0)
            losses = cs.get('losses', 0)
            city_pnl = cs.get('pnl', 0.0)
            city_settled = wins + losses

            if city_settled > 0:
                city_wr = wins / city_settled * 100
                city_wr_c = c['green'] if city_wr >= 50 else c['red']
                pnl_c2 = c['green'] if city_pnl >= 0 else c['red']
                stats_str = (
                    f"{city_wr_c}{city_wr:.0f}%{c['reset']}"
                    f" {c['dim']}({wins}W/{losses}L){c['reset']}"
                    f"  {pnl_c2}${city_pnl:+.2f}{c['reset']}"
                )
            else:
                stats_str = f"{c['dim']}--{c['reset']}"

            lines.append(f" {c['bright']}{city.ljust(5)}{c['reset']} {status_tag}  {stats_str}")

        # ── Threshold vs Range P&L ──
        th = s.type_stats['threshold']
        rg = s.type_stats['range']
        th_settled = th['wins'] + th['losses']
        rg_settled = rg['wins'] + rg['losses']

        type_parts = []
        if th_settled > 0:
            th_wr = th['wins'] / th_settled * 100
            th_wr_c = c['green'] if th_wr >= 50 else c['red']
            th_pnl_c = c['green'] if th['pnl'] >= 0 else c['red']
            type_parts.append(f" {c['bright']}THRESH{c['reset']} {th_wr_c}{th_wr:.0f}%{c['reset']} ({th['wins']}W/{th['losses']}L) {th_pnl_c}${th['pnl']:+.2f}{c['reset']}")

        if rg_settled > 0:
            rg_wr = rg['wins'] / rg_settled * 100
            rg_wr_c = c['green'] if rg_wr >= 50 else c['red']
            rg_pnl_c = c['green'] if rg['pnl'] >= 0 else c['red']
            type_parts.append(f" {c['bright']}RANGE{c['reset']}  {rg_wr_c}{rg_wr:.0f}%{c['reset']} ({rg['wins']}W/{rg['losses']}L) {rg_pnl_c}${rg['pnl']:+.2f}{c['reset']}")

        if type_parts:
            lines.append(SEP)
            for tp in type_parts:
                lines.append(tp)

        # ── Drawdown warning (only shown when active — matches Crypto Bot) ──
        if s.drawdown_level == 'PAUSED':
            lines.append(f" {c['red']}{c['bright']}PAUSED — drawdown limit ({s.drawdown_consecutive} consecutive losses){c['reset']}")
        elif s.drawdown_consecutive > 0 and s.drawdown_level != 'NORMAL':
            lines.append(f" {c['yellow']}drawdown {s.drawdown_level} ({s.drawdown_multiplier:.0%} size, {s.drawdown_consecutive}L streak){c['reset']}")

        # ── Scan + ops ──
        lines.append(SEP)
        if s.last_scan_time:
            scan_ts = s.last_scan_time.strftime('%H:%M:%S')
            traded_c = c['green'] if s.last_scan_traded > 0 else c['dim']
            lines.append(
                f" {c['dim']}scan {s.total_scans}{c['reset']}"
                f"  {scan_ts}"
                f"  {c['dim']}({s.last_scan_duration:.1f}s){c['reset']}"
                f"  {s.last_scan_markets} mkts"
                f"  {c['dim']}|{c['reset']} {s.last_scan_skipped} skip"
                f"  {c['dim']}|{c['reset']} {traded_c}{s.last_scan_traded} traded{c['reset']}"
                f"  {c['dim']}|{c['reset']} {c['dim']}src{c['reset']} {s.forecast_sources}"
            )
        else:
            lines.append(f" {c['dim']}no scan yet{c['reset']}")

        # ── Event feed ──
        if s.recent_events:
            lines.append(SEP)
            for ts, icon, msg in list(s.recent_events)[:8]:
                lines.append(f"  {c['dim']}{ts}{c['reset']}  {icon} {msg}")

        # ── Footer ──
        lines.append(SEP)
        import os
        err_str = ''
        if s.total_errors > 0:
            err_str = f"  {c['dim']}|{c['reset']}  {c['red']}{s.total_errors} errors{c['reset']}"
        lines.append(
            f"  {c['dim']}{datetime.now().strftime('%H:%M:%S')}"
            f"  |  PID {os.getpid()}"
            f"  |  Ctrl+C to stop{c['reset']}{err_str}"
        )

        output = '\n'.join(lines)

        if self._is_tty:
            # Clear screen + scrollback (matches Crypto Bot)
            sys.stdout.write('\x1b[H\x1b[2J\x1b[3J')
            print(output, flush=True)
        else:
            print('\n' + output, flush=True)
