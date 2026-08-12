from decimal import Decimal
from unittest import TestCase

import pandas as pd

from kairos.connector.exchange.binance.binance_api_order_book_data_source import BinanceAPIOrderBookDataSource
from kairos.connector.exchange.paper_trade import create_paper_trade_market, get_order_book_tracker
from kairos.connector.exchange.paper_trade.paper_trade_exchange import QuantizationParams
from kairos.connector.test_support.mock_paper_exchange import MockPaperExchange
from kairos.core.clock import Clock, ClockMode
from kairos.core.data_type.common import OrderType, TradeType
from kairos.core.data_type.order_book_row import OrderBookRow
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
        self.simulate_trade_at(self.clock.current_timestamp, is_buy, quantity, price)

    def simulate_trade_at(self, timestamp: float, is_buy: bool, quantity: Decimal, price: Decimal):
        self.market.get_order_book(self.trading_pair).apply_trade(OrderBookTradeEvent(
            self.trading_pair,
            timestamp,
            TradeType.BUY if is_buy else TradeType.SELL,
            price,
            quantity,
        ))

    def drop_best_ask_to(self, price: float):
        """Move the book so that a resting bid above `price` becomes crossed, without trading."""
        order_book = self.market.get_order_book(self.trading_pair)
        update_id = order_book.last_diff_uid + 1
        order_book.apply_diffs([], [OrderBookRow(price, 5.0, update_id)], update_id)

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

    def test_order_priced_where_nothing_rests_fills_from_a_print_at_that_price(self):
        """99 sits between two book levels (99.5 and 98.5), so an order there improves the book and
        starts at the front of an empty queue."""
        self.clock.backtest_til(self.start_timestamp + 1)
        self.market.buy(self.trading_pair, Decimal("1"), OrderType.LIMIT, Decimal("99"))

        self.simulate_trade(is_buy=False, quantity=Decimal("10"), price=Decimal("99"))

        self.assertEqual(0, len(self.market.limit_orders))
        self.assertEqual(1, len(self.fill_logger.event_log))

    def test_a_print_through_the_price_still_fills_the_whole_order(self):
        """A print below the order's price means the level it rested on was swept whole, so there is
        no queue left to wait behind."""
        self.clock.backtest_til(self.start_timestamp + 1)
        self.market.buy(self.trading_pair, Decimal("40"), OrderType.LIMIT, Decimal("99"))

        self.simulate_trade(is_buy=False, quantity=Decimal("0.00001"), price=Decimal("98.9"))

        self.assertEqual(0, len(self.market.limit_orders))
        self.assertEqual(1, len(self.fill_logger.event_log))
        self.assertEqual(Decimal("40"), self.fill_logger.event_log[0].amount)

    # </editor-fold>

    # <editor-fold desc="Queue position">

    # The book has 20 units resting at 98.5, which is what an order placed there has to wait behind.

    def test_order_does_not_fill_while_the_queue_ahead_of_it_is_being_consumed(self):
        self.clock.backtest_til(self.start_timestamp + 1)
        self.market.buy(self.trading_pair, Decimal("1"), OrderType.LIMIT, Decimal("98.5"))

        self.simulate_trade(is_buy=False, quantity=Decimal("20"), price=Decimal("98.5"))

        self.assertEqual(1, len(self.market.limit_orders))
        self.assertEqual(0, len(self.fill_logger.event_log))

    def test_order_fills_from_what_is_left_after_the_queue_is_exhausted(self):
        self.clock.backtest_til(self.start_timestamp + 1)
        self.market.buy(self.trading_pair, Decimal("1"), OrderType.LIMIT, Decimal("98.5"))

        self.simulate_trade(is_buy=False, quantity=Decimal("21"), price=Decimal("98.5"))

        self.assertEqual(0, len(self.market.limit_orders))
        self.assertEqual(1, len(self.fill_logger.event_log))
        self.assertEqual(Decimal("1"), self.fill_logger.event_log[0].amount)

    def test_the_queue_is_consumed_across_several_prints(self):
        self.clock.backtest_til(self.start_timestamp + 1)
        self.market.buy(self.trading_pair, Decimal("1"), OrderType.LIMIT, Decimal("98.5"))

        for _ in range(4):
            self.simulate_trade(is_buy=False, quantity=Decimal("5"), price=Decimal("98.5"))
        self.assertEqual(0, len(self.fill_logger.event_log))

        self.simulate_trade(is_buy=False, quantity=Decimal("1"), price=Decimal("98.5"))
        self.assertEqual(1, len(self.fill_logger.event_log))

    def test_a_sell_order_waits_behind_the_ask_side_queue(self):
        self.clock.backtest_til(self.start_timestamp + 1)
        self.market.sell(self.trading_pair, Decimal("1"), OrderType.LIMIT, Decimal("101.5"))

        self.simulate_trade(is_buy=True, quantity=Decimal("20"), price=Decimal("101.5"))
        self.assertEqual(0, len(self.fill_logger.event_log))

        self.simulate_trade(is_buy=True, quantity=Decimal("1"), price=Decimal("101.5"))
        self.assertEqual(1, len(self.fill_logger.event_log))

    def test_one_print_is_shared_between_two_orders_at_the_same_price(self):
        """The print is walked across the level, so it cannot fill more in total than actually
        traded there."""
        self.clock.backtest_til(self.start_timestamp + 1)
        self.market.buy(self.trading_pair, Decimal("1"), OrderType.LIMIT, Decimal("98.5"))
        self.market.buy(self.trading_pair, Decimal("1"), OrderType.LIMIT, Decimal("98.5"))

        # 20 clears the queue, leaving 1 — enough for exactly one of the two orders.
        self.simulate_trade(is_buy=False, quantity=Decimal("21"), price=Decimal("98.5"))

        self.assertEqual(1, len(self.fill_logger.event_log))
        self.assertEqual(1, len(self.market.limit_orders))

    # </editor-fold>

    # <editor-fold desc="Partial fills">

    def test_a_print_smaller_than_the_order_fills_it_partially_and_leaves_it_resting(self):
        self.clock.backtest_til(self.start_timestamp + 1)
        self.market.buy(self.trading_pair, Decimal("1"), OrderType.LIMIT, Decimal("98.5"))

        self.simulate_trade(is_buy=False, quantity=Decimal("20.4"), price=Decimal("98.5"))

        self.assertEqual(1, len(self.fill_logger.event_log))
        self.assertEqual(Decimal("0.4"), self.fill_logger.event_log[0].amount)
        self.assertEqual(0, len(self.complete_logger.event_log))

        self.assertEqual(1, len(self.market.limit_orders))
        resting = self.market.limit_orders[0]
        self.assertEqual(Decimal("1"), resting.quantity)
        self.assertEqual(Decimal("0.4"), resting.filled_quantity)
        self.assertEqual(Decimal("98.5"), resting.price)

    def test_successive_prints_complete_a_partially_filled_order(self):
        self.clock.backtest_til(self.start_timestamp + 1)
        self.market.buy(self.trading_pair, Decimal("1"), OrderType.LIMIT, Decimal("98.5"))

        self.simulate_trade(is_buy=False, quantity=Decimal("20.4"), price=Decimal("98.5"))
        self.simulate_trade(is_buy=False, quantity=Decimal("0.6"), price=Decimal("98.5"))

        self.assertEqual(0, len(self.market.limit_orders))
        self.assertEqual([Decimal("0.4"), Decimal("0.6")],
                         [f.amount for f in self.fill_logger.event_log])
        # One completion, reporting the sum of both fills rather than just the last one.
        self.assertEqual(1, len(self.complete_logger.event_log))
        self.assertEqual(Decimal("1"), self.complete_logger.event_log[0].base_asset_amount)
        self.assertEqual(Decimal("501"), self.market.get_balance(self.base_asset))

    def test_a_partial_fill_only_reserves_the_remainder(self):
        self.clock.backtest_til(self.start_timestamp + 1)
        self.market.buy(self.trading_pair, Decimal("1"), OrderType.LIMIT, Decimal("98.5"))
        self.simulate_trade(is_buy=False, quantity=Decimal("20.4"), price=Decimal("98.5"))

        held = Decimal("5000") - self.market.get_available_balance(self.quote_asset)
        # 0.6 still outstanding at 98.5, plus the 98.5 * 1.0 * 0.001 fee already paid on the fill.
        self.assertEqual(Decimal("0.6") * Decimal("98.5"), held - Decimal("0.4") * Decimal("98.5") * Decimal("1.001"))

    # </editor-fold>

    # <editor-fold desc="The legacy fill model">

    def test_optimistic_model_ignores_traded_volume_entirely(self):
        self.market.fill_model = "optimistic"
        self.clock.backtest_til(self.start_timestamp + 1)
        self.market.buy(self.trading_pair, Decimal("1"), OrderType.LIMIT, Decimal("98.5"))

        # Would not even clear the queue under the queue model.
        self.simulate_trade(is_buy=False, quantity=Decimal("0.00001"), price=Decimal("98.4"))

        self.assertEqual(0, len(self.market.limit_orders))
        self.assertEqual(Decimal("1"), self.fill_logger.event_log[0].amount)

    def test_optimistic_model_fills_on_a_book_cross_with_no_trade(self):
        self.market.fill_model = "optimistic"
        self.clock.backtest_til(self.start_timestamp + 1)
        self.market.buy(self.trading_pair, Decimal("1"), OrderType.LIMIT, Decimal("99"))
        self.drop_best_ask_to(98.0)

        self.clock.backtest_til(self.start_timestamp + 2)

        self.assertEqual(0, len(self.market.limit_orders))
        self.assertEqual(1, len(self.fill_logger.event_log))

    def test_queue_model_does_not_fill_on_a_book_cross_with_no_trade(self):
        """An order that only becomes marketable later has to wait for something to actually trade
        at its price — otherwise it jumps the whole queue at that level for free."""
        self.clock.backtest_til(self.start_timestamp + 1)
        self.market.buy(self.trading_pair, Decimal("1"), OrderType.LIMIT, Decimal("99"))
        self.drop_best_ask_to(98.0)

        self.clock.backtest_til(self.start_timestamp + 5)

        self.assertEqual(1, len(self.market.limit_orders))
        self.assertEqual(0, len(self.fill_logger.event_log))

    def test_unknown_fill_model_is_rejected(self):
        with self.assertRaises(ValueError):
            self.market.fill_model = "wishful"

    # </editor-fold>

    # <editor-fold desc="Latency">

    def test_latency_is_off_by_default(self):
        self.assertEqual(0, self.market.order_latency)

    def test_negative_latency_is_rejected(self):
        with self.assertRaises(ValueError):
            self.market.order_latency = -1

    def test_an_order_in_flight_is_not_on_the_book_yet(self):
        self.market.order_latency = 2
        self.clock.backtest_til(self.start_timestamp + 1)
        self.market.buy(self.trading_pair, Decimal("1"), OrderType.LIMIT, Decimal("99"))

        self.assertEqual(0, len(self.market.limit_orders))

    def test_an_order_in_flight_cannot_be_filled(self):
        self.market.order_latency = 2
        self.clock.backtest_til(self.start_timestamp + 1)
        self.market.buy(self.trading_pair, Decimal("1"), OrderType.LIMIT, Decimal("99"))

        self.simulate_trade(is_buy=False, quantity=Decimal("10"), price=Decimal("98.9"))

        self.assertEqual(0, len(self.fill_logger.event_log))

    def test_an_order_lands_once_its_flight_time_has_elapsed(self):
        self.market.order_latency = 2
        self.clock.backtest_til(self.start_timestamp + 1)
        self.market.buy(self.trading_pair, Decimal("1"), OrderType.LIMIT, Decimal("99"))

        self.clock.backtest_til(self.start_timestamp + 3)
        self.assertEqual(1, len(self.market.limit_orders))

        self.simulate_trade(is_buy=False, quantity=Decimal("10"), price=Decimal("98.9"))
        self.assertEqual(1, len(self.fill_logger.event_log))

    def test_queue_position_is_read_from_the_book_on_arrival_not_on_send(self):
        """The point of landing the order late: it queues behind the book as it is when it gets
        there. Here the level fills up while the order is still in flight."""
        self.market.order_latency = 2
        self.clock.backtest_til(self.start_timestamp + 1)
        self.market.buy(self.trading_pair, Decimal("1"), OrderType.LIMIT, Decimal("99"))
        # 30 units appear at 99 while the order is on its way.
        order_book = self.market.get_order_book(self.trading_pair)
        update_id = order_book.last_diff_uid + 1
        order_book.apply_diffs([OrderBookRow(99.0, 30.0, update_id)], [], update_id)

        self.clock.backtest_til(self.start_timestamp + 3)

        # Had the queue been read at send time it would have been empty and this would fill.
        self.simulate_trade(is_buy=False, quantity=Decimal("10"), price=Decimal("99"))
        self.assertEqual(0, len(self.fill_logger.event_log))

    def test_a_cancel_in_flight_leaves_the_order_fillable(self):
        """Adverse selection: the price runs against you, you pull the quote, and you get filled
        anyway on the way out."""
        self.market.order_latency = 2
        self.clock.backtest_til(self.start_timestamp + 1)
        order_id = self.market.buy(self.trading_pair, Decimal("1"), OrderType.LIMIT, Decimal("99"))
        self.clock.backtest_til(self.start_timestamp + 3)

        self.market.cancel(self.trading_pair, order_id)
        self.assertEqual(1, len(self.market.limit_orders))
        self.assertEqual(0, len(self.cancel_logger.event_log))

        self.simulate_trade(is_buy=False, quantity=Decimal("10"), price=Decimal("98.9"))

        self.assertEqual(1, len(self.fill_logger.event_log))
        self.assertEqual(0, len(self.cancel_logger.event_log))

    def test_a_cancel_completes_once_its_flight_time_has_elapsed(self):
        self.market.order_latency = 2
        self.clock.backtest_til(self.start_timestamp + 1)
        order_id = self.market.buy(self.trading_pair, Decimal("1"), OrderType.LIMIT, Decimal("99"))
        self.clock.backtest_til(self.start_timestamp + 3)

        self.market.cancel(self.trading_pair, order_id)
        self.clock.backtest_til(self.start_timestamp + 6)

        self.assertEqual(0, len(self.market.limit_orders))
        self.assertEqual(1, len(self.cancel_logger.event_log))
        self.assertEqual(order_id, self.cancel_logger.event_log[0].order_id)

    def test_an_order_that_filled_before_its_cancel_arrived_is_not_cancelled_afterwards(self):
        self.market.order_latency = 2
        self.clock.backtest_til(self.start_timestamp + 1)
        order_id = self.market.buy(self.trading_pair, Decimal("1"), OrderType.LIMIT, Decimal("99"))
        self.clock.backtest_til(self.start_timestamp + 3)

        self.market.cancel(self.trading_pair, order_id)
        self.simulate_trade(is_buy=False, quantity=Decimal("10"), price=Decimal("98.9"))
        self.clock.backtest_til(self.start_timestamp + 8)

        self.assertEqual(1, len(self.fill_logger.event_log))
        self.assertEqual(0, len(self.cancel_logger.event_log))

    def test_a_print_lands_in_flight_orders_at_its_own_timestamp_not_the_last_tick(self):
        """Sub-tick latency still bites, because a print carries a finer timestamp than the clock."""
        self.market.order_latency = 0.2
        self.clock.backtest_til(self.start_timestamp + 1)
        self.market.buy(self.trading_pair, Decimal("1"), OrderType.LIMIT, Decimal("99"))

        # 0.1s after the send: still in flight, so nothing to fill.
        self.simulate_trade_at(self.clock.current_timestamp + 0.1,
                               is_buy=False, quantity=Decimal("10"), price=Decimal("98.9"))
        self.assertEqual(0, len(self.fill_logger.event_log))

        # 0.3s after the send, and the clock has not ticked in between.
        self.simulate_trade_at(self.clock.current_timestamp + 0.3,
                               is_buy=False, quantity=Decimal("10"), price=Decimal("98.9"))
        self.assertEqual(1, len(self.fill_logger.event_log))

    def test_market_order_delay_is_configurable(self):
        self.market.market_order_delay = 2
        self.clock.backtest_til(self.start_timestamp + 1)
        self.market.buy(self.trading_pair, Decimal("1"), OrderType.MARKET)

        self.clock.backtest_til(self.start_timestamp + 2)
        self.assertEqual(0, len(self.fill_logger.event_log))

        self.clock.backtest_til(self.start_timestamp + 3)
        self.assertLess(0, len(self.fill_logger.event_log))

    def test_trade_on_the_same_side_never_fills(self):
        """A buy print can only fill resting asks, and a sell print only resting bids."""
        self.clock.backtest_til(self.start_timestamp + 1)
        self.market.buy(self.trading_pair, Decimal("1"), OrderType.LIMIT, Decimal("99"))

        self.simulate_trade(is_buy=True, quantity=Decimal("10"), price=Decimal("98.9"))

        self.assertEqual(1, len(self.market.limit_orders))
        self.assertEqual(0, len(self.fill_logger.event_log))

    # </editor-fold>

    # <editor-fold desc="Marketable limit orders">

    def test_limit_buy_placed_through_the_ask_fills_on_the_next_tick_without_any_trade(self):
        """An order that already crosses the spread when placed is a taker: it lifts what is resting
        on the other side, so it fills straight off the book with no print needed."""
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

    def test_limit_sell_placed_through_the_bid_fills_on_the_next_tick(self):
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
        # 99 for the base, plus the 0.1% maker fee added on top of the cost.
        self.assertEqual(Decimal("4900.901"), self.market.get_balance(self.quote_asset))
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
        # ...and with no fee the cost is exactly the notional, with no 0.099 skim.
        self.assertEqual(Decimal("4901"), self.market.get_balance(self.quote_asset))

    # </editor-fold>
