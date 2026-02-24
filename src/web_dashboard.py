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
        app.router.add_get('/api/calibration', self.handle_calibration)
        app.router.add_get('/api/postmortems', self.handle_postmortems)
        app.router.add_get('/api/forecasts', self.handle_forecasts)
        app.router.add_get('/api/analytics', self.handle_analytics)
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

    async def handle_calibration(self, request):
        """Brier score and calibration curve data."""
        try:
            from .calibration import CalibrationTracker
            tracker = CalibrationTracker()
            data = tracker.compute()
            return web.json_response(data)
        except Exception as e:
            logger.debug(f"Calibration error: {e}")
            return web.json_response({'brier_score': None, 'n_trades': 0, 'buckets': [], 'by_city': {}, 'by_strategy': {}})

    async def handle_postmortems(self, request):
        """Return post-mortem cards."""
        try:
            from .postmortem import PostMortemGenerator
            limit = int(request.query.get('limit', '50'))
            city = request.query.get('city')
            gen = PostMortemGenerator()
            postmortems = gen.load(limit=limit, city=city)
            return web.json_response({'postmortems': postmortems})
        except Exception as e:
            logger.debug(f"Postmortems error: {e}")
            return web.json_response({'postmortems': []})

    async def handle_forecasts(self, request):
        """Per-source forecast accuracy from ForecastTracker."""
        try:
            from .forecast_weighting import get_forecast_tracker
            tracker = get_forecast_tracker()
            data = tracker.get_all_stats() if hasattr(tracker, 'get_all_stats') else {}
            return web.json_response(data)
        except Exception as e:
            logger.debug(f"Forecasts error: {e}")
            return web.json_response({})

    async def handle_analytics(self, request):
        """Compute Sharpe ratio, max drawdown, avg edge/EV, ML/cooldown/WS status."""
        result = {}

        # Sharpe ratio and max drawdown from daily P&L
        outcomes_file = Path('data/paper_outcomes.csv') if Config.PAPER_TRADING else Path('data/outcomes.csv')
        daily_pnls = {}
        if outcomes_file.exists():
            try:
                with open(outcomes_file, 'r') as f:
                    for row in csv.DictReader(f):
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
                        daily_pnls[date] = daily_pnls.get(date, 0.0) + pnl
            except Exception:
                pass

        if daily_pnls:
            import numpy as np
            daily_vals = [daily_pnls[d] for d in sorted(daily_pnls)]
            mean_daily = np.mean(daily_vals)
            std_daily = np.std(daily_vals) if len(daily_vals) > 1 else 0.0
            result['sharpe_ratio'] = round(float(mean_daily / std_daily * np.sqrt(252)), 2) if std_daily > 0 else None
            # Max drawdown
            cum = np.cumsum(daily_vals)
            peak = np.maximum.accumulate(cum)
            dd = cum - peak
            result['max_drawdown'] = round(float(np.min(dd)), 2) if len(dd) > 0 else 0.0
            result['total_pnl'] = round(float(cum[-1]), 2) if len(cum) > 0 else 0.0
            result['trading_days'] = len(daily_vals)
        else:
            result['sharpe_ratio'] = None
            result['max_drawdown'] = 0.0
            result['total_pnl'] = 0.0
            result['trading_days'] = 0

        # Avg edge/EV from trades.csv
        trades_file = Path('data/trades.csv')
        edges, evs = [], []
        if trades_file.exists():
            try:
                with open(trades_file, 'r') as f:
                    for row in csv.DictReader(f):
                        try:
                            e = float(row.get('edge', 0))
                            if e > 0:
                                edges.append(e)
                        except (ValueError, TypeError):
                            pass
                        try:
                            v = float(row.get('ev', 0))
                            if v > 0:
                                evs.append(v)
                        except (ValueError, TypeError):
                            pass
            except Exception:
                pass
        result['avg_edge'] = round(sum(edges) / len(edges), 2) if edges else None
        result['avg_ev'] = round(sum(evs) / len(evs), 4) if evs else None

        # ML status
        try:
            from .ml_predictor import get_ml_predictor
            result['ml'] = get_ml_predictor().get_status()
        except Exception:
            result['ml'] = {'enabled': False}

        # Cooldown status
        try:
            if hasattr(self.bot, 'cooldown_timer') and self.bot.cooldown_timer:
                result['cooldown'] = self.bot.cooldown_timer.get_status()
            else:
                result['cooldown'] = {'enabled': False}
        except Exception:
            result['cooldown'] = {'enabled': False}

        # WebSocket status
        try:
            if hasattr(self.bot, 'ws_price_cache') and self.bot.ws_price_cache:
                result['websocket'] = self.bot.ws_price_cache.get_status()
            else:
                result['websocket'] = {'enabled': False}
        except Exception:
            result['websocket'] = {'enabled': False}

        return web.json_response(result)


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
  .full-width { margin-bottom: 12px; }

  /* Account card */
  .account-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
  .account-item { }
  .account-item .label { font-size: 11px; color: var(--text-dim); }
  .account-item .value { font-size: 16px; font-weight: 600; color: var(--text-bright); }
  .account-item .value.small { font-size: 13px; }

  /* Analytics card */
  .analytics-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
  .analytics-item .label { font-size: 10px; color: var(--text-dim); text-transform: uppercase; }
  .analytics-item .value { font-size: 14px; font-weight: 600; color: var(--text-bright); }
  .analytics-item .value.good { color: var(--green); }
  .analytics-item .value.bad { color: var(--red); }
  .analytics-item .value.neutral { color: var(--yellow); }
  .status-dot { display: inline-block; width: 6px; height: 6px; border-radius: 50%; margin-right: 4px; }
  .status-dot.on { background: var(--green); }
  .status-dot.off { background: var(--text-dim); }

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

  /* Banners */
  .drawdown-banner { background: #f8514922; border: 1px solid var(--red); border-radius: 6px; padding: 8px 12px; margin-bottom: 12px; color: var(--red); font-weight: 600; text-align: center; display: none; }
  .cooldown-banner { background: #d2992222; border: 1px solid var(--yellow); border-radius: 6px; padding: 8px 12px; margin-bottom: 12px; color: var(--yellow); font-weight: 600; text-align: center; display: none; }

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

  /* Post-mortem cards */
  .pm-card { background: var(--surface); border: 1px solid var(--border); border-radius: 6px; margin-bottom: 8px; overflow: hidden; }
  .pm-header { display: flex; align-items: center; gap: 10px; padding: 8px 12px; cursor: pointer; }
  .pm-header:hover { background: #ffffff06; }
  .pm-badge { padding: 2px 6px; border-radius: 3px; font-size: 10px; font-weight: 700; }
  .pm-badge.win { background: #3fb95022; color: var(--green); }
  .pm-badge.loss { background: #f8514922; color: var(--red); }
  .pm-ticker { font-weight: 600; font-size: 12px; }
  .pm-meta { color: var(--text-dim); font-size: 11px; }
  .pm-arrow { margin-left: auto; color: var(--text-dim); transition: transform 0.2s; }
  .pm-arrow.open { transform: rotate(90deg); }
  .pm-body { display: none; padding: 8px 12px; border-top: 1px solid var(--border); font-size: 11px; }
  .pm-body.open { display: block; }
  .pm-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; margin-bottom: 8px; }
  .pm-item .label { color: var(--text-dim); font-size: 10px; }
  .pm-item .value { font-weight: 600; }
  .pm-sources { margin-top: 6px; }
  .pm-sources table { width: 100%; border-collapse: collapse; }
  .pm-sources th { text-align: left; font-size: 10px; color: var(--text-dim); padding: 2px 6px; }
  .pm-sources td { padding: 2px 6px; font-size: 11px; }
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

  <!-- Banners -->
  <div id="drawdownBanner" class="drawdown-banner"></div>
  <div id="cooldownBanner" class="cooldown-banner"></div>

  <!-- Row 1: P&L Charts -->
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

  <!-- Row 2: Calibration + Analytics -->
  <div class="grid">
    <div class="card">
      <h3>Calibration Curve <span id="brierScore" style="color:var(--cyan);float:right;font-size:11px"></span></h3>
      <div class="chart-container"><canvas id="calibrationChart"></canvas></div>
    </div>
    <div class="card">
      <h3>Analytics</h3>
      <div class="analytics-grid">
        <div class="analytics-item"><div class="label">Sharpe Ratio</div><div id="anSharpe" class="value">--</div></div>
        <div class="analytics-item"><div class="label">Max Drawdown</div><div id="anMaxDD" class="value">--</div></div>
        <div class="analytics-item"><div class="label">Avg Edge</div><div id="anAvgEdge" class="value">--</div></div>
        <div class="analytics-item"><div class="label">Avg EV</div><div id="anAvgEV" class="value">--</div></div>
        <div class="analytics-item"><div class="label">Trading Days</div><div id="anDays" class="value">--</div></div>
        <div class="analytics-item"><div class="label">Total P&L</div><div id="anTotalPnl" class="value">--</div></div>
        <div class="analytics-item"><div class="label">ML Model</div><div id="anML" class="value">--</div></div>
        <div class="analytics-item"><div class="label">WebSocket</div><div id="anWS" class="value">--</div></div>
      </div>
    </div>
  </div>

  <!-- Row 3: Account + Cities -->
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

  <!-- Row 4: Active Positions -->
  <div class="card full-width">
    <h3>Active Positions <span id="posCount" style="color:var(--cyan)"></span></h3>
    <div style="max-height:260px;overflow-y:auto">
      <table class="pos-table">
        <thead><tr><th>Date</th><th>City</th><th>Ticker</th><th>Side</th><th>Qty</th><th>Entry</th><th>Edge</th><th>Prob</th><th>Forecast</th><th>Threshold</th><th>Max Gain</th><th>Max Loss</th></tr></thead>
        <tbody id="posBody"><tr><td colspan="12" class="pos-empty">Loading...</td></tr></tbody>
      </table>
    </div>
  </div>

  <!-- Row 5: City chart + Live feed -->
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

  <!-- Row 6: Post-Mortem Cards -->
  <div class="card full-width">
    <h3>Trade Post-Mortems <span id="pmCount" style="color:var(--text-dim);font-size:11px"></span></h3>
    <div id="pmContainer" style="max-height:400px;overflow-y:auto">
      <div style="color:var(--text-dim);text-align:center;padding:16px;font-style:italic">Loading...</div>
    </div>
  </div>

  <!-- Row 7: Forecast Source Accuracy -->
  <div class="card full-width">
    <h3>Forecast Source Accuracy</h3>
    <div class="chart-container" style="height:250px"><canvas id="forecastChart"></canvas></div>
  </div>

  <!-- Row 8: Recent trades -->
  <div class="card full-width">
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
  data: { labels: [], datasets: [{ label: 'P&L', data: [], backgroundColor: [] }] },
  options: { ...chartDefaults, indexAxis: 'y' }
});

// Calibration chart (predicted vs actual with perfect diagonal)
const calibrationChart = new Chart(document.getElementById('calibrationChart'), {
  type: 'scatter',
  data: {
    datasets: [
      { label: 'Perfect', data: [{x:0,y:0},{x:100,y:100}], type: 'line', borderColor: '#30363d', borderDash: [5,5], pointRadius: 0, borderWidth: 1 },
      { label: 'Actual', data: [], borderColor: '#58a6ff', backgroundColor: '#58a6ff44', pointRadius: 5, pointHoverRadius: 7, showLine: true, tension: 0.3 },
    ]
  },
  options: { ...chartDefaults,
    plugins: { legend: { display: false } },
    scales: {
      x: { min: 0, max: 100, title: { display: true, text: 'Predicted %', color: '#8b949e', font: { size: 10 } }, ticks: { color: '#8b949e', font: { size: 10 } }, grid: { color: '#30363d33' } },
      y: { min: 0, max: 100, title: { display: true, text: 'Actual Win %', color: '#8b949e', font: { size: 10 } }, ticks: { color: '#8b949e', font: { size: 10 } }, grid: { color: '#30363d33' } },
    }
  }
});

// Forecast accuracy chart (horizontal bars)
const forecastChart = new Chart(document.getElementById('forecastChart'), {
  type: 'bar',
  data: { labels: [], datasets: [{ label: 'RMSE', data: [], backgroundColor: [] }] },
  options: { ...chartDefaults, indexAxis: 'y',
    scales: {
      x: { title: { display: true, text: 'RMSE (lower = better)', color: '#8b949e', font: { size: 10 } }, ticks: { color: '#8b949e', font: { size: 10 } }, grid: { color: '#30363d33' } },
      y: { ticks: { color: '#8b949e', font: { size: 10 } }, grid: { color: '#30363d33' } },
    }
  }
});

// ── Helpers ──
function formatUptime(s) {
  if (s < 3600) return Math.floor(s/60) + 'm';
  const h = Math.floor(s/3600), m = Math.floor((s%3600)/60);
  return h + 'h ' + m + 'm';
}
function pnlClass(v) { return v >= 0 ? 'pnl-pos' : 'pnl-neg'; }
function pnlStr(v) { return (v >= 0 ? '+' : '') + '$' + v.toFixed(2); }

// ── Data fetching ──

async function fetchStatus() {
  try {
    const r = await fetch('/api/status');
    const d = await r.json();

    document.getElementById('modeBadge').textContent = d.paper_mode ? 'PAPER' : 'LIVE';
    document.getElementById('modeBadge').className = 'badge ' + (d.paper_mode ? 'paper' : 'live');
    const pnlEl = document.getElementById('headerPnl');
    pnlEl.textContent = pnlStr(d.daily_pnl);
    pnlEl.className = 'val ' + pnlClass(d.daily_pnl);
    document.getElementById('headerTrades').textContent = d.trades_placed;
    document.getElementById('headerWL').textContent = d.wins + '/' + d.losses;
    document.getElementById('headerUptime').textContent = formatUptime(d.uptime_s);

    // Drawdown banner
    const dd = document.getElementById('drawdownBanner');
    if (d.drawdown_level === 'PAUSED') {
      dd.style.display = 'block';
      dd.textContent = 'PAUSED -- drawdown limit (' + d.drawdown_consecutive + ' consecutive losses)';
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
      const forecast = p.mean_forecast ? parseFloat(p.mean_forecast).toFixed(1) + '\\u00b0' : '--';
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
        + '<td>' + threshold + '\\u00b0</td>'
        + '<td class="pnl-pos">+$' + p.max_gain.toFixed(2) + '</td>'
        + '<td class="pnl-neg">-$' + p.max_loss.toFixed(2) + '</td>';
      tbody.appendChild(tr);
    }
  } catch(e) { console.error('Positions fetch error:', e); }
}

async function fetchCalibration() {
  try {
    const r = await fetch('/api/calibration');
    const d = await r.json();
    if (d.brier_score !== null) {
      document.getElementById('brierScore').textContent = 'Brier: ' + d.brier_score.toFixed(4) + ' (' + d.n_trades + ' trades)';
    }
    const points = [];
    for (const b of d.buckets || []) {
      if (b.actual_rate !== null && b.count > 0) {
        points.push({ x: b.predicted_avg * 100, y: b.actual_rate * 100 });
      }
    }
    calibrationChart.data.datasets[1].data = points;
    calibrationChart.update('none');
  } catch(e) { console.error('Calibration fetch error:', e); }
}

async function fetchAnalytics() {
  try {
    const r = await fetch('/api/analytics');
    const d = await r.json();

    const sharpeEl = document.getElementById('anSharpe');
    if (d.sharpe_ratio !== null) {
      sharpeEl.textContent = d.sharpe_ratio.toFixed(2);
      sharpeEl.className = 'value ' + (d.sharpe_ratio > 1 ? 'good' : d.sharpe_ratio > 0 ? 'neutral' : 'bad');
    } else { sharpeEl.textContent = '--'; }

    const ddEl = document.getElementById('anMaxDD');
    ddEl.textContent = '$' + (d.max_drawdown || 0).toFixed(2);
    ddEl.className = 'value bad';

    const edgeEl = document.getElementById('anAvgEdge');
    edgeEl.textContent = d.avg_edge !== null ? d.avg_edge.toFixed(1) + '%' : '--';

    const evEl = document.getElementById('anAvgEV');
    evEl.textContent = d.avg_ev !== null ? '$' + d.avg_ev.toFixed(4) : '--';

    document.getElementById('anDays').textContent = d.trading_days || 0;

    const pnlEl = document.getElementById('anTotalPnl');
    pnlEl.textContent = pnlStr(d.total_pnl || 0);
    pnlEl.className = 'value ' + ((d.total_pnl || 0) >= 0 ? 'good' : 'bad');

    // ML status
    const mlEl = document.getElementById('anML');
    if (d.ml && d.ml.enabled) {
      if (d.ml.trained) {
        mlEl.innerHTML = '<span class="status-dot on"></span>Trained (' + d.ml.training_samples + ' samples)';
      } else {
        mlEl.innerHTML = '<span class="status-dot off"></span>Untrained';
      }
    } else {
      mlEl.innerHTML = '<span class="status-dot off"></span>Disabled';
    }

    // WS status
    const wsEl = document.getElementById('anWS');
    if (d.websocket && d.websocket.enabled) {
      if (d.websocket.connected) {
        wsEl.innerHTML = '<span class="status-dot on"></span>Connected (' + d.websocket.cached_tickers + ' tickers)';
      } else {
        wsEl.innerHTML = '<span class="status-dot off"></span>Disconnected';
      }
    } else {
      wsEl.innerHTML = '<span class="status-dot off"></span>Disabled';
    }

    // Cooldown banner
    const cb = document.getElementById('cooldownBanner');
    if (d.cooldown && d.cooldown.enabled && d.cooldown.on_cooldown) {
      cb.style.display = 'block';
      if (d.cooldown.session_paused) {
        cb.textContent = 'COOLDOWN -- Session paused (' + d.cooldown.consecutive_losses + ' consecutive losses)';
      } else {
        cb.textContent = 'COOLDOWN -- ' + d.cooldown.remaining_minutes + 'm remaining after loss';
      }
    } else {
      cb.style.display = 'none';
    }
  } catch(e) { console.error('Analytics fetch error:', e); }
}

async function fetchPostmortems() {
  try {
    const r = await fetch('/api/postmortems?limit=20');
    const d = await r.json();
    const container = document.getElementById('pmContainer');
    const countEl = document.getElementById('pmCount');
    container.innerHTML = '';

    if (!d.postmortems || d.postmortems.length === 0) {
      container.innerHTML = '<div style="color:var(--text-dim);text-align:center;padding:16px;font-style:italic">No post-mortems yet</div>';
      countEl.textContent = '';
      return;
    }
    countEl.textContent = '(showing ' + d.postmortems.length + ')';

    for (let i = 0; i < d.postmortems.length; i++) {
      const pm = d.postmortems[i];
      const won = pm.outcome && pm.outcome.won;
      const pnl = pm.outcome ? pm.outcome.pnl : 0;
      const edge = pm.reasoning ? pm.reasoning.edge : null;
      const ticker = pm.market_ticker || '';

      const card = document.createElement('div');
      card.className = 'pm-card';

      // Header
      const header = document.createElement('div');
      header.className = 'pm-header';
      header.innerHTML = '<span class="pm-badge ' + (won ? 'win' : 'loss') + '">' + (won ? 'WIN' : 'LOSS') + '</span>'
        + '<span class="pm-ticker">' + ticker + '</span>'
        + '<span class="pm-meta">' + (edge !== null ? 'Edge: ' + edge.toFixed(1) + '%' : '') + '</span>'
        + '<span class="pm-meta ' + pnlClass(pnl) + '">' + pnlStr(pnl) + '</span>'
        + '<span class="pm-arrow" id="pmArrow' + i + '">&#9654;</span>';

      // Body (expandable)
      const body = document.createElement('div');
      body.className = 'pm-body';
      body.id = 'pmBody' + i;

      let bodyHtml = '<div class="pm-grid">';
      if (pm.reasoning) {
        bodyHtml += '<div class="pm-item"><div class="label">Our Prob</div><div class="value">' + (pm.reasoning.our_probability !== null ? (pm.reasoning.our_probability * 100).toFixed(0) + '%' : '--') + '</div></div>';
        bodyHtml += '<div class="pm-item"><div class="label">Market Price</div><div class="value">' + (pm.reasoning.market_price !== null ? pm.reasoning.market_price + 'c' : '--') + '</div></div>';
        bodyHtml += '<div class="pm-item"><div class="label">EV</div><div class="value">' + (pm.reasoning.ev !== null ? '$' + pm.reasoning.ev.toFixed(4) : '--') + '</div></div>';
      }
      if (pm.outcome) {
        bodyHtml += '<div class="pm-item"><div class="label">Actual Temp</div><div class="value">' + (pm.outcome.actual_temp !== null ? pm.outcome.actual_temp.toFixed(1) + '\\u00b0F' : '--') + '</div></div>';
        bodyHtml += '<div class="pm-item"><div class="label">Forecast Mean</div><div class="value">' + (pm.reasoning && pm.reasoning.mean_forecast !== null ? pm.reasoning.mean_forecast.toFixed(1) + '\\u00b0F' : '--') + '</div></div>';
        bodyHtml += '<div class="pm-item"><div class="label">Forecast Error</div><div class="value">' + (pm.outcome.forecast_error !== null ? pm.outcome.forecast_error.toFixed(1) + '\\u00b0F' : '--') + '</div></div>';
      }
      if (pm.trade) {
        bodyHtml += '<div class="pm-item"><div class="label">Side</div><div class="value">' + (pm.trade.side || '').toUpperCase() + '</div></div>';
        bodyHtml += '<div class="pm-item"><div class="label">Entry</div><div class="value">' + (pm.trade.entry_price || '--') + 'c</div></div>';
        bodyHtml += '<div class="pm-item"><div class="label">Strategy</div><div class="value">' + (pm.trade.strategy_mode || '--') + '</div></div>';
      }
      bodyHtml += '</div>';

      // Source accuracy table
      if (pm.source_accuracy && pm.source_accuracy.length > 0) {
        bodyHtml += '<div class="pm-sources"><table><thead><tr><th>Source</th><th>Forecast</th><th>Error</th></tr></thead><tbody>';
        for (const sa of pm.source_accuracy) {
          const errColor = Math.abs(sa.error) < 2 ? 'var(--green)' : Math.abs(sa.error) < 4 ? 'var(--yellow)' : 'var(--red)';
          bodyHtml += '<tr><td>' + sa.source + '</td><td>' + sa.forecast.toFixed(1) + '\\u00b0</td><td style="color:' + errColor + '">' + (sa.error > 0 ? '+' : '') + sa.error.toFixed(1) + '\\u00b0</td></tr>';
        }
        bodyHtml += '</tbody></table></div>';
      }

      body.innerHTML = bodyHtml;

      header.addEventListener('click', function() {
        const b = document.getElementById('pmBody' + i);
        const a = document.getElementById('pmArrow' + i);
        b.classList.toggle('open');
        a.classList.toggle('open');
      });

      card.appendChild(header);
      card.appendChild(body);
      container.appendChild(card);
    }
  } catch(e) { console.error('Postmortems fetch error:', e); }
}

async function fetchForecasts() {
  try {
    const r = await fetch('/api/forecasts');
    const d = await r.json();
    if (!d || typeof d !== 'object') return;

    // Extract source RMSE data
    const sources = [];
    for (const [source, stats] of Object.entries(d)) {
      if (stats && typeof stats.rmse === 'number') {
        sources.push({ source, rmse: stats.rmse });
      }
    }
    sources.sort((a, b) => a.rmse - b.rmse);

    forecastChart.data.labels = sources.map(s => s.source);
    forecastChart.data.datasets[0].data = sources.map(s => s.rmse);
    forecastChart.data.datasets[0].backgroundColor = sources.map(s =>
      s.rmse < 2 ? '#3fb950' : s.rmse < 4 ? '#d29922' : '#f85149'
    );
    forecastChart.update('none');
  } catch(e) { console.error('Forecasts fetch error:', e); }
}

// ── SSE for live updates ──
function connectSSE() {
  const es = new EventSource('/api/events');
  es.onmessage = function(e) {
    try {
      const d = JSON.parse(e.data);
      if (d.daily_pnl !== undefined) {
        const el = document.getElementById('headerPnl');
        el.textContent = pnlStr(d.daily_pnl);
        el.className = 'val ' + pnlClass(d.daily_pnl);
      }
      if (d.wins !== undefined) {
        document.getElementById('headerWL').textContent = d.wins + '/' + d.losses;
      }
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
fetchCalibration();
fetchAnalytics();
fetchPostmortems();
fetchForecasts();
connectSSE();

setInterval(fetchStatus, 5000);
setInterval(fetchPnl, 60000);
setInterval(fetchTrades, 30000);
setInterval(fetchPositions, 30000);
setInterval(fetchCalibration, 300000);   // 5 minutes
setInterval(fetchAnalytics, 60000);      // 1 minute
setInterval(fetchPostmortems, 60000);    // 1 minute
setInterval(fetchForecasts, 300000);     // 5 minutes
</script>
</body>
</html>
"""
