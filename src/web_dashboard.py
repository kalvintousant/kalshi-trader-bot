"""
Web dashboard for Weather Trader Bot.
Serves a Chart.js-based HTML dashboard via aiohttp on a daemon thread.
Zero new dependencies — aiohttp is already installed.
"""

import asyncio
import csv
import json
import logging
import threading
import time
from datetime import datetime
from pathlib import Path

from aiohttp import web

from .config import Config, extract_city_code

logger = logging.getLogger(__name__)


class WebDashboard:
    """aiohttp web server that exposes bot state as JSON + an HTML dashboard."""

    def __init__(self, dashboard_state, bot):
        self.state = dashboard_state
        self.bot = bot
        self.host = Config.WEB_DASHBOARD_HOST
        self.port = Config.WEB_DASHBOARD_PORT
        self._sse_clients = []

    def start_background(self):
        """Spawn a daemon thread running the aiohttp server."""
        t = threading.Thread(target=self._run_server, daemon=True)
        t.start()

    def _run_server(self):
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            app = self._create_app()
            runner = web.AppRunner(app)
            loop.run_until_complete(runner.setup())
            site = web.TCPSite(runner, self.host, self.port)
            loop.run_until_complete(site.start())
            logger.info(f"Web dashboard listening on http://{self.host}:{self.port}")
            loop.run_forever()
        except OSError as e:
            logger.error(f"Web dashboard failed to start: {e} — kill the process on port {self.port} or change WEB_DASHBOARD_PORT")
        except Exception as e:
            logger.error(f"Web dashboard crashed: {e}", exc_info=True)

    def _create_app(self):
        app = web.Application()
        app.router.add_get('/', self.handle_index)
        app.router.add_get('/api/status', self.handle_status)
        app.router.add_get('/api/pnl', self.handle_pnl)
        app.router.add_get('/api/cities', self.handle_cities)
        app.router.add_get('/api/trades', self.handle_trades)
        app.router.add_get('/api/positions', self.handle_positions)
        app.router.add_get('/api/events', self.handle_events_sse)
        return app

    # ── Handlers ──

    async def handle_index(self, request):
        return web.Response(text=HTML_TEMPLATE, content_type='text/html')

    async def handle_status(self, request):
        s = self.state
        uptime = time.time() - s.start_time
        settled = s.session_wins + s.session_losses
        win_rate = (s.session_wins / settled * 100) if settled else 0

        city_data = {}
        for city, cs in s.city_stats.items():
            w, l = cs['wins'], cs['losses']
            city_data[city] = {
                'wins': w,
                'losses': l,
                'pnl': round(cs['pnl'], 2),
                'win_rate': round(w / (w + l) * 100, 1) if (w + l) else 0,
            }

        events = []
        for ts, icon, msg in list(s.recent_events)[:20]:
            # Strip ANSI codes for JSON
            import re
            clean = re.sub(r'\x1b\[[0-9;]*m', '', msg)
            events.append({'time': ts, 'msg': clean})

        data = {
            'paper_mode': Config.PAPER_TRADING,
            'uptime_s': round(uptime),
            'cash': round(s.cash, 2),
            'portfolio_value': round(s.portfolio_value, 2),
            'daily_pnl': round(s.daily_pnl, 2),
            'daily_loss_limit': round(s.daily_loss_limit, 2),
            'exposure': round(s.weather_exposure, 2),
            'positions': s.active_positions,
            'resting_orders': s.resting_orders,
            'wins': s.session_wins,
            'losses': s.session_losses,
            'win_rate': round(win_rate, 1),
            'trades_placed': s.session_placed,
            'drawdown_level': s.drawdown_level,
            'drawdown_consecutive': s.drawdown_consecutive,
            'drawdown_multiplier': s.drawdown_multiplier,
            'forecast_sources': s.forecast_sources,
            'cities_enabled': s.cities_enabled,
            'cities_disabled': s.cities_disabled,
            'scans': s.total_scans,
            'errors': s.total_errors,
            'last_scan_duration': round(s.last_scan_duration, 1),
            'last_scan_markets': s.last_scan_markets,
            'cities': city_data,
            'events': events,
        }
        return web.json_response(data)

    async def handle_pnl(self, request):
        """Parse outcomes CSV to build daily P&L series."""
        daily = {}
        outcomes_file = Path('data/paper_outcomes.csv') if Config.PAPER_TRADING else Path('data/outcomes.csv')
        if outcomes_file.exists():
            try:
                with open(outcomes_file, 'r') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        ts = row.get('timestamp', '')
                        date = ts[:10] if len(ts) >= 10 else ''
                        if not date:
                            continue
                        try:
                            pnl = float(row.get('profit_loss', 0))
                            won = row.get('won', '') == 'YES'
                            if not won:
                                pnl = -abs(pnl)
                        except (ValueError, TypeError):
                            continue
                        if date not in daily:
                            daily[date] = {'pnl': 0.0, 'trades': 0, 'wins': 0, 'losses': 0}
                        daily[date]['pnl'] += pnl
                        daily[date]['trades'] += 1
                        if won:
                            daily[date]['wins'] += 1
                        else:
                            daily[date]['losses'] += 1
            except Exception as e:
                logger.debug(f"Error parsing outcomes CSV: {e}")

        cumulative = 0.0
        series = []
        for date in sorted(daily.keys()):
            d = daily[date]
            cumulative += d['pnl']
            series.append({
                'date': date,
                'pnl': round(d['pnl'], 2),
                'cumulative': round(cumulative, 2),
                'trades': d['trades'],
                'wins': d['wins'],
                'losses': d['losses'],
            })

        return web.json_response({
            'daily': series,
            'total_pnl': round(cumulative, 2),
        })

    async def handle_cities(self, request):
        """City-level stats from dashboard state."""
        s = self.state
        cities = {}
        all_city_codes = set()
        for series in Config.WEATHER_SERIES:
            all_city_codes.add(extract_city_code(series))

        for city in sorted(all_city_codes):
            cs = s.city_stats.get(city, {})
            w, l = cs.get('wins', 0), cs.get('losses', 0)
            enabled = city in s.cities_enabled
            hard_disabled = city.upper() in Config.DISABLED_CITIES
            cp = s.city_positions.get(city, {})
            cities[city] = {
                'enabled': enabled,
                'hard_disabled': hard_disabled,
                'wins': w,
                'losses': l,
                'pnl': round(cs.get('pnl', 0.0), 2),
                'win_rate': round(w / (w + l) * 100, 1) if (w + l) else 0,
                'high_positions': len(cp.get('high', set())),
                'low_positions': len(cp.get('low', set())),
            }
        return web.json_response(cities)

    async def handle_trades(self, request):
        """Return recent trades from trades.csv."""
        limit = int(request.query.get('limit', '200'))
        trades_file = Path('data/trades.csv')
        rows = []
        if trades_file.exists():
            try:
                with open(trades_file, 'r') as f:
                    reader = csv.DictReader(f)
                    all_rows = list(reader)
                    for row in all_rows[-limit:]:
                        rows.append({
                            'timestamp': row.get('timestamp', ''),
                            'ticker': row.get('market_ticker', ''),
                            'action': row.get('action', ''),
                            'side': row.get('side', ''),
                            'count': row.get('count', ''),
                            'price': row.get('price', ''),
                            'edge': row.get('edge', ''),
                            'ev': row.get('ev', ''),
                            'strategy': row.get('strategy_mode', ''),
                            'status': row.get('status', ''),
                        })
            except Exception as e:
                logger.debug(f"Error reading trades CSV: {e}")
        return web.json_response({'trades': rows})

    async def handle_positions(self, request):
        """Return unsettled paper positions with details."""
        trades_file = Path('data/trades.csv')
        outcomes_file = Path('data/paper_outcomes.csv') if Config.PAPER_TRADING else Path('data/outcomes.csv')

        # Gather settled tickers
        settled = set()
        if outcomes_file.exists():
            try:
                with open(outcomes_file, 'r') as f:
                    for row in csv.DictReader(f):
                        settled.add(row.get('market_ticker', ''))
            except Exception:
                pass

        # Build net positions from trades.csv (buys add, sells subtract)
        positions = {}  # ticker -> {side, qty, cost, ...}
        if trades_file.exists():
            try:
                with open(trades_file, 'r') as f:
                    for row in csv.DictReader(f):
                        order_id = row.get('order_id', '')
                        if not order_id.startswith('PAPER-'):
                            continue
                        ticker = row.get('market_ticker', '')
                        if not ticker or ticker in settled:
                            continue
                        action = row.get('action', '').lower()
                        side = row.get('side', '')
                        try:
                            count = int(row.get('count', 0))
                            price = int(float(row.get('price', 0)))
                        except (ValueError, TypeError):
                            continue

                        if ticker not in positions:
                            positions[ticker] = {
                                'ticker': ticker,
                                'side': side,
                                'qty': 0,
                                'total_cost': 0,
                                'entry_price': price,
                                'entry_time': row.get('timestamp', ''),
                                'edge': row.get('edge', ''),
                                'ev': row.get('ev', ''),
                                'strategy': row.get('strategy_mode', ''),
                                'our_prob': row.get('our_probability', ''),
                                'mean_forecast': row.get('mean_forecast', ''),
                                'threshold': row.get('threshold', ''),
                                'target_date': row.get('target_date', ''),
                                'num_sources': row.get('num_sources', ''),
                            }
                        p = positions[ticker]
                        if action == 'buy':
                            p['total_cost'] += count * price
                            p['qty'] += count
                        elif action == 'sell':
                            p['total_cost'] -= count * price
                            p['qty'] -= count
            except Exception as e:
                logger.debug(f"Error reading trades for positions: {e}")

        # Filter to positions with qty > 0 and compute avg entry
        result = []
        for ticker, p in positions.items():
            if p['qty'] <= 0:
                continue
            avg_entry = round(p['total_cost'] / p['qty']) if p['qty'] > 0 else 0
            series = ticker.split('-')[0] if '-' in ticker else ticker
            city = extract_city_code(series)
            market_type = 'HIGH' if 'HIGH' in series.upper() else 'LOW'
            max_gain = round(p['qty'] * (100 - avg_entry) / 100, 2)
            max_loss = round(p['qty'] * avg_entry / 100, 2)
            result.append({
                'ticker': ticker,
                'city': city,
                'type': market_type,
                'side': p['side'],
                'qty': p['qty'],
                'avg_entry': avg_entry,
                'max_gain': max_gain,
                'max_loss': max_loss,
                'edge': p['edge'],
                'our_prob': p['our_prob'],
                'mean_forecast': p['mean_forecast'],
                'threshold': p['threshold'],
                'target_date': p['target_date'],
                'strategy': p['strategy'],
                'entry_time': p['entry_time'],
                'num_sources': p['num_sources'],
            })

        # Sort by target date, then ticker
        result.sort(key=lambda x: (x['target_date'], x['ticker']))
        return web.json_response({'positions': result})

    async def handle_events_sse(self, request):
        """Server-Sent Events stream for live updates."""
        response = web.StreamResponse()
        response.content_type = 'text/event-stream'
        response.headers['Cache-Control'] = 'no-cache'
        response.headers['X-Accel-Buffering'] = 'no'
        await response.prepare(request)

        last_event_count = len(self.state.recent_events)
        last_scan_count = self.state.total_scans
        try:
            while True:
                # Push new events
                current_count = len(self.state.recent_events)
                current_scans = self.state.total_scans
                if current_count != last_event_count or current_scans != last_scan_count:
                    import re
                    events = []
                    for ts, icon, msg in list(self.state.recent_events)[:10]:
                        clean = re.sub(r'\x1b\[[0-9;]*m', '', msg)
                        events.append({'time': ts, 'msg': clean})
                    payload = json.dumps({
                        'type': 'update',
                        'events': events,
                        'scans': current_scans,
                        'daily_pnl': round(self.state.daily_pnl, 2),
                        'wins': self.state.session_wins,
                        'losses': self.state.session_losses,
                    })
                    await response.write(f"data: {payload}\n\n".encode())
                    last_event_count = current_count
                    last_scan_count = current_scans

                await asyncio.sleep(3)
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        return response


