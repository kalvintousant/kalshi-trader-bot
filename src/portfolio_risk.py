"""
Correlation-Aware Portfolio Risk Management

Manages portfolio-level risk by:
- Calculating position correlations (same city, same date, same direction)
- Computing portfolio Value at Risk (VaR)
- Reducing position sizes for correlated exposures
- Suggesting hedges when appropriate

Key concepts:
- HIGH temp markets in hot cities (MIA, AUS, LAX) are correlated
- LOW temp markets in cold cities (CHI, NY, DEN) are correlated
- Same-day positions in a city are highly correlated
- Opposite positions can hedge each other
"""

import math
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
import logging
import re

logger = logging.getLogger(__name__)


# City climate clusters - cities with correlated weather patterns
CLIMATE_CLUSTERS = {
    'hot': ['MIA', 'AUS', 'LAX'],  # Warm climate cities
    'cold': ['CHI', 'NY', 'DEN'],  # Cold climate cities
    'coastal': ['NY', 'MIA', 'LAX'],  # Coastal cities
    'inland': ['CHI', 'AUS', 'DEN'],  # Inland cities
}

# Base correlation estimates between cities (for same day, same market type)
CITY_CORRELATIONS = {
    ('MIA', 'AUS'): 0.3,  # Both hot but different regions
    ('MIA', 'LAX'): 0.4,  # Both warm coastal
    ('AUS', 'LAX'): 0.3,  # Both warm
    ('CHI', 'NY'): 0.5,   # Both cold northeast/midwest
    ('CHI', 'DEN'): 0.4,  # Both cold interior
    ('NY', 'DEN'): 0.3,   # Both cold but different regions
}


class PositionCorrelation:
    """
    Calculates correlation between positions based on:
    - City similarity
    - Date similarity
    - Market type (HIGH vs LOW)
    - Direction (YES vs NO)
    """

    def __init__(self):
        self.city_correlations = CITY_CORRELATIONS
        self.climate_clusters = CLIMATE_CLUSTERS

    def parse_ticker(self, ticker: str) -> Dict:
        """Parse ticker into components"""
        result = {
            'city': None,
            'market_type': None,  # HIGH or LOW
            'date': None,
            'threshold_type': None,  # B or T
            'threshold': None
        }

        match = re.match(r'KX(HIGH|LOW)(\w+)-(\w+)-([BT])(\d+\.?\d*)', ticker)
        if match:
            result['market_type'] = match.group(1)
            result['city'] = match.group(2)
            result['date'] = match.group(3)
            result['threshold_type'] = match.group(4)
            result['threshold'] = float(match.group(5))

        return result

    def calculate_correlation(self, pos1: Dict, pos2: Dict) -> float:
        """
        Calculate correlation between two positions

        Args:
            pos1: {'ticker': str, 'side': str, 'count': int, ...}
            pos2: {'ticker': str, 'side': str, 'count': int, ...}

        Returns:
            Correlation coefficient (-1 to 1)
        """
        parsed1 = self.parse_ticker(pos1.get('ticker', ''))
        parsed2 = self.parse_ticker(pos2.get('ticker', ''))

        if not parsed1['city'] or not parsed2['city']:
            return 0.0

        correlation = 0.0

        # Same ticker = perfect correlation
        if pos1.get('ticker') == pos2.get('ticker'):
            return 1.0 if pos1.get('side') == pos2.get('side') else -1.0

        # Same city, same date = very high correlation
        if parsed1['city'] == parsed2['city'] and parsed1['date'] == parsed2['date']:
            base_corr = 0.9

            # Same market type (both HIGH or both LOW) = higher correlation
            if parsed1['market_type'] == parsed2['market_type']:
                base_corr = 0.95
            else:
                # HIGH and LOW in same city are negatively correlated
                base_corr = -0.3

            # Adjust for direction (same side = positive, opposite = negative)
            if pos1.get('side') != pos2.get('side'):
                base_corr = -base_corr

            return base_corr

        # Same city, different date = moderate correlation
        if parsed1['city'] == parsed2['city']:
            base_corr = 0.5
            if pos1.get('side') != pos2.get('side'):
                base_corr = -base_corr
            return base_corr

        # Different cities - check climate clusters
        city1, city2 = parsed1['city'], parsed2['city']

        # Direct city correlation lookup
        key = tuple(sorted([city1, city2]))
        if key in self.city_correlations:
            base_corr = self.city_correlations[key]
        else:
            # Check climate clusters
            base_corr = 0.0
            for cluster_name, cities in self.climate_clusters.items():
                if city1 in cities and city2 in cities:
                    base_corr = 0.2  # Same cluster = some correlation
                    break

        # Same date increases correlation
        if parsed1['date'] == parsed2['date']:
            base_corr *= 1.5

        # Same market type increases correlation
        if parsed1['market_type'] == parsed2['market_type']:
            base_corr *= 1.2

        # Opposite sides reduce correlation
        if pos1.get('side') != pos2.get('side'):
            base_corr = -base_corr

        return max(-1, min(1, base_corr))  # Clamp to [-1, 1]

    def build_correlation_matrix(self, positions: List[Dict]) -> List[List[float]]:
        """
        Build correlation matrix for all positions

        Args:
            positions: List of position dicts

        Returns:
            2D correlation matrix
        """
        n = len(positions)
        matrix = [[0.0] * n for _ in range(n)]

        for i in range(n):
            for j in range(n):
                if i == j:
                    matrix[i][j] = 1.0
                else:
                    matrix[i][j] = self.calculate_correlation(positions[i], positions[j])

        return matrix


