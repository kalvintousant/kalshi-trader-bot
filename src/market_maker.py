"""
Market Making Mode

Instead of always paying the ask (taking liquidity), this module:
- Posts limit orders at better prices (providing liquidity)
- Manages queue position
- Earns the spread when possible
- Cancels and replaces orders as market moves

Key concepts:
- Maker orders: Posted at or below best bid (for buys), earn the spread
- Taker orders: Hit the ask immediately, pay the spread
- Edge improvement: By posting at bid+1 instead of ask, we improve entry by ~spread
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from src.config import Config

logger = logging.getLogger(__name__)


class MarketMaker:
    """
    Market making strategy overlay

    Posts limit orders at better prices to earn the spread instead of paying it.
    """

    def __init__(self, client, aggressive_threshold: int = 3):
        """
        Args:
            client: KalshiClient instance
            aggressive_threshold: Cents from fair value to switch to taking (default 3)
        """
        self.client = client
        self.aggressive_threshold = aggressive_threshold

        # Track our resting orders for management
        self.managed_orders: Dict[str, Dict] = {}  # order_id -> order_info

        # Configuration
        self.min_edge_to_make = Config.MIN_EDGE_THRESHOLD  # Minimum edge to post maker orders
        self.max_spread_to_make = 10  # Don't make markets wider than 10¢
        self.requote_threshold = 2  # Requote if market moves 2¢ away from our order

    def calculate_maker_price(self, side: str, orderbook: Dict, our_fair_value: int,
                               edge: float) -> Tuple[int, str]:
        """
        Calculate optimal maker price

        Args:
            side: 'yes' or 'no'
            orderbook: Current orderbook
            our_fair_value: Our calculated fair value in cents
            edge: Our calculated edge percentage

        Returns:
            (price, order_type) where order_type is 'maker' or 'taker'
        """
        yes_orders = orderbook.get('orderbook', {}).get('yes', [])
        no_orders = orderbook.get('orderbook', {}).get('no', [])

        if side == 'yes':
            # For YES buys: we want to post at YES bid or slightly above
            # Best YES bid is the highest price someone will pay for YES
            best_yes_bid = yes_orders[-1][0] if yes_orders else 0
            # YES ask is 100 - best NO bid
            best_no_bid = no_orders[-1][0] if no_orders else 50
            best_yes_ask = 100 - best_no_bid

            spread = best_yes_ask - best_yes_bid

            # If spread is too wide, post in the middle
            if spread > self.max_spread_to_make:
                # Post at fair value minus a small buffer
                maker_price = min(our_fair_value - 1, best_yes_ask - 2)
                maker_price = max(maker_price, best_yes_bid + 1)  # Don't go below best bid
            else:
                # Post 1¢ above best bid to be first in queue at better price
                maker_price = best_yes_bid + 1

            # If edge is very high or price is close to fair value, just take
            if edge > 25 or (best_yes_ask - our_fair_value) <= self.aggressive_threshold:
                return best_yes_ask, 'taker'

            return maker_price, 'maker'

        else:  # NO side
            # For NO buys: we want to post at NO bid or slightly above
            best_no_bid = no_orders[-1][0] if no_orders else 0
            # NO ask is 100 - best YES bid
            best_yes_bid = yes_orders[-1][0] if yes_orders else 50
            best_no_ask = 100 - best_yes_bid

            spread = best_no_ask - best_no_bid

            if spread > self.max_spread_to_make:
                maker_price = min(our_fair_value - 1, best_no_ask - 2)
                maker_price = max(maker_price, best_no_bid + 1)
            else:
                maker_price = best_no_bid + 1

            if edge > 25 or (best_no_ask - our_fair_value) <= self.aggressive_threshold:
                return best_no_ask, 'taker'

            return maker_price, 'maker'

    def should_requote(self, order_id: str, current_orderbook: Dict) -> Tuple[bool, Optional[int]]:
        """
        Check if we should cancel and replace an order

        Returns:
            (should_requote, new_price or None)
        """
        if order_id not in self.managed_orders:
            return False, None

        order_info = self.managed_orders[order_id]
        side = order_info['side']
        our_price = order_info['price']

        yes_orders = current_orderbook.get('orderbook', {}).get('yes', [])
        no_orders = current_orderbook.get('orderbook', {}).get('no', [])

        if side == 'yes':
            best_yes_bid = yes_orders[-1][0] if yes_orders else 0
            best_no_bid = no_orders[-1][0] if no_orders else 50
            best_yes_ask = 100 - best_no_bid

            # If someone outbid us significantly, requote
            if best_yes_bid > our_price + self.requote_threshold:
                new_price = best_yes_bid + 1
                if new_price < best_yes_ask:  # Still a maker order
                    return True, new_price

            # If the ask dropped significantly, we might want to take instead
            if best_yes_ask < our_price:
                return True, best_yes_ask  # Switch to taker
        else:
            best_no_bid = no_orders[-1][0] if no_orders else 0
            best_yes_bid = yes_orders[-1][0] if yes_orders else 50
            best_no_ask = 100 - best_yes_bid

            if best_no_bid > our_price + self.requote_threshold:
                new_price = best_no_bid + 1
                if new_price < best_no_ask:
                    return True, new_price

            if best_no_ask < our_price:
                return True, best_no_ask

        return False, None

    def track_order(self, order_id: str, ticker: str, side: str, price: int,
                    count: int, order_type: str):
        """Track a managed order"""
        self.managed_orders[order_id] = {
            'ticker': ticker,
            'side': side,
            'price': price,
            'count': count,
            'order_type': order_type,
            'placed_at': datetime.now()
        }
        logger.info(f"📝 Tracking {order_type} order {order_id}: {side.upper()} {count}@{price}¢")

    def untrack_order(self, order_id: str):
        """Stop tracking an order (filled or cancelled)"""
        if order_id in self.managed_orders:
            del self.managed_orders[order_id]

    def get_managed_orders(self) -> Dict[str, Dict]:
        """Get all managed orders"""
        return self.managed_orders.copy()

    def manage_orders(self):
        """
        Main order management loop

        Checks all managed orders and requotes if necessary.
        Should be called periodically (e.g., every scan cycle).
        """
        if not self.managed_orders:
            return

        orders_to_requote = []

        for order_id, order_info in list(self.managed_orders.items()):
            ticker = order_info['ticker']

            try:
                # Get current orderbook
                orderbook = self.client.get_market_orderbook(ticker)

                should_requote, new_price = self.should_requote(order_id, orderbook)

                if should_requote and new_price:
                    orders_to_requote.append((order_id, order_info, new_price))
            except Exception as e:
                logger.debug(f"Error checking order {order_id}: {e}")

        # Process requotes
        for order_id, order_info, new_price in orders_to_requote:
            try:
                # Cancel old order
                self.client.cancel_order(order_id)
                self.untrack_order(order_id)

                # Place new order at better price
                # Note: This requires the caller to handle the new order placement
                logger.info(f"🔄 Requoting {order_id}: {order_info['side'].upper()} {order_info['price']}¢ -> {new_price}¢")

            except Exception as e:
                logger.warning(f"Error requoting order {order_id}: {e}")


class SmartOrderRouter:
    """
    Smart order routing to minimize execution cost

    Decides whether to:
    - Post a maker order (earn spread, slower fill)
    - Take liquidity (pay spread, immediate fill)
    - Split the order across prices
    """

    def __init__(self, market_maker: MarketMaker):
        self.market_maker = market_maker

    def route_order(self, side: str, count: int, orderbook: Dict,
                    our_fair_value: int, edge: float, urgency: str = 'normal') -> List[Dict]:
        """
        Route an order optimally

        Args:
            side: 'yes' or 'no'
            count: Number of contracts
            orderbook: Current orderbook
            our_fair_value: Our fair value estimate in cents
            edge: Calculated edge percentage
            urgency: 'low' (maker only), 'normal' (smart), 'high' (taker only)

        Returns:
            List of order instructions: [{'price': int, 'count': int, 'type': str}]
        """
        if urgency == 'high':
            # Immediate execution needed - just take
            yes_orders = orderbook.get('orderbook', {}).get('yes', [])
            no_orders = orderbook.get('orderbook', {}).get('no', [])

            if side == 'yes':
                best_no_bid = no_orders[-1][0] if no_orders else 50
                ask_price = 100 - best_no_bid
            else:
                best_yes_bid = yes_orders[-1][0] if yes_orders else 50
                ask_price = 100 - best_yes_bid

            return [{'price': ask_price, 'count': count, 'type': 'taker'}]

        if urgency == 'low':
            # Patient - always make
            price, _ = self.market_maker.calculate_maker_price(
                side, orderbook, our_fair_value, edge
            )
            return [{'price': price, 'count': count, 'type': 'maker'}]

        # Normal urgency - smart routing
        price, order_type = self.market_maker.calculate_maker_price(
            side, orderbook, our_fair_value, edge
        )

        # For larger orders, consider splitting
        if count > 3 and order_type == 'maker':
            # Split: some at maker price, some at slightly better to ensure partial fill
            maker_count = count // 2
            aggressive_count = count - maker_count

            yes_orders = orderbook.get('orderbook', {}).get('yes', [])
            no_orders = orderbook.get('orderbook', {}).get('no', [])

            if side == 'yes':
                best_no_bid = no_orders[-1][0] if no_orders else 50
                aggressive_price = min(price + 1, 100 - best_no_bid)
            else:
                best_yes_bid = yes_orders[-1][0] if yes_orders else 50
                aggressive_price = min(price + 1, 100 - best_yes_bid)

            return [
                {'price': price, 'count': maker_count, 'type': 'maker'},
                {'price': aggressive_price, 'count': aggressive_count, 'type': 'maker'}
            ]

        return [{'price': price, 'count': count, 'type': order_type}]

    def estimate_fill_probability(self, side: str, price: int, orderbook: Dict,
                                   time_horizon_minutes: int = 30) -> float:
        """
        Estimate probability of fill at given price

        Args:
            side: 'yes' or 'no'
            price: Limit price
            orderbook: Current orderbook
            time_horizon_minutes: Time window for fill probability

        Returns:
            Estimated fill probability (0-1)
        """
        yes_orders = orderbook.get('orderbook', {}).get('yes', [])
        no_orders = orderbook.get('orderbook', {}).get('no', [])

        if side == 'yes':
            best_yes_bid = yes_orders[-1][0] if yes_orders else 0
            best_no_bid = no_orders[-1][0] if no_orders else 50
            ask = 100 - best_no_bid
            spread = ask - best_yes_bid
        else:
            best_no_bid = no_orders[-1][0] if no_orders else 0
            best_yes_bid = yes_orders[-1][0] if yes_orders else 50
            ask = 100 - best_yes_bid
            spread = ask - best_no_bid

        # Simple heuristic: closer to ask = higher fill probability
        if price >= ask:
            return 1.0  # Immediate fill
        elif spread == 0:
            return 0.5

        distance_from_ask = ask - price
        fill_prob = max(0, 1 - (distance_from_ask / spread) * 0.5)

        # Adjust for time horizon
        time_factor = min(1, time_horizon_minutes / 60)
        fill_prob = fill_prob * 0.5 + fill_prob * 0.5 * time_factor

        return fill_prob


def add_market_making_to_config():
    """Add market making configuration options to Config class"""
    # These would be added to config.py
    defaults = {
        'MARKET_MAKING_ENABLED': True,
        'MM_MIN_SPREAD_TO_MAKE': 3,  # Minimum spread to post maker orders
        'MM_MAX_SPREAD_TO_MAKE': 15,  # Maximum spread - don't make very wide markets
        'MM_REQUOTE_THRESHOLD': 2,  # Requote if outbid by this many cents
        'MM_AGGRESSIVE_EDGE_THRESHOLD': 25,  # Switch to taker if edge > this
        'MM_ORDER_URGENCY': 'normal',  # 'low', 'normal', 'high'
    }
    return defaults
