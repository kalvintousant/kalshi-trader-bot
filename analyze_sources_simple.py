"""
Simple Data Source Accuracy Analysis

Compare data source forecasts against NWS actual temperatures (which Kalshi uses to settle).
Only analyzes markets we actually traded.
"""

import csv
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
import numpy as np

from src.weather_data import WeatherDataAggregator

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s'
)
logger = logging.getLogger(__name__)


class SimpleSourceAnalyzer:
    """Compare data source accuracy for actual trades"""
    
    def __init__(self):
        self.weather_agg = WeatherDataAggregator()
        self.outcomes_file = Path("data/outcomes.csv")
    
    def analyze_sources(self):
        """
        For each outcome with actual temperature:
        - Get current forecast from each data source
        - Compare to NWS actual
        - Calculate errors
        """
        if not self.outcomes_file.exists():
            logger.error("No outcomes.csv file found")
            return
        
        # Read outcomes
        outcomes = []
        with open(self.outcomes_file, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get('actual_temp'):
                    try:
                        row['actual_temp'] = float(row['actual_temp'])
                        outcomes.append(row)
                    except ValueError:
                        continue
        
        if not outcomes:
            logger.error("No outcomes with actual temperatures found")
            return
        
        logger.info(f"Analyzing {len(outcomes)} outcomes...")
        
        # For each source, track errors
        source_errors = defaultdict(list)
        source_coverage = defaultdict(int)  # How many outcomes each source could forecast
        
        # Available sources to test
        sources_to_test = [
            ('nws', 'NWS'),
            ('nws_mos', 'NWS MOS'),
            ('tomorrowio', 'Tomorrow.io'),
            ('open_meteo_best', 'Open-Meteo Best'),
            ('open_meteo_gfs', 'Open-Meteo GFS'),
            ('open_meteo_ecmwf', 'Open-Meteo ECMWF'),
            ('open_meteo_icon', 'Open-Meteo ICON'),
            ('pirate_weather', 'Pirate Weather'),
            ('visual_crossing', 'Visual Crossing'),
            ('weatherbit', 'Weatherbit'),
        ]
        
        logger.info("\nFetching forecasts from each source...")
        
        for i, outcome in enumerate(outcomes, 1):
            if i % 10 == 0:
                logger.info(f"  Processing {i}/{len(outcomes)}...")
            
            series_ticker = outcome.get('city', '')
            actual_temp = outcome.get('actual_temp')
            date_str = outcome.get('date', '')
            
            if not series_ticker or not date_str:
                continue
            
            try:
                target_date = datetime.fromisoformat(date_str)
            except:
                continue
            
            # Get coords
            if series_ticker not in WeatherDataAggregator.CITY_COORDS:
                continue
            
            city = WeatherDataAggregator.CITY_COORDS[series_ticker]
            lat, lon = city['lat'], city['lon']
            
            # Test each source
            for source_key, source_name in sources_to_test:
                try:
                    # Get forecast from this source
                    if source_key == 'nws':
                        result = self.weather_agg.get_forecast_nws(lat, lon, target_date, series_ticker)
                    elif source_key == 'nws_mos':
                        result = self.weather_agg.get_forecast_nws_mos(lat, lon, target_date, series_ticker)
                    elif source_key == 'tomorrowio':
                        result = self.weather_agg.get_forecast_tomorrowio(lat, lon, target_date, series_ticker)
                    elif source_key == 'open_meteo_best':
                        result = self.weather_agg.get_forecast_open_meteo(lat, lon, target_date, series_ticker, 'best_match')
                    elif source_key == 'open_meteo_gfs':
                        result = self.weather_agg.get_forecast_open_meteo(lat, lon, target_date, series_ticker, 'gfs_seamless')
                    elif source_key == 'open_meteo_ecmwf':
                        result = self.weather_agg.get_forecast_open_meteo(lat, lon, target_date, series_ticker, 'ecmwf_ifs04')
                    elif source_key == 'open_meteo_icon':
                        result = self.weather_agg.get_forecast_open_meteo(lat, lon, target_date, series_ticker, 'icon_seamless')
                    elif source_key == 'pirate_weather':
                        result = self.weather_agg.get_forecast_pirate_weather(lat, lon, target_date, series_ticker)
                    elif source_key == 'visual_crossing':
                        result = self.weather_agg.get_forecast_visual_crossing(lat, lon, target_date, series_ticker)
                    elif source_key == 'weatherbit':
                        result = self.weather_agg.get_forecast_weatherbit(lat, lon, target_date, series_ticker)
                    else:
                        continue
                    
                    if result:
                        forecast_temp, _, _ = result
                        error = abs(forecast_temp - actual_temp)
                        source_errors[source_key].append(error)
                        source_coverage[source_key] += 1
                
                except Exception as e:
                    logger.debug(f"Error with {source_key}: {e}")
                    continue
        
        # Calculate statistics
        logger.info("\n" + "="*80)
        logger.info("DATA SOURCE ACCURACY ANALYSIS")
        logger.info("="*80)
        logger.info(f"Total outcomes analyzed: {len(outcomes)}")
        logger.info("")
        
        results = []
        for source_key, source_name in sources_to_test:
            errors = source_errors[source_key]
            coverage = source_coverage[source_key]
            
            if not errors:
                continue
            
            mae = np.mean(errors)
            rmse = np.sqrt(np.mean([e**2 for e in errors]))
            max_error = max(errors)
            min_error = min(errors)
            within_2deg = sum(1 for e in errors if e <= 2.0) / len(errors)
            
            results.append({
                'source': source_name,
                'key': source_key,
                'mae': mae,
                'rmse': rmse,
                'coverage': coverage / len(outcomes) * 100,
                'hit_rate': within_2deg,
                'max_error': max_error,
                'min_error': min_error,
                'n_samples': len(errors)
            })
        
        # Sort by MAE (lower is better)
        results.sort(key=lambda x: x['mae'])
        
        # Print results
        logger.info("\nINDIVIDUAL SOURCE PERFORMANCE (sorted by accuracy):")
        logger.info("-" * 80)
        
        for i, r in enumerate(results, 1):
            logger.info(f"\n#{i}: {r['source']}")
            logger.info(f"  Mean Absolute Error: {r['mae']:.2f}°F")
            logger.info(f"  RMSE: {r['rmse']:.2f}°F")
            logger.info(f"  Hit Rate (±2°F): {r['hit_rate']:.1%}")
            logger.info(f"  Coverage: {r['coverage']:.1f}% ({r['n_samples']} samples)")
            logger.info(f"  Error Range: {r['min_error']:.1f}°F - {r['max_error']:.1f}°F")
        
        # Test combinations of top sources
        logger.info("\n" + "="*80)
        logger.info("COMBINATION ANALYSIS")
        logger.info("="*80)
        
        # Get top 3 sources
        top_sources = [r['key'] for r in results[:3]]
        
        # Test combinations
        combos_to_test = []
        
        # All top 3 together
        combos_to_test.append(('All Top 3', top_sources))
        
        # Pairs
        if len(top_sources) >= 2:
            combos_to_test.append((f'{results[0]["source"]} + {results[1]["source"]}', top_sources[:2]))
        
        # Include current setup (all sources)
        all_sources = [r['key'] for r in results]
        combos_to_test.append(('All Sources (Current)', all_sources))
        
        logger.info("\nTesting combinations...")
        
        combo_results = []
        for combo_name, combo_sources in combos_to_test:
            combo_errors = []
            
            for outcome in outcomes:
                series_ticker = outcome.get('city', '')
                actual_temp = outcome.get('actual_temp')
                date_str = outcome.get('date', '')
                
                if not series_ticker or not date_str:
                    continue
                
                try:
                    target_date = datetime.fromisoformat(date_str)
                except:
                    continue
                
                if series_ticker not in WeatherDataAggregator.CITY_COORDS:
                    continue
                
                city = WeatherDataAggregator.CITY_COORDS[series_ticker]
                lat, lon = city['lat'], city['lon']
                
                # Get forecasts from sources in this combo
                forecasts = []
                for source_key in combo_sources:
                    # Re-use logic from above
                    try:
                        if source_key == 'nws':
                            result = self.weather_agg.get_forecast_nws(lat, lon, target_date, series_ticker)
                        elif source_key == 'nws_mos':
                            result = self.weather_agg.get_forecast_nws_mos(lat, lon, target_date, series_ticker)
                        elif source_key == 'tomorrowio':
                            result = self.weather_agg.get_forecast_tomorrowio(lat, lon, target_date, series_ticker)
                        elif source_key.startswith('open_meteo'):
                            model = source_key.replace('open_meteo_', '')
                            result = self.weather_agg.get_forecast_open_meteo(lat, lon, target_date, series_ticker, model)
                        elif source_key == 'pirate_weather':
                            result = self.weather_agg.get_forecast_pirate_weather(lat, lon, target_date, series_ticker)
                        elif source_key == 'visual_crossing':
                            result = self.weather_agg.get_forecast_visual_crossing(lat, lon, target_date, series_ticker)
                        elif source_key == 'weatherbit':
                            result = self.weather_agg.get_forecast_weatherbit(lat, lon, target_date, series_ticker)
                        else:
                            continue
                        
                        if result:
                            forecast_temp, _, _ = result
                            forecasts.append(forecast_temp)
                    except:
                        continue
                
                if forecasts:
                    combined_forecast = np.mean(forecasts)
                    error = abs(combined_forecast - actual_temp)
                    combo_errors.append(error)
            
            if combo_errors:
                mae = np.mean(combo_errors)
                hit_rate = sum(1 for e in combo_errors if e <= 2.0) / len(combo_errors)
                combo_results.append({
                    'name': combo_name,
                    'mae': mae,
                    'hit_rate': hit_rate,
                    'n_samples': len(combo_errors)
                })
        
        # Print combo results
        logger.info("")
        for combo in combo_results:
            logger.info(f"\n{combo['name']}:")
            logger.info(f"  MAE: {combo['mae']:.2f}°F")
            logger.info(f"  Hit Rate: {combo['hit_rate']:.1%}")
            logger.info(f"  Samples: {combo['n_samples']}")
        
        # Recommendation
        logger.info("\n" + "="*80)
        logger.info("RECOMMENDATION")
        logger.info("="*80)
        
        if results:
            best = results[0]
            logger.info(f"\nMost Accurate Single Source: {best['source']}")
            logger.info(f"  MAE: {best['mae']:.2f}°F")
            
            if combo_results:
                best_combo = min(combo_results, key=lambda x: x['mae'])
                logger.info(f"\nBest Combination: {best_combo['name']}")
                logger.info(f"  MAE: {best_combo['mae']:.2f}°F")
                
                # Compare
                current = next((c for c in combo_results if 'Current' in c['name']), None)
                if current and best_combo['name'] != current['name']:
                    improvement = (current['mae'] - best_combo['mae']) / current['mae'] * 100
                    logger.info(f"\n💡 Potential improvement: {improvement:.1f}% more accurate than current setup")
        
        logger.info("\n" + "="*80)


def main():
    logger.info("Starting simple data source analysis...\n")
    
    analyzer = SimpleSourceAnalyzer()
    analyzer.analyze_sources()
    
    logger.info("\n✅ Analysis complete!")


if __name__ == "__main__":
    main()
