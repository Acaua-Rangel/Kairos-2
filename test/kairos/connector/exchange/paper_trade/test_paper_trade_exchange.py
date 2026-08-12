from decimal import Decimal
from unittest import TestCase

import pandas as pd

from kairos.connector.exchange.binance.binance_api_order_book_data_source import BinanceAPIOrderBookDataSource
from kairos.connector.exchange.paper_trade import create_paper_trade_market, get_order_book_tracker
from kairos.connector.exchange.paper_trade.paper_trade_exchange import QuantizationParams
from kairos.connector.test_support.mock_paper_exchange import MockPaperExchange
from kairos.core.clock import Clock, ClockMode
from kairos.core.data_type.common import OrderType, TradeType
from kairos.core.data_type.order_book_tracker import OrderBookTracker
from kairos.core.data_type.trade_fee import MakerTakerExchangeFeeRates, TradeFeeSchema
from kairos.core.data_type.trade_fee_registry import TradeFeeRegistry
from kairos.core.event.event_logger import EventLogger
from kairos.core.event.events import MarketEvent, OrderBookTradeEvent


class PaperTradeExchangeTests(TestCase):

    def test_get_order_book_tracker_for_connector_using_generic_tracker(self):
        tracker = get_order_book_tracker(connector_name="binance", trading_pairs=["COINALPHA-HBOT"])
        self.assertEqual(OrderBookTracker, type(tracker))

        tracker = get_order_book_tracker(connector_name="binance", trading_pairs=["COINALPHA-HBOT"])
        self.assertEqual(OrderBookTracker, type(tracker))

    def test_create_paper_trade_market_for_connector_using_generic_tracker(self):
        paper_exchange = create_paper_trade_market(
            exchange_name="binance",
            trading_pairs=["COINALPHA-HBOT"])
        self.assertEqual(BinanceAPIOrderBookDataSource, type(paper_exchange.order_book_tracker.data_source))

        paper_exchange = create_paper_trade_market(
            exchange_name="binance",
            trading_pairs=["COINALPHA-HBOT"])
        self.assertEqual(BinanceAPIOrderBookDataSource, type(paper_exchange.order_book_tracker.data_source))