# ── HTML Template ──

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Weather Trader Bot</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
  :root {
    --bg: #0d1117; --surface: #161b22; --border: #30363d;
    --text: #c9d1d9; --text-dim: #8b949e; --text-bright: #f0f6fc;
    --green: #3fb950; --red: #f85149; --yellow: #d29922;
    --blue: #58a6ff; --cyan: #39d2c0; --purple: #bc8cff;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { background: var(--bg); color: var(--text); font-family: 'SF Mono', 'Fira Code', monospace; font-size: 13px; }
  .container { max-width: 1200px; margin: 0 auto; padding: 16px; }

  /* Header */
  .header { display: flex; align-items: center; gap: 16px; padding: 12px 16px; background: var(--surface); border: 1px solid var(--border); border-radius: 8px; margin-bottom: 12px; flex-wrap: wrap; }
  .header .title { font-size: 16px; font-weight: 700; color: var(--cyan); }
  .header .badge { padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; }
  .badge.paper { background: #d2992233; color: var(--yellow); }
  .badge.live { background: #f8514933; color: var(--red); }
  .header .stat { color: var(--text-dim); }
  .header .stat .val { color: var(--text-bright); font-weight: 600; }
  .pnl-pos { color: var(--green); }
  .pnl-neg { color: var(--red); }

  /* Grid */
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 12px; }
  @media (max-width: 768px) { .grid { grid-template-columns: 1fr; } }
  .card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 14px; }
  .card h3 { font-size: 12px; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 10px; }

  /* Account card */
  .account-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
  .account-item { }
  .account-item .label { font-size: 11px; color: var(--text-dim); }
  .account-item .value { font-size: 16px; font-weight: 600; color: var(--text-bright); }
  .account-item .value.small { font-size: 13px; }

  /* City table */
  .city-table { width: 100%; border-collapse: collapse; }
  .city-table th { text-align: left; font-size: 11px; color: var(--text-dim); padding: 4px 8px; border-bottom: 1px solid var(--border); }
  .city-table td { padding: 4px 8px; font-size: 12px; }
  .city-table tr:hover { background: #ffffff08; }
  .city-on { color: var(--green); }
  .city-off { color: var(--red); }

  /* Event feed */
  .feed { max-height: 280px; overflow-y: auto; }
  .feed-item { padding: 4px 0; border-bottom: 1px solid #ffffff06; display: flex; gap: 8px; font-size: 12px; }
  .feed-item .time { color: var(--text-dim); min-width: 60px; }
  .feed-item .msg { color: var(--text); word-break: break-all; }

  /* Footer */
  .footer { text-align: center; color: var(--text-dim); font-size: 11px; padding: 8px; }

  /* Charts */
  .chart-container { position: relative; height: 200px; }

  /* Drawdown banner */
  .drawdown-banner { background: #f8514922; border: 1px solid var(--red); border-radius: 6px; padding: 8px 12px; margin-bottom: 12px; color: var(--red); font-weight: 600; text-align: center; display: none; }

  /* Trades table */
  .trades-table { width: 100%; border-collapse: collapse; font-size: 11px; }
  .trades-table th { text-align: left; color: var(--text-dim); padding: 4px 6px; border-bottom: 1px solid var(--border); }
  .trades-table td { padding: 3px 6px; }
  .trades-table tr:hover { background: #ffffff08; }

  /* Positions table */
  .pos-table { width: 100%; border-collapse: collapse; font-size: 11px; }
  .pos-table th { text-align: left; color: var(--text-dim); padding: 5px 8px; border-bottom: 1px solid var(--border); font-size: 10px; text-transform: uppercase; letter-spacing: 0.3px; }
  .pos-table td { padding: 5px 8px; }
  .pos-table tr:hover { background: #ffffff08; }
  .pos-table .ticker { font-weight: 600; }
  .pos-table .ticker a { color: var(--blue); text-decoration: none; }
  .pos-table .ticker a:hover { text-decoration: underline; color: #5fa8ff; }
  .pos-table .side-yes { color: var(--green); font-weight: 600; }
  .pos-table .side-no { color: var(--red); font-weight: 600; }
  .pos-empty { color: var(--text-dim); text-align: center; padding: 20px; font-style: italic; }
</style>
</head>
<body>
<div class="container">
  <!-- Header -->
  <div class="header">
    <span class="title">WEATHER TRADER BOT</span>
    <span id="modeBadge" class="badge paper">PAPER</span>
    <span class="stat">P&L <span id="headerPnl" class="val pnl-pos">$0.00</span></span>
    <span class="stat">Trades <span id="headerTrades" class="val">0</span></span>
    <span class="stat">W/L <span id="headerWL" class="val">0/0</span></span>
    <span class="stat">Uptime <span id="headerUptime" class="val">0m</span></span>
  </div>

  <!-- Drawdown banner -->
  <div id="drawdownBanner" class="drawdown-banner"></div>

  <!-- Charts row -->
  <div class="grid">
    <div class="card">
      <h3>Cumulative P&L</h3>
      <div class="chart-container"><canvas id="cumPnlChart"></canvas></div>
    </div>
    <div class="card">
      <h3>Daily P&L</h3>
      <div class="chart-container"><canvas id="dailyPnlChart"></canvas></div>
    </div>
  </div>

  <!-- Account + Cities row -->
  <div class="grid">
    <div class="card">
      <h3>Account</h3>
      <div class="account-grid">
        <div class="account-item"><div class="label">Cash</div><div id="accCash" class="value">$0.00</div></div>
        <div class="account-item"><div class="label">Portfolio</div><div id="accPortfolio" class="value">$0.00</div></div>
        <div class="account-item"><div class="label">Total</div><div id="accTotal" class="value">$0.00</div></div>
        <div class="account-item"><div class="label">Exposure</div><div id="accExposure" class="value small">$0.00</div></div>
        <div class="account-item"><div class="label">Positions</div><div id="accPositions" class="value small">0</div></div>
        <div class="account-item"><div class="label">Loss Limit</div><div id="accLimit" class="value small">$0.00</div></div>
      </div>
    </div>
    <div class="card">
      <h3>Cities</h3>
      <table class="city-table">
        <thead><tr><th>City</th><th>Status</th><th>W/L</th><th>Win%</th><th>P&L</th></tr></thead>
        <tbody id="cityTableBody"></tbody>
      </table>
    </div>
  </div>

  <!-- Active Positions -->
  <div class="card" style="margin-bottom:12px">
    <h3>Active Positions <span id="posCount" style="color:var(--cyan)"></span></h3>
    <div style="max-height:260px;overflow-y:auto">
      <table class="pos-table">
        <thead><tr><th>Date</th><th>City</th><th>Ticker</th><th>Side</th><th>Qty</th><th>Entry</th><th>Edge</th><th>Prob</th><th>Forecast</th><th>Threshold</th><th>Max Gain</th><th>Max Loss</th></tr></thead>
        <tbody id="posBody"><tr><td colspan="12" class="pos-empty">Loading...</td></tr></tbody>
      </table>
    </div>
  </div>

  <!-- City chart + Live feed -->
  <div class="grid">
    <div class="card">
      <h3>City Performance</h3>
      <div class="chart-container"><canvas id="cityChart"></canvas></div>
    </div>
    <div class="card">
      <h3>Live Feed</h3>
      <div id="eventFeed" class="feed"></div>
    </div>
  </div>

  <!-- Recent trades -->
  <div class="card" style="margin-bottom:12px">
    <h3>Recent Trades</h3>
    <div style="max-height:220px;overflow-y:auto">
      <table class="trades-table">
        <thead><tr><th>Time</th><th>Ticker</th><th>Side</th><th>Qty</th><th>Price</th><th>Edge</th><th>Strategy</th></tr></thead>
        <tbody id="tradesBody"></tbody>
      </table>
    </div>
  </div>

  <div class="footer">
    <span id="footerInfo">Scans: 0 | Sources: 0 | Errors: 0</span>
  </div>
</div>

<script>
// ── Chart setup ──
const chartDefaults = { responsive: true, maintainAspectRatio: false, animation: { duration: 300 },
  plugins: { legend: { display: false } },
  scales: { x: { ticks: { color: '#8b949e', maxRotation: 45, font: { size: 10 } }, grid: { color: '#30363d33' } },
            y: { ticks: { color: '#8b949e', font: { size: 10 } }, grid: { color: '#30363d33' } } } };

const cumPnlChart = new Chart(document.getElementById('cumPnlChart'), {
  type: 'line',
  data: { labels: [], datasets: [{ data: [], borderColor: '#39d2c0', backgroundColor: '#39d2c022', fill: true, tension: 0.3, pointRadius: 2 }] },
  options: { ...chartDefaults }
});

const dailyPnlChart = new Chart(document.getElementById('dailyPnlChart'), {
  type: 'bar',
  data: { labels: [], datasets: [{ data: [], backgroundColor: [] }] },
  options: { ...chartDefaults }
});

const cityChart = new Chart(document.getElementById('cityChart'), {
  type: 'bar',
  data: { labels: [], datasets: [
    { label: 'P&L', data: [], backgroundColor: [] },
  ]},
  options: { ...chartDefaults, indexAxis: 'y' }
});

// ── Data fetching ──

function formatUptime(s) {
  if (s < 3600) return Math.floor(s/60) + 'm';
  const h = Math.floor(s/3600), m = Math.floor((s%3600)/60);
  return h + 'h ' + m + 'm';
}

function pnlClass(v) { return v >= 0 ? 'pnl-pos' : 'pnl-neg'; }
function pnlStr(v) { return (v >= 0 ? '+' : '') + '$' + v.toFixed(2); }

async function fetchStatus() {
  try {
    const r = await fetch('/api/status');
    const d = await r.json();

    // Header
    document.getElementById('modeBadge').textContent = d.paper_mode ? 'PAPER' : 'LIVE';
    document.getElementById('modeBadge').className = 'badge ' + (d.paper_mode ? 'paper' : 'live');
    const pnlEl = document.getElementById('headerPnl');
    pnlEl.textContent = pnlStr(d.daily_pnl);
    pnlEl.className = 'val ' + pnlClass(d.daily_pnl);
    document.getElementById('headerTrades').textContent = d.trades_placed;
    document.getElementById('headerWL').textContent = d.wins + '/' + d.losses;
    document.getElementById('headerUptime').textContent = formatUptime(d.uptime_s);

    // Drawdown
    const dd = document.getElementById('drawdownBanner');
    if (d.drawdown_level === 'PAUSED') {
      dd.style.display = 'block';
      dd.textContent = 'PAUSED — drawdown limit (' + d.drawdown_consecutive + ' consecutive losses)';
    } else if (d.drawdown_consecutive > 0 && d.drawdown_level !== 'NORMAL') {
      dd.style.display = 'block';
      dd.textContent = 'Drawdown ' + d.drawdown_level + ' (' + (d.drawdown_multiplier*100).toFixed(0) + '% size, ' + d.drawdown_consecutive + 'L streak)';
    } else {
      dd.style.display = 'none';
    }

    // Account
    document.getElementById('accCash').textContent = '$' + d.cash.toFixed(2);
    document.getElementById('accPortfolio').textContent = '$' + d.portfolio_value.toFixed(2);
    document.getElementById('accTotal').textContent = '$' + (d.cash + d.portfolio_value).toFixed(2);
    document.getElementById('accExposure').textContent = '$' + d.exposure.toFixed(2);
    document.getElementById('accPositions').textContent = d.positions + ' pos / ' + d.resting_orders + ' orders';
    document.getElementById('accLimit').textContent = '-$' + d.daily_loss_limit.toFixed(2);

    // Cities table
    const tbody = document.getElementById('cityTableBody');
    tbody.innerHTML = '';
    const cities = Object.entries(d.cities).sort((a,b) => a[0].localeCompare(b[0]));
    for (const [city, cs] of cities) {
      const tr = document.createElement('tr');
      const enabled = d.cities_enabled.includes(city);
      const wr = cs.win_rate || 0;
      tr.innerHTML = '<td style="font-weight:600">' + city + '</td>'
        + '<td class="' + (enabled ? 'city-on' : 'city-off') + '">' + (enabled ? 'ON' : 'OFF') + '</td>'
        + '<td>' + cs.wins + '/' + cs.losses + '</td>'
        + '<td style="color:' + (wr >= 50 ? 'var(--green)' : wr > 0 ? 'var(--red)' : 'var(--text-dim)') + '">' + (cs.wins+cs.losses > 0 ? wr.toFixed(0)+'%' : '--') + '</td>'
        + '<td class="' + pnlClass(cs.pnl) + '">' + pnlStr(cs.pnl) + '</td>';
      tbody.appendChild(tr);
    }

    // City chart
    const cityLabels = cities.map(c => c[0]);
    const cityPnl = cities.map(c => c[1].pnl);
    const cityColors = cityPnl.map(v => v >= 0 ? '#3fb950' : '#f85149');
    cityChart.data.labels = cityLabels;
    cityChart.data.datasets[0].data = cityPnl;
    cityChart.data.datasets[0].backgroundColor = cityColors;
    cityChart.update('none');

    // Events feed
    const feed = document.getElementById('eventFeed');
    feed.innerHTML = '';
    for (const ev of d.events) {
      const div = document.createElement('div');
      div.className = 'feed-item';
      div.innerHTML = '<span class="time">' + ev.time + '</span><span class="msg">' + ev.msg + '</span>';
      feed.appendChild(div);
    }

    // Footer
    document.getElementById('footerInfo').textContent =
      'Scans: ' + d.scans + ' | Sources: ' + d.forecast_sources + ' | Errors: ' + d.errors
      + ' | Last scan: ' + d.last_scan_duration + 's (' + d.last_scan_markets + ' markets)';
  } catch(e) { console.error('Status fetch error:', e); }
}

async function fetchPnl() {
  try {
    const r = await fetch('/api/pnl');
    const d = await r.json();
    if (!d.daily || d.daily.length === 0) return;

    const labels = d.daily.map(x => x.date.slice(5));
    const cum = d.daily.map(x => x.cumulative);
    const daily = d.daily.map(x => x.pnl);
    const colors = daily.map(v => v >= 0 ? '#3fb950' : '#f85149');

    cumPnlChart.data.labels = labels;
    cumPnlChart.data.datasets[0].data = cum;
    cumPnlChart.update('none');

    dailyPnlChart.data.labels = labels;
    dailyPnlChart.data.datasets[0].data = daily;
    dailyPnlChart.data.datasets[0].backgroundColor = colors;
    dailyPnlChart.update('none');
  } catch(e) { console.error('PnL fetch error:', e); }
}

async function fetchTrades() {
  try {
    const r = await fetch('/api/trades?limit=50');
    const d = await r.json();
    const tbody = document.getElementById('tradesBody');
    tbody.innerHTML = '';
    for (const t of d.trades.reverse()) {
      const tr = document.createElement('tr');
      const sideColor = t.side === 'yes' ? 'var(--green)' : 'var(--red)';
      const ts = t.timestamp ? t.timestamp.slice(11, 19) : '';
      const edge = t.edge ? parseFloat(t.edge).toFixed(1) + '%' : '';
      tr.innerHTML = '<td style="color:var(--text-dim)">' + ts + '</td>'
        + '<td>' + (t.ticker || '') + '</td>'
        + '<td style="color:' + sideColor + ';font-weight:600">' + (t.side||'').toUpperCase() + '</td>'
        + '<td>' + (t.count || '') + '</td>'
        + '<td>' + (t.price || '') + 'c</td>'
        + '<td>' + edge + '</td>'
        + '<td style="color:var(--text-dim)">' + (t.strategy || '') + '</td>';
      tbody.appendChild(tr);
    }
  } catch(e) { console.error('Trades fetch error:', e); }
}

async function fetchPositions() {
  try {
    const r = await fetch('/api/positions');
    const d = await r.json();
    const tbody = document.getElementById('posBody');
    const countEl = document.getElementById('posCount');
    tbody.innerHTML = '';
    if (!d.positions || d.positions.length === 0) {
      tbody.innerHTML = '<tr><td colspan="12" class="pos-empty">No active positions</td></tr>';
      countEl.textContent = '';
      return;
    }
    countEl.textContent = '(' + d.positions.length + ')';
    const KALSHI_SLUGS = {
      'KXHIGHNY':'highest-temperature-in-nyc','KXLOWNY':'lowest-temperature-in-nyc',
      'KXHIGHCHI':'highest-temperature-in-chicago','KXLOWCHI':'lowest-temperature-in-chicago',
      'KXHIGHMIA':'highest-temperature-in-miami','KXLOWMIA':'lowest-temperature-in-miami',
      'KXHIGHAUS':'highest-temperature-in-austin','KXLOWAUS':'lowest-temperature-in-austin',
      'KXHIGHLAX':'highest-temperature-in-los-angeles','KXLOWLAX':'lowest-temperature-in-los-angeles',
      'KXHIGHDEN':'highest-temperature-in-denver','KXLOWDEN':'lowest-temperature-in-denver',
      'KXHIGHTDAL':'dallas-maximum-temperature','KXHIGHTDC':'washington-dc-daily-max-temp',
      'KXHIGHTPHX':'phoenix-high-temperature-daily','KXLOWTPHIL':'lowest-temperature-in-philadelphia',
      'KXHIGHOU':'highest-temperature-in-houston',
    };
    function kalshiUrl(ticker) {
      const parts = ticker.split('-');
      const series = parts[0];
      const event = parts.slice(0,2).join('-').toLowerCase();
      const slug = KALSHI_SLUGS[series];
      if (slug) return 'https://kalshi.com/markets/' + series.toLowerCase() + '/' + slug + '/' + event;
      return 'https://kalshi.com/markets/' + series.toLowerCase();
    }
    for (const p of d.positions) {
      const tr = document.createElement('tr');
      const sideClass = p.side === 'yes' ? 'side-yes' : 'side-no';
      const edge = p.edge ? parseFloat(p.edge).toFixed(1) + '%' : '--';
      const prob = p.our_prob ? (parseFloat(p.our_prob) * 100).toFixed(0) + '%' : '--';
      const forecast = p.mean_forecast ? parseFloat(p.mean_forecast).toFixed(1) + '\u00b0' : '--';
      const threshold = p.threshold || '--';
      const date = p.target_date ? p.target_date.slice(5) : '--';
      tr.innerHTML = '<td style="color:var(--text-dim)">' + date + '</td>'
        + '<td style="font-weight:600">' + (p.city || '--') + '</td>'
        + '<td class="ticker"><a href="' + kalshiUrl(p.ticker) + '" target="_blank" rel="noopener">' + p.ticker + '</a></td>'
        + '<td class="' + sideClass + '">' + p.side.toUpperCase() + '</td>'
        + '<td>' + p.qty + '</td>'
        + '<td>' + p.avg_entry + 'c</td>'
        + '<td>' + edge + '</td>'
        + '<td>' + prob + '</td>'
        + '<td>' + forecast + '</td>'
        + '<td>' + threshold + '\u00b0</td>'
        + '<td class="pnl-pos">+$' + p.max_gain.toFixed(2) + '</td>'
        + '<td class="pnl-neg">-$' + p.max_loss.toFixed(2) + '</td>';
      tbody.appendChild(tr);
    }
  } catch(e) { console.error('Positions fetch error:', e); }
}

// ── SSE for live updates ──
function connectSSE() {
  const es = new EventSource('/api/events');
  es.onmessage = function(e) {
    try {
      const d = JSON.parse(e.data);
      // Update header P&L immediately
      if (d.daily_pnl !== undefined) {
        const el = document.getElementById('headerPnl');
        el.textContent = pnlStr(d.daily_pnl);
        el.className = 'val ' + pnlClass(d.daily_pnl);
      }
      if (d.wins !== undefined) {
        document.getElementById('headerWL').textContent = d.wins + '/' + d.losses;
      }
      // Refresh full status on event
      fetchStatus();
    } catch(err) {}
  };
  es.onerror = function() {
    es.close();
    setTimeout(connectSSE, 5000);
  };
}

// ── Initial load + polling ──
fetchStatus();
fetchPnl();
fetchTrades();
fetchPositions();
connectSSE();
setInterval(fetchStatus, 5000);
setInterval(fetchPnl, 60000);
setInterval(fetchTrades, 30000);
setInterval(fetchPositions, 30000);
</script>
</body>
</html>
"""
