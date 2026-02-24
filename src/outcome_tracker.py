"""
Outcome Tracker - Track bet outcomes and improve forecast accuracy over time

Writes only real Kalshi API data to data/outcomes.csv (results.csv): markets that have
officially settled (status closed/finalized/settled). No NWS-inferred outcomes are
written here; today's P&L may still use NWS inference for same-day reporting.

This module:
1. Checks for settled positions (markets that have resolved on API)
2. Extracts actual temperatures from market outcomes
3. Writes one row per market to outcomes.csv (real Kalshi results only)
4. Updates forecast model with historical accuracy data
"""

import json
import csv
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

from .config import Config, extract_city_code

logger = logging.getLogger(__name__)


class OutcomeTracker:
    """Track market outcomes and forecast accuracy"""

    def __init__(self, client, weather_aggregator, adaptive_manager=None, drawdown_protector=None, cooldown_timer=None):
        self.client = client
        self.weather_agg = weather_aggregator
        self.adaptive_manager = adaptive_manager
        self.drawdown_protector = drawdown_protector
        self.cooldown_timer = cooldown_timer

        # Settlement divergence tracker
        self.settlement_tracker = None
        try:
            from .settlement_tracker import SettlementTracker
            self.settlement_tracker = SettlementTracker()
        except ImportError:
            pass

        # File paths for persistent storage (paper mode uses separate file)
        self.outcomes_file = Path("data/paper_outcomes.csv") if Config.PAPER_TRADING else Path("data/outcomes.csv")
        self.performance_file = Path("data/performance.json")
        
        # Ensure data directory exists
        self.outcomes_file.parent.mkdir(exist_ok=True)
        
        # Initialize CSV if it doesn't exist
        if not self.outcomes_file.exists():
            with open(self.outcomes_file, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'timestamp', 'market_ticker', 'city', 'date', 'threshold', 'threshold_type',
                    'our_probability', 'market_price', 'edge', 'ev', 'strategy_mode',
                    'side', 'contracts', 'entry_price', 'outcome', 'actual_temp',
                    'predicted_temp', 'forecast_error', 'won', 'profit_loss'
                ])
        
        # Track positions we've already logged
        self.logged_positions: set = set()
        
        # Load logged positions from file
        self._load_logged_positions()
    
    def _load_logged_positions(self):
        """Load already-logged positions from outcomes file"""
        if self.outcomes_file.exists():
            try:
                with open(self.outcomes_file, 'r') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        self.logged_positions.add(row['market_ticker'])
            except Exception as e:
                logger.warning(f"Could not load logged positions: {e}")
    
    def _load_paper_trades(self) -> Dict[str, list]:
        """Load paper trades from data/trades.csv, grouped by market_ticker.

        Collects ALL trades per ticker so settlement aggregates the full
        position (multiple buys at different prices/times).
        """
        trades_file = Path("data/trades.csv")
        by_ticker: Dict[str, list] = defaultdict(list)
        if not trades_file.exists():
            return by_ticker
        try:
            with open(trades_file, 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    order_id = row.get('order_id', '')
                    if order_id.startswith('PAPER-'):
                        ticker = row.get('market_ticker', '')
                        if ticker:
                            by_ticker[ticker].append(row)
        except Exception as e:
            logger.warning(f"Could not load paper trades: {e}")
        return by_ticker

    def _lookup_trade_probability(self, market_ticker: str, side: str) -> float:
        """Look up our original probability for a trade from trades.csv."""
        details = self._lookup_trade_details(market_ticker, side)
        prob = details.get('our_probability')
        return float(prob) if prob else 0.5

    def _lookup_trade_details(self, market_ticker: str, side: str) -> dict:
        """Look up original trade decision data from trades.csv.

        Returns dict with keys: our_probability, market_price, edge, ev, strategy_mode.
        Values are strings (empty string if not found).
        """
        result = {'our_probability': '', 'market_price': '', 'edge': '', 'ev': '', 'strategy_mode': ''}
        trades_file = Path("data/trades.csv")
        if not trades_file.exists():
            return result
        try:
            with open(trades_file, 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get('market_ticker') == market_ticker and row.get('side', '').lower() == side:
                        result['our_probability'] = row.get('our_probability', '')
                        result['market_price'] = row.get('market_price', '')
                        result['edge'] = row.get('edge', '')
                        result['ev'] = row.get('ev', '')
                        result['strategy_mode'] = row.get('strategy_mode', '')
                        break
        except Exception as e:
            logger.debug(f"Could not look up trade details for {market_ticker}: {e}")
        return result

    @staticmethod
    def parse_target_date_from_ticker(market_ticker: str) -> Optional[datetime]:
        """Parse target date from market ticker.

        e.g., KXHIGHNY-26FEB07-T24 → Feb 7, 2026
        """
        if not market_ticker:
            return None
        parts = market_ticker.split('-')
        if len(parts) < 2:
            return None
        date_part = parts[1]  # e.g., '26FEB07'
        try:
            return datetime.strptime(date_part, '%y%b%d')
        except ValueError:
            return None

    def check_settled_positions(self) -> List[Dict]:
        """
        Check portfolio for settled positions (markets that have resolved).
        Groups fills by market_ticker so each market is logged once with aggregated P&L.
        Returns list of settled positions (each has 'fills' list and 'market').
        """
        try:
            if Config.PAPER_TRADING:
                # Paper mode: reconstruct fills from trades.csv, check real settlement on Kalshi
                paper_trades = self._load_paper_trades()
                settled_positions = []
                for ticker, trades in paper_trades.items():
                    if ticker in self.logged_positions:
                        continue
                    try:
                        market_response = self.client.get_market(ticker)
                        market = market_response.get('market', market_response)
                        status = market.get('status', '').lower()
                        result = market.get('result', '').lower()
                        if status in ['closed', 'finalized', 'settled'] and result in ['yes', 'no']:
                            # Synthesize fill records from paper trades
                            fills = []
                            for t in trades:
                                price = int(t.get('price', 0))
                                side = t.get('side', '')
                                fills.append({
                                    'ticker': ticker,
                                    'side': side,
                                    'count': int(t.get('count', 0)),
                                    'yes_price': price if side == 'yes' else 0,
                                    'no_price': price if side == 'no' else 0,
                                })
                            settled_positions.append({'fills': fills, 'market': market})
                            logger.info(f"Found settled paper position: {ticker} (status: {status}, {len(fills)} trade(s))")
                    except Exception as e:
                        logger.debug(f"Could not fetch market {ticker}: {e}")
                return settled_positions

            fills = self.client.get_fills()
            # Group fills by market_ticker (same market can have many fill records)
            by_ticker: Dict[str, list] = defaultdict(list)
            for fill in fills:
                ticker = fill.get('ticker')
                if ticker and ticker not in self.logged_positions:
                    by_ticker[ticker].append(fill)

            settled_positions = []
            for market_ticker, ticker_fills in by_ticker.items():
                if not ticker_fills:
                    continue
                try:
                    market_response = self.client.get_market(market_ticker)
                    market = market_response.get('market', market_response)  # Unwrap nested response
                    status = market.get('status', '').lower()
                    result = market.get('result', '').lower()
                    if status in ['closed', 'finalized', 'settled'] and result in ['yes', 'no']:
                        settled_positions.append({
                            'fills': ticker_fills,
                            'market': market
                        })
                        logger.info(f"Found settled position: {market_ticker} (status: {status}, {len(ticker_fills)} fill(s))")
                except Exception as e:
                    logger.debug(f"Could not fetch market {market_ticker}: {e}")
            return settled_positions
        except Exception as e:
            logger.error(f"Error checking settled positions: {e}", exc_info=True)
            return []
    
    def extract_actual_temperature(self, market: Dict, series_ticker: str = '', target_date: Optional[datetime] = None) -> Optional[float]:
        """
        Extract actual temperature from settled market.

        Strategy:
        1. Try NWS observed data (most accurate — same source Kalshi settles on)
        2. Fall back to range midpoint for range markets
        3. Return None if we can't determine the actual temp
        """
        try:
            result = market.get('result', '').lower()
            if result not in ['yes', 'no']:
                return None

            # Try NWS observed data first (closes feedback loop for all market types)
            if series_ticker and self.weather_agg:
                is_high = series_ticker.startswith('KXHIGH')
                try:
                    if target_date and target_date.date() != datetime.now().date():
                        # Historical date — use date-specific method
                        if is_high:
                            obs = self.weather_agg.get_observed_high_for_date(series_ticker, target_date)
                        else:
                            obs = self.weather_agg.get_observed_low_for_date(series_ticker, target_date)
                    else:
                        # Today — use cached today method
                        if is_high:
                            obs = self.weather_agg.get_todays_observed_high(series_ticker)
                        else:
                            obs = self.weather_agg.get_todays_observed_low(series_ticker)
                    if obs is not None:
                        actual_temp, _ = obs
                        logger.debug(f"NWS observed {'high' if is_high else 'low'} for {series_ticker}: {actual_temp:.1f}°F")
                        return actual_temp
                except Exception as e:
                    logger.debug(f"Could not get NWS observation for {series_ticker}: {e}")

            # Fall back to range market midpoint
            from src.weather_data import extract_threshold_from_market
            threshold = extract_threshold_from_market(market)
            if threshold is None:
                return None

            if isinstance(threshold, tuple):
                low, high = threshold
                if result == 'yes':
                    return (low + high) / 2.0
                return None

            return None

        except Exception as e:
            logger.warning(f"Error extracting actual temp: {e}")
            return None
    
    def get_predicted_temperature(self, market_ticker: str, target_date: datetime, series_ticker: str) -> Optional[float]:
        """
        Get what our forecast predicted for this market
        This should match what we used when placing the trade
        """
        try:
            # Get forecasts for that date
            forecasts = self.weather_agg.get_all_forecasts(series_ticker, target_date)
            
            if not forecasts:
                return None
            
            # Return mean forecast
            return sum(forecasts) / len(forecasts)
        
        except Exception as e:
            logger.warning(f"Error getting predicted temp for {market_ticker}: {e}")
            return None
    
    def log_outcome(self, settled_position: Dict):
        """
        Log outcome of a settled position to CSV (one row per market, aggregated over all fills).
        Update forecast model with actual accuracy data.
        """
        try:
            fills = settled_position.get('fills')
            if not fills:
                fill = settled_position.get('fill')
                fills = [fill] if fill else []
            if not fills:
                return
            market = settled_position['market']
            first_fill = fills[0]
            market_ticker = first_fill.get('ticker')

            from src.weather_data import extract_threshold_from_market
            threshold = extract_threshold_from_market(market)

            # Extract series_ticker from the market ticker (Kalshi market objects
            # don't include a series_ticker field).
            # e.g., KXHIGHNY-26FEB07-T24 → KXHIGHNY
            series_ticker = market.get('series_ticker', '')
            if not series_ticker and market_ticker:
                parts = market_ticker.split('-')
                series_ticker = parts[0] if parts else ''

            target_date = self.parse_target_date_from_ticker(market_ticker) or datetime.now()
            actual_temp = self.extract_actual_temperature(market, series_ticker, target_date)
            predicted_temp = None
            if actual_temp and series_ticker:
                predicted_temp = self.get_predicted_temperature(market_ticker, target_date, series_ticker)
            forecast_error = None
            if actual_temp and predicted_temp:
                forecast_error = abs(actual_temp - predicted_temp)
                # Update overall forecast error tracking
                self.weather_agg.update_forecast_error(
                    series_ticker, target_date, actual_temp, predicted_temp
                )
                # Update per-model bias tracking for all sources that contributed
                self.weather_agg.update_all_model_biases(
                    series_ticker, target_date, actual_temp
                )
                logger.info(f"📊 Updated forecast model biases for {series_ticker} (actual: {actual_temp:.1f}°F)")

                # Store actual in ForecastTracker to close the accuracy feedback loop
                try:
                    from .forecast_weighting import get_forecast_tracker
                    tracker = get_forecast_tracker()
                    city = extract_city_code(series_ticker)
                    is_high = series_ticker.startswith('KXHIGH')
                    tracker.store_actual(
                        city, target_date.strftime('%Y-%m-%d'),
                        actual_high=actual_temp if is_high else None,
                        actual_low=actual_temp if not is_high else None
                    )
                except Exception:
                    pass

            result = market.get('result', '').lower()
            total_count = 0
            total_profit_loss = 0.0
            side = first_fill.get('side', '').lower()
            for fill in fills:
                count = fill.get('count', 0)
                trade_price = fill.get('yes_price', 0) if side == 'yes' else fill.get('no_price', 0)
                won = (side == result)
                if won:
                    total_profit_loss += count * (100 - trade_price) / 100.0
                else:
                    total_profit_loss -= count * trade_price / 100.0
                total_count += count
            # Use avg entry price for display (first fill's price as proxy)
            trade_price = first_fill.get('yes_price', 0) if side == 'yes' else first_fill.get('no_price', 0)
            won = (side == result)

            # Look up original trade decision data
            trade_details = self._lookup_trade_details(market_ticker, side)

            with open(self.outcomes_file, 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    datetime.now().isoformat(),
                    market_ticker,
                    series_ticker,
                    target_date.date().isoformat() if target_date else '',
                    str(threshold),
                    'range' if isinstance(threshold, tuple) else 'threshold',
                    trade_details['our_probability'],
                    trade_details['market_price'],
                    trade_details['edge'],
                    trade_details['ev'],
                    trade_details['strategy_mode'],
                    side,
                    total_count,
                    trade_price,
                    result,
                    actual_temp if actual_temp else '',
                    predicted_temp if predicted_temp else '',
                    forecast_error if forecast_error else '',
                    'YES' if won else 'NO',
                    f"{total_profit_loss:.2f}"
                ])

            self.logged_positions.add(market_ticker)
            outcome_symbol = "✅" if won else "❌"
            logger.info(f"{outcome_symbol} Logged outcome: {market_ticker} | {side.upper()} | {'WON' if won else 'LOST'} | P&L: ${total_profit_loss:.2f} ({total_count} contract(s))")
            if forecast_error:
                logger.info(f"   Forecast accuracy: Predicted {predicted_temp:.1f}°, Actual {actual_temp:.1f}° (error: {forecast_error:.1f}°)")

            # Update adaptive city manager with outcome
            if self.adaptive_manager and series_ticker:
                city = extract_city_code(series_ticker)
                self.adaptive_manager.record_outcome(city, won, total_profit_loss)
                logger.debug(f"Updated adaptive manager for city {city}")

            # Update drawdown protector with outcome
            if self.drawdown_protector:
                self.drawdown_protector.record_outcome(won)

            # Update settlement divergence tracker
            if self.settlement_tracker and series_ticker:
                city = extract_city_code(series_ticker)
                # Look up our original probability from trades.csv
                our_prob = self._lookup_trade_probability(market_ticker, side)
                self.settlement_tracker.record_settlement(
                    city=city, our_probability=our_prob, won=won, ticker=market_ticker
                )

            # Update cooldown timer with outcome
            if self.cooldown_timer:
                self.cooldown_timer.record_outcome(won)

            # Feed forecast error to city/season error tracker
            if forecast_error is not None and series_ticker:
                try:
                    from .city_error_tracker import get_city_error_tracker
                    city = extract_city_code(series_ticker)
                    month = target_date.month if target_date else datetime.now().month
                    tracker = get_city_error_tracker()
                    tracker.record_error(city, month, forecast_error)
                except Exception:
                    pass

            # Generate post-mortem
            if Config.POSTMORTEM_ENABLED:
                try:
                    from .postmortem import PostMortemGenerator
                    pm_gen = PostMortemGenerator()
                    source_forecasts = pm_gen._lookup_source_forecasts(market_ticker)
                    pm = pm_gen.generate(
                        market_ticker=market_ticker,
                        trade_details=trade_details,
                        outcome_data={
                            'won': won,
                            'pnl': total_profit_loss,
                            'side': side,
                            'contracts': total_count,
                            'entry_price': trade_price,
                            'actual_temp': actual_temp,
                            'predicted_temp': predicted_temp,
                            'forecast_error': forecast_error,
                            'result': result,
                            'threshold': str(threshold),
                        },
                        source_forecasts=source_forecasts,
                    )
                    pm_gen.store(pm)
                except Exception as e:
                    logger.debug(f"Could not generate post-mortem: {e}")

            # Trigger ML retrain check
            if Config.ML_ENABLED:
                try:
                    from .ml_predictor import get_ml_predictor
                    ml = get_ml_predictor()
                    if ml.needs_retrain():
                        ml.train()
                except Exception:
                    pass

            return {'ticker': market_ticker, 'won': won, 'pnl': abs(total_profit_loss), 'signed_pnl': total_profit_loss}

        except Exception as e:
            logger.error(f"Error logging outcome: {e}", exc_info=True)
            return None
    
    def generate_performance_report(self) -> Dict:
        """
        Generate performance analytics from outcomes
        Returns dict with win rates, P&L, forecast accuracy by city/strategy
        """
        try:
            if not self.outcomes_file.exists():
                return {}
            
            # Read all outcomes
            outcomes = []
            with open(self.outcomes_file, 'r') as f:
                reader = csv.DictReader(f)
                outcomes = list(reader)
            
            if not outcomes:
                return {"message": "No settled positions yet"}
            
            # Calculate overall stats
            total_trades = len(outcomes)
            wins = sum(1 for o in outcomes if o['won'] == 'YES')
            losses = sum(1 for o in outcomes if o['won'] == 'NO')
            win_rate = wins / total_trades if total_trades > 0 else 0
            
            total_pnl = sum(float(o['profit_loss']) for o in outcomes if o['profit_loss'])
            
            # Stats by city
            by_city = defaultdict(lambda: {'wins': 0, 'losses': 0, 'pnl': 0.0, 'forecast_errors': []})
            
            for outcome in outcomes:
                city = outcome['city']
                if outcome['won'] == 'YES':
                    by_city[city]['wins'] += 1
                else:
                    by_city[city]['losses'] += 1
                
                if outcome['profit_loss']:
                    by_city[city]['pnl'] += float(outcome['profit_loss'])
                
                if outcome['forecast_error']:
                    by_city[city]['forecast_errors'].append(float(outcome['forecast_error']))
            
            # Calculate average forecast error per city
            city_stats = {}
            for city, stats in by_city.items():
                total = stats['wins'] + stats['losses']
                city_stats[city] = {
                    'trades': total,
                    'win_rate': stats['wins'] / total if total > 0 else 0,
                    'pnl': stats['pnl'],
                    'avg_forecast_error': sum(stats['forecast_errors']) / len(stats['forecast_errors']) if stats['forecast_errors'] else None
                }
            
            report = {
                'generated_at': datetime.now().isoformat(),
                'overall': {
                    'total_trades': total_trades,
                    'wins': wins,
                    'losses': losses,
                    'win_rate': win_rate,
                    'total_pnl': total_pnl
                },
                'by_city': city_stats
            }
            
            # Save to JSON
            with open(self.performance_file, 'w') as f:
                json.dump(report, f, indent=2)
            
            return report
        
        except Exception as e:
            logger.error(f"Error generating performance report: {e}", exc_info=True)
            return {}
    
    # Weather series prefixes (only reconcile these)
    WEATHER_PREFIXES = ('KXHIGH', 'KXLOW')

    def reconcile_with_kalshi(self):
        """
        Reconcile outcomes.csv against actual Kalshi weather settlements.

        Fetches settlements from Kalshi API and adds missing weather entries
        to outcomes.csv. Only processes weather markets (KXHIGH*, KXLOW*).

        Kalshi settlement format:
          yes_count, no_count: contracts held on each side
          yes_total_cost, no_total_cost: cost basis in cents
          revenue: total payout in cents
          market_result: 'yes' or 'no'
        """
        try:
            settlements = self.client.get_all_settlements()
            if not settlements:
                logger.info("No settlements found on Kalshi")
                return

            added = 0
            skipped_non_weather = 0
            for settlement in settlements:
                ticker = settlement.get('ticker', '')
                if not ticker or ticker in self.logged_positions:
                    continue

                # Only reconcile weather markets
                series_ticker = ticker.split('-')[0] if ticker else ''
                if not series_ticker.startswith(self.WEATHER_PREFIXES):
                    skipped_non_weather += 1
                    self.logged_positions.add(ticker)  # Mark as seen to avoid re-checking
                    continue

                # Determine side and count from settlement data
                yes_count = settlement.get('yes_count', 0)
                no_count = settlement.get('no_count', 0)
                yes_cost = settlement.get('yes_total_cost', 0)  # cents
                no_cost = settlement.get('no_total_cost', 0)    # cents
                revenue = settlement.get('revenue', 0)          # cents
                market_result = settlement.get('market_result', '').lower()
                total_cost = yes_cost + no_cost

                # Determine which side we held
                if yes_count > 0 and no_count > 0:
                    # Contradictory position — both sides held
                    side = 'yes'  # Primary side
                    count = yes_count + no_count
                    avg_price = total_cost // count if count > 0 else 0
                elif yes_count > 0:
                    side = 'yes'
                    count = yes_count
                    avg_price = yes_cost // yes_count if yes_count > 0 else 0
                elif no_count > 0:
                    side = 'no'
                    count = no_count
                    avg_price = no_cost // no_count if no_count > 0 else 0
                else:
                    self.logged_positions.add(ticker)
                    continue

                # Win = we held the side that won
                won = (side == market_result) if market_result in ('yes', 'no') else False
                # For contradictory positions, we can't simply say we "won"
                if yes_count > 0 and no_count > 0:
                    won = False  # Contradictory = guaranteed loss

                # P&L = revenue - total cost (in dollars)
                profit_loss = (revenue - total_cost) / 100.0

                # Extract city from series ticker
                city = extract_city_code(series_ticker)

                with open(self.outcomes_file, 'a', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow([
                        settlement.get('settled_time', datetime.now().isoformat()),
                        ticker,
                        city,
                        '',  # date
                        '',  # threshold
                        '',  # threshold_type
                        '', '', '', '', '',  # our_probability, market_price, edge, ev, strategy_mode
                        side,
                        count,
                        avg_price,
                        market_result,
                        '',  # actual_temp
                        '',  # predicted_temp
                        '',  # forecast_error
                        'YES' if won else 'NO',
                        f"{profit_loss:.2f}"
                    ])

                self.logged_positions.add(ticker)
                added += 1

            if added > 0:
                logger.info(f"📊 Reconciliation: added {added} weather settlement(s) to outcomes.csv (skipped {skipped_non_weather} non-weather)")
            else:
                logger.info(f"📊 Reconciliation: outcomes.csv is up to date (skipped {skipped_non_weather} non-weather)")

        except Exception as e:
            logger.error(f"Error reconciling with Kalshi: {e}", exc_info=True)

    def run_outcome_check(self):
        """
        Main method to check for settled positions and log outcomes.
        Should be called periodically (e.g., once per hour).
        Returns list of settlement result dicts (ticker, won, pnl, signed_pnl).
        """
        logger.info("🔍 Checking for settled positions...")

        settled = self.check_settled_positions()

        if not settled:
            logger.info("No new settled positions found")
            return []

        logger.info(f"Found {len(settled)} settled position(s) to process")

        results = []
        for position in settled:
            result = self.log_outcome(position)
            if result:
                results.append(result)

        # Generate updated performance report
        report = self.generate_performance_report()

        if report and 'overall' in report:
            overall = report['overall']
            logger.info(f"📊 Performance Update: {overall['wins']}W-{overall['losses']}L ({overall['win_rate']:.1%}) | P&L: ${overall['total_pnl']:.2f}")

        return results