class PaperTradeMatchingTests(TestCase):
    """Characterizes how the paper trade exchange decides that a simulated order got filled.

    The matching logic lives entirely in Cython (`paper_trade_exchange.pyx`) and had no direct
    coverage — its only exercise was indirect, through the PMM strategy tests. These tests pin the
    behaviour down so that changes to the fill model are deliberate rather than accidental.

    Book layout used throughout: mid 100, 1.0 price steps, so the best bid is 99.5 and the best ask
    is 100.5.
    """

    start_timestamp: float = pd.Timestamp("2019-01-01", tz="UTC").timestamp()
    end_timestamp: float = pd.Timestamp("2019-01-01 01:00:00", tz="UTC").timestamp()
    trading_pair = "HBOT-ETH"
    base_asset, quote_asset = trading_pair.split("-")

    def setUp(self):
        super().setUp()
        self.clock_tick_size = 1
        self.clock = Clock(ClockMode.BACKTEST, self.clock_tick_size, self.start_timestamp, self.end_timestamp)
        self.market = MockPaperExchange(
            trade_fee_schema=TradeFeeSchema(
                maker_percent_fee_decimal=Decimal("0.001"), taker_percent_fee_decimal=Decimal("0.002")
            )
        )
        self.market.set_balanced_order_book(self.trading_pair,
                                            mid_price=100,
                                            min_price=1,
                                            max_price=200,
                                            price_step_size=1,
                                            volume_step_size=10)
        self.market.set_balance(self.base_asset, 500)
        self.market.set_balance(self.quote_asset, 5000)
        self.market.set_quantization_param(QuantizationParams(self.trading_pair, 6, 6, 6, 6))
        self.clock.add_iterator(self.market)

        self.fill_logger = EventLogger()
        self.cancel_logger = EventLogger()
        self.complete_logger = EventLogger()
        self.market.add_listener(MarketEvent.OrderFilled, self.fill_logger)
        self.market.add_listener(MarketEvent.OrderCancelled, self.cancel_logger)
        self.market.add_listener(MarketEvent.BuyOrderCompleted, self.complete_logger)
        self.market.add_listener(MarketEvent.SellOrderCompleted, self.complete_logger)

    def tearDown(self):
        TradeFeeRegistry.clear()
        super().tearDown()

    def simulate_trade(self, is_buy: bool, quantity: Decimal, price: Decimal):
        """Push a single trade print into the book, which is what drives the event-driven fill path."""
        self.market.get_order_book(self.trading_pair).apply_trade(OrderBookTradeEvent(
            self.trading_pair,
            self.clock.current_timestamp,
            TradeType.BUY if is_buy else TradeType.SELL,
            price,
            quantity,
        ))

    # <editor-fold desc="Fill triggered by a trade print">

    def test_limit_buy_fills_when_a_sell_trade_prints_below_its_price(self):
        self.clock.backtest_til(self.start_timestamp + 1)
        order_id = self.market.buy(self.trading_pair, Decimal("1"), OrderType.LIMIT, Decimal("99"))
        self.assertEqual(1, len(self.market.limit_orders))

        self.simulate_trade(is_buy=False, quantity=Decimal("1"), price=Decimal("98.9"))

        self.assertEqual(0, len(self.market.limit_orders))
        self.assertEqual(1, len(self.fill_logger.event_log))
        fill = self.fill_logger.event_log[0]
        self.assertEqual(order_id, fill.order_id)
        self.assertEqual(TradeType.BUY, fill.trade_type)
        self.assertEqual(OrderType.LIMIT, fill.order_type)
        # Filled at the resting order's own price, not at the price that printed.
        self.assertEqual(Decimal("99"), fill.price)
        self.assertEqual(Decimal("1"), fill.amount)

    def test_limit_sell_fills_when_a_buy_trade_prints_above_its_price(self):
        self.clock.backtest_til(self.start_timestamp + 1)
        order_id = self.market.sell(self.trading_pair, Decimal("1"), OrderType.LIMIT, Decimal("101"))

        self.simulate_trade(is_buy=True, quantity=Decimal("1"), price=Decimal("101.1"))

        self.assertEqual(0, len(self.market.limit_orders))
        self.assertEqual(1, len(self.fill_logger.event_log))
        self.assertEqual(order_id, self.fill_logger.event_log[0].order_id)
        self.assertEqual(TradeType.SELL, self.fill_logger.event_log[0].trade_type)

    def test_trade_at_exactly_the_order_price_does_not_fill(self):
        """The comparison is strict: the trade has to go through the order's price, not merely reach
        it. This is the one place today where the simulation is *not* optimistic."""
        self.clock.backtest_til(self.start_timestamp + 1)
        self.market.buy(self.trading_pair, Decimal("1"), OrderType.LIMIT, Decimal("99"))

        self.simulate_trade(is_buy=False, quantity=Decimal("10"), price=Decimal("99"))

        self.assertEqual(1, len(self.market.limit_orders))
        self.assertEqual(0, len(self.fill_logger.event_log))

    def test_trade_quantity_is_ignored_so_a_tiny_print_fills_a_large_order(self):
        """No queue model: the traded volume never limits the fill, and the fill is all-or-nothing."""
        self.clock.backtest_til(self.start_timestamp + 1)
        self.market.buy(self.trading_pair, Decimal("40"), OrderType.LIMIT, Decimal("99"))

        self.simulate_trade(is_buy=False, quantity=Decimal("0.00001"), price=Decimal("98.9"))

        self.assertEqual(0, len(self.market.limit_orders))
        self.assertEqual(1, len(self.fill_logger.event_log))
        self.assertEqual(Decimal("40"), self.fill_logger.event_log[0].amount)

    def test_trade_on_the_same_side_never_fills(self):
        """A buy print can only fill resting asks, and a sell print only resting bids."""
        self.clock.backtest_til(self.start_timestamp + 1)
        self.market.buy(self.trading_pair, Decimal("1"), OrderType.LIMIT, Decimal("99"))

        self.simulate_trade(is_buy=True, quantity=Decimal("10"), price=Decimal("98.9"))

        self.assertEqual(1, len(self.market.limit_orders))
        self.assertEqual(0, len(self.fill_logger.event_log))

    # </editor-fold>

    # <editor-fold desc="Fill triggered by the book crossing on a tick">

    def test_limit_buy_priced_through_the_ask_fills_on_the_next_tick_without_any_trade(self):
        """The second, tick-driven fill path: no trade has to print at all — it is enough for the
        resting order to be at or through the opposite side of the book."""
        self.clock.backtest_til(self.start_timestamp + 1)
        self.market.buy(self.trading_pair, Decimal("1"), OrderType.LIMIT, Decimal("101"))
        self.assertEqual(1, len(self.market.limit_orders))

        self.clock.backtest_til(self.start_timestamp + 2)

        self.assertEqual(0, len(self.market.limit_orders))
        self.assertEqual(1, len(self.fill_logger.event_log))

    def test_limit_buy_below_the_ask_survives_ticks(self):
        self.clock.backtest_til(self.start_timestamp + 1)
        self.market.buy(self.trading_pair, Decimal("1"), OrderType.LIMIT, Decimal("99"))

        self.clock.backtest_til(self.start_timestamp + 10)

        self.assertEqual(1, len(self.market.limit_orders))
        self.assertEqual(0, len(self.fill_logger.event_log))

    def test_limit_sell_priced_through_the_bid_fills_on_the_next_tick(self):
        self.clock.backtest_til(self.start_timestamp + 1)
        self.market.sell(self.trading_pair, Decimal("1"), OrderType.LIMIT, Decimal("99"))

        self.clock.backtest_til(self.start_timestamp + 2)

        self.assertEqual(0, len(self.market.limit_orders))
        self.assertEqual(1, len(self.fill_logger.event_log))
        self.assertEqual(TradeType.SELL, self.fill_logger.event_log[0].trade_type)

    # </editor-fold>

    # <editor-fold desc="Balances, events and rejections">

    def test_filled_limit_buy_moves_both_balances_and_completes_the_order(self):
        self.clock.backtest_til(self.start_timestamp + 1)
        self.market.buy(self.trading_pair, Decimal("1"), OrderType.LIMIT, Decimal("99"))

        self.simulate_trade(is_buy=False, quantity=Decimal("1"), price=Decimal("98.9"))

        self.assertEqual(Decimal("501"), self.market.get_balance(self.base_asset))
        # BUG (characterized here, fixed in the next commit): only the raw notional is debited.
        # For a buy the percent fee lands in the candidate's `percent_fee_collateral`, which the
        # paper trade never reads, so the 0.099 maker fee is silently not charged.
        self.assertEqual(Decimal("4901"), self.market.get_balance(self.quote_asset))
        self.assertEqual(1, len(self.complete_logger.event_log))
        self.assertEqual(0, len(self.cancel_logger.event_log))

    def test_filled_limit_sell_moves_both_balances(self):
        self.clock.backtest_til(self.start_timestamp + 1)
        self.market.sell(self.trading_pair, Decimal("1"), OrderType.LIMIT, Decimal("101"))

        self.simulate_trade(is_buy=True, quantity=Decimal("1"), price=Decimal("101.1"))

        self.assertEqual(Decimal("499"), self.market.get_balance(self.base_asset))
        # 0.1% maker fee, charged out of the acquired quote asset.
        self.assertEqual(Decimal("5100.899"), self.market.get_balance(self.quote_asset))
        self.assertEqual(1, len(self.complete_logger.event_log))

    def test_limit_buy_with_insufficient_quote_balance_is_cancelled_instead_of_filled(self):
        self.market.set_balance(self.quote_asset, 10)
        self.clock.backtest_til(self.start_timestamp + 1)
        order_id = self.market.buy(self.trading_pair, Decimal("1"), OrderType.LIMIT, Decimal("99"))

        self.simulate_trade(is_buy=False, quantity=Decimal("1"), price=Decimal("98.9"))

        self.assertEqual(0, len(self.fill_logger.event_log))
        self.assertEqual(1, len(self.cancel_logger.event_log))
        self.assertEqual(order_id, self.cancel_logger.event_log[0].order_id)
        self.assertEqual(0, len(self.market.limit_orders))
        self.assertEqual(Decimal("10"), self.market.get_balance(self.quote_asset))

    def test_limit_sell_with_insufficient_base_balance_is_cancelled_instead_of_filled(self):
        self.market.set_balance(self.base_asset, Decimal("0.5"))
        self.clock.backtest_til(self.start_timestamp + 1)
        self.market.sell(self.trading_pair, Decimal("1"), OrderType.LIMIT, Decimal("101"))

        self.simulate_trade(is_buy=True, quantity=Decimal("1"), price=Decimal("101.1"))

        self.assertEqual(0, len(self.fill_logger.event_log))
        self.assertEqual(1, len(self.cancel_logger.event_log))
        self.assertEqual(Decimal("0.5"), self.market.get_balance(self.base_asset))

    def test_cancelled_order_leaves_the_book_and_stops_filling(self):
        self.clock.backtest_til(self.start_timestamp + 1)
        order_id = self.market.buy(self.trading_pair, Decimal("1"), OrderType.LIMIT, Decimal("99"))

        self.market.cancel(self.trading_pair, order_id)

        self.assertEqual(0, len(self.market.limit_orders))
        self.assertEqual(1, len(self.cancel_logger.event_log))

        self.simulate_trade(is_buy=False, quantity=Decimal("1"), price=Decimal("98.9"))
        self.assertEqual(0, len(self.fill_logger.event_log))

    # </editor-fold>

    # <editor-fold desc="Market orders">

    def test_market_order_is_queued_and_only_executes_after_the_execution_delay(self):
        self.clock.backtest_til(self.start_timestamp + 1)
        self.market.buy(self.trading_pair, Decimal("1"), OrderType.MARKET)

        self.assertEqual(1, len(self.market.queued_orders))
        self.clock.backtest_til(self.start_timestamp + 1 + self.market.TRADE_EXECUTION_DELAY - 1)
        self.assertEqual(0, len(self.fill_logger.event_log))

        self.clock.backtest_til(self.start_timestamp + 1 + self.market.TRADE_EXECUTION_DELAY)

        self.assertEqual(0, len(self.market.queued_orders))
        self.assertLess(0, len(self.fill_logger.event_log))
        self.assertTrue(all(f.order_type is OrderType.MARKET for f in self.fill_logger.event_log))
        # Taker, and walked into the asks, so it paid at or above the best ask.
        self.assertLessEqual(Decimal("100.5"), self.fill_logger.event_log[0].price)

    # </editor-fold>

    # <editor-fold desc="Fees applied to the recorded fill">

    def test_recorded_maker_fill_uses_the_exchange_fee_schema(self):
        self.clock.backtest_til(self.start_timestamp + 1)
        self.market.buy(self.trading_pair, Decimal("1"), OrderType.LIMIT, Decimal("99"))

        self.simulate_trade(is_buy=False, quantity=Decimal("1"), price=Decimal("98.9"))

        self.assertEqual(Decimal("0.001"), self.fill_logger.event_log[0].trade_fee.percent)

    def test_recorded_taker_fill_uses_the_taker_rate(self):
        self.clock.backtest_til(self.start_timestamp + 1)
        self.market.buy(self.trading_pair, Decimal("1"), OrderType.MARKET)

        self.clock.backtest_til(self.start_timestamp + 1 + self.market.TRADE_EXECUTION_DELAY)

        self.assertEqual(Decimal("0.002"), self.fill_logger.event_log[0].trade_fee.percent)

    def test_recorded_fill_prefers_the_real_per_pair_rate_from_the_registry(self):
        """The registry is populated from the exchange's live fee endpoint, so a promo pair (0% maker)
        must show up as 0% on the simulated fill instead of the schema default."""
        TradeFeeRegistry.set_rates(self.market.name, {
            self.trading_pair: MakerTakerExchangeFeeRates(
                maker=Decimal("0"), taker=Decimal("0.0005"), maker_flat_fees=[], taker_flat_fees=[]
            )
        })
        self.clock.backtest_til(self.start_timestamp + 1)
        self.market.buy(self.trading_pair, Decimal("1"), OrderType.LIMIT, Decimal("99"))

        self.simulate_trade(is_buy=False, quantity=Decimal("1"), price=Decimal("98.9"))

        self.assertEqual(Decimal("0"), self.fill_logger.event_log[0].trade_fee.percent)

    # </editor-fold>