class PortfolioVaR:
    """
    Calculate portfolio Value at Risk

    Uses variance-covariance method with position correlations.
    """

    def __init__(self, correlation_calculator: PositionCorrelation):
        self.correlation_calc = correlation_calculator

    def calculate_position_volatility(self, position: Dict) -> float:
        """
        Estimate position volatility (standard deviation of returns)

        For binary options, volatility depends on price (max at 50¢).
        """
        price = position.get('price', 50)
        count = position.get('count', 1)

        # Binary option volatility: sqrt(p * (1-p))
        p = price / 100.0
        single_contract_vol = math.sqrt(p * (1 - p))

        # Scale by position size
        return single_contract_vol * count

    def calculate_portfolio_var(self, positions: List[Dict],
                                 confidence_level: float = 0.95) -> Dict:
        """
        Calculate portfolio VaR using variance-covariance method

        Args:
            positions: List of position dicts with ticker, side, count, price
            confidence_level: VaR confidence level (e.g., 0.95 for 95% VaR)

        Returns:
            Dict with VaR metrics
        """
        if not positions:
            return {'var_95': 0, 'var_99': 0, 'expected_shortfall': 0}

        n = len(positions)

        # Calculate individual volatilities
        volatilities = [self.calculate_position_volatility(p) for p in positions]

        # Build correlation matrix
        corr_matrix = self.correlation_calc.build_correlation_matrix(positions)

        # Calculate portfolio variance
        # Var(portfolio) = sum_i sum_j (vol_i * vol_j * corr_ij)
        portfolio_variance = 0.0
        for i in range(n):
            for j in range(n):
                portfolio_variance += volatilities[i] * volatilities[j] * corr_matrix[i][j]

        portfolio_vol = math.sqrt(max(0, portfolio_variance))

        # Calculate VaR at different confidence levels
        # Z-score for 95% = 1.645, 99% = 2.326
        z_95 = 1.645
        z_99 = 2.326

        var_95 = portfolio_vol * z_95
        var_99 = portfolio_vol * z_99

        # Expected Shortfall (CVaR) - average loss beyond VaR
        # For normal distribution: ES = vol * pdf(z) / (1-confidence)
        es_95 = portfolio_vol * 2.063  # Approximate ES at 95%

        # Calculate individual contributions
        marginal_vars = []
        for i, pos in enumerate(positions):
            # Marginal VaR = how much this position contributes to total VaR
            marginal_var = 0.0
            for j in range(n):
                marginal_var += volatilities[i] * volatilities[j] * corr_matrix[i][j]

            if portfolio_vol > 0:
                marginal_var = (marginal_var / portfolio_vol) * z_95
            else:
                marginal_var = volatilities[i] * z_95

            marginal_vars.append({
                'ticker': pos.get('ticker'),
                'marginal_var': round(marginal_var, 4),
                'pct_contribution': round(marginal_var / var_95 * 100, 1) if var_95 > 0 else 0
            })

        return {
            'var_95': round(var_95, 4),
            'var_99': round(var_99, 4),
            'expected_shortfall_95': round(es_95, 4),
            'portfolio_volatility': round(portfolio_vol, 4),
            'total_exposure': sum(p.get('count', 0) * p.get('price', 0) / 100 for p in positions),
            'num_positions': n,
            'marginal_contributions': marginal_vars
        }


class CorrelationAwareRisk:
    """
    Main risk management class that integrates correlation-aware sizing.
    """

    def __init__(self, client=None):
        self.client = client
        self.correlation_calc = PositionCorrelation()
        self.var_calc = PortfolioVaR(self.correlation_calc)

        # Configuration
        self.max_correlated_exposure = 0.5  # Max 50% reduction for correlated positions
        self.correlation_threshold = 0.5  # Consider positions correlated above this

    def get_current_positions(self) -> List[Dict]:
        """Get current positions from client"""
        if not self.client:
            return []

        try:
            positions = self.client.get_positions()
            return [
                {
                    'ticker': p.get('ticker'),
                    'side': 'yes' if p.get('position', 0) > 0 else 'no',
                    'count': abs(p.get('position', 0)),
                    'price': p.get('market_exposure', 0) / max(1, abs(p.get('position', 1)))
                }
                for p in positions if p.get('position', 0) != 0
            ]
        except Exception as e:
            logger.warning(f"Could not get positions: {e}")
            return []

    def calculate_correlated_exposure(self, new_ticker: str, new_side: str,
                                       new_count: int = 1) -> Dict:
        """
        Calculate how much correlated exposure we already have

        Args:
            new_ticker: Ticker we're considering trading
            new_side: Side we're considering (yes/no)
            new_count: Number of contracts

        Returns:
            Dict with correlation metrics and suggested adjustment
        """
        current_positions = self.get_current_positions()

        if not current_positions:
            return {
                'total_correlation': 0,
                'correlated_contracts': 0,
                'adjustment_factor': 1.0,
                'max_correlated_position': None
            }

        new_position = {'ticker': new_ticker, 'side': new_side, 'count': new_count}
        total_correlation = 0
        correlated_contracts = 0
        max_correlation = 0
        max_correlated_position = None

        for pos in current_positions:
            corr = self.correlation_calc.calculate_correlation(new_position, pos)

            if corr > self.correlation_threshold:
                total_correlation += corr * pos['count']
                correlated_contracts += pos['count']

                if corr > max_correlation:
                    max_correlation = corr
                    max_correlated_position = pos

        # Calculate adjustment factor
        # More correlated exposure = smaller new position
        if correlated_contracts > 0:
            # Scale adjustment: at 10 correlated contracts, reduce by max_correlated_exposure
            adjustment = 1.0 - min(self.max_correlated_exposure,
                                    (correlated_contracts / 10) * self.max_correlated_exposure)
        else:
            adjustment = 1.0

        return {
            'total_correlation': round(total_correlation, 2),
            'correlated_contracts': correlated_contracts,
            'adjustment_factor': round(adjustment, 2),
            'max_correlation': round(max_correlation, 2),
            'max_correlated_position': max_correlated_position
        }

    def adjust_position_size(self, base_size: int, ticker: str, side: str) -> int:
        """
        Adjust position size based on correlated exposure

        Args:
            base_size: Original position size
            ticker: Ticker being traded
            side: Side being traded

        Returns:
            Adjusted position size
        """
        corr_data = self.calculate_correlated_exposure(ticker, side, base_size)

        adjusted_size = int(base_size * corr_data['adjustment_factor'])
        adjusted_size = max(1, adjusted_size)  # Always at least 1

        if adjusted_size < base_size:
            logger.info(f"📊 Correlation adjustment: {base_size} -> {adjusted_size} contracts "
                       f"(correlated: {corr_data['correlated_contracts']}, "
                       f"factor: {corr_data['adjustment_factor']})")

        return adjusted_size

    def get_portfolio_risk_report(self) -> Dict:
        """
        Generate comprehensive portfolio risk report

        Returns:
            Dict with VaR, correlations, and recommendations
        """
        positions = self.get_current_positions()

        if not positions:
            return {'error': 'No positions found'}

        # Calculate VaR
        var_metrics = self.var_calc.calculate_portfolio_var(positions)

        # Calculate correlation matrix summary
        corr_matrix = self.correlation_calc.build_correlation_matrix(positions)

        # Find highly correlated pairs
        high_correlations = []
        n = len(positions)
        for i in range(n):
            for j in range(i + 1, n):
                if abs(corr_matrix[i][j]) > 0.5:
                    high_correlations.append({
                        'pos1': positions[i]['ticker'],
                        'pos2': positions[j]['ticker'],
                        'correlation': round(corr_matrix[i][j], 2)
                    })

        # Group by city for concentration analysis
        by_city = defaultdict(lambda: {'count': 0, 'exposure': 0})
        for pos in positions:
            parsed = self.correlation_calc.parse_ticker(pos['ticker'])
            city = parsed.get('city', 'Unknown')
            by_city[city]['count'] += pos['count']
            by_city[city]['exposure'] += pos['count'] * pos.get('price', 50) / 100

        return {
            'var_metrics': var_metrics,
            'high_correlations': high_correlations,
            'concentration_by_city': dict(by_city),
            'total_positions': len(positions),
            'recommendations': self._generate_recommendations(positions, var_metrics, high_correlations)
        }

    def _generate_recommendations(self, positions: List[Dict], var_metrics: Dict,
                                   high_correlations: List[Dict]) -> List[str]:
        """Generate risk management recommendations"""
        recommendations = []

        # Check VaR level
        if var_metrics['var_95'] > 5.0:
            recommendations.append(f"⚠️ High VaR (${var_metrics['var_95']:.2f}): Consider reducing position sizes")

        # Check for concentration
        if len(high_correlations) > 3:
            recommendations.append(f"⚠️ High correlation: {len(high_correlations)} position pairs are >50% correlated")

        # Check for hedging opportunities
        for corr in high_correlations:
            if corr['correlation'] < -0.5:
                recommendations.append(f"✓ Natural hedge: {corr['pos1']} and {corr['pos2']} (corr: {corr['correlation']})")

        if not recommendations:
            recommendations.append("✓ Portfolio risk within normal parameters")

        return recommendations

    def print_risk_report(self):
        """Print formatted risk report"""
        report = self.get_portfolio_risk_report()

        if 'error' in report:
            print(f"Error: {report['error']}")
            return

        print(f"\n{'='*70}")
        print(f"  PORTFOLIO RISK REPORT")
        print(f"{'='*70}")

        var = report['var_metrics']
        print(f"\n  VALUE AT RISK:")
        print(f"  {'-'*66}")
        print(f"  95% VaR: ${var['var_95']:.4f}")
        print(f"  99% VaR: ${var['var_99']:.4f}")
        print(f"  Expected Shortfall (95%): ${var['expected_shortfall_95']:.4f}")
        print(f"  Portfolio Volatility: ${var['portfolio_volatility']:.4f}")
        print(f"  Total Exposure: ${var['total_exposure']:.2f}")

        print(f"\n  CONCENTRATION BY CITY:")
        print(f"  {'-'*66}")
        for city, data in sorted(report['concentration_by_city'].items(),
                                  key=lambda x: x[1]['exposure'], reverse=True):
            print(f"  {city}: {data['count']} contracts, ${data['exposure']:.2f} exposure")

        if report['high_correlations']:
            print(f"\n  HIGH CORRELATIONS (>50%):")
            print(f"  {'-'*66}")
            for corr in report['high_correlations'][:10]:
                print(f"  {corr['pos1']} <-> {corr['pos2']}: {corr['correlation']}")

        print(f"\n  RECOMMENDATIONS:")
        print(f"  {'-'*66}")
        for rec in report['recommendations']:
            print(f"  {rec}")


# Convenience function
def get_risk_manager(client=None) -> CorrelationAwareRisk:
    """Get correlation-aware risk manager"""
    return CorrelationAwareRisk(client)
