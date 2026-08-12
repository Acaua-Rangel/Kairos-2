import unittest
from decimal import Decimal

from kairos.core.data_type.common import OrderType, TradeType
from kairos.core.data_type.trade_fee import MakerTakerExchangeFeeRates
from kairos.core.data_type.trade_fee_registry import TradeFeeRegistry
from kairos.strategy_v2.backtesting.backtesting_engine_base import _DEFAULT_TRADE_COST, _resolve_backtesting_trade_cost
from kairos.strategy_v2.executors.dca_executor.data_types import DCAExecutorConfig
from kairos.strategy_v2.executors.grid_executor.data_types import GridExecutorConfig
from kairos.strategy_v2.executors.order_executor.data_types import (
    ExecutionStrategy,
    LimitChaserConfig,
    OrderExecutorConfig,
)
from kairos.strategy_v2.executors.position_executor.data_types import PositionExecutorConfig, TripleBarrierConfig

BINANCE_MAKER = Decimal("0")       # a promo-style rate (e.g. Binance's FDUSD 0% maker), so tests
BINANCE_TAKER = Decimal("0.001")   # can distinguish "used maker" from "used the static default"


class ResolveBacktestingTradeCostTest(unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        TradeFeeRegistry.set_rates("binance", {
            "BTC-USDT": MakerTakerExchangeFeeRates(
                maker=BINANCE_MAKER, taker=BINANCE_TAKER, maker_flat_fees=[], taker_flat_fees=[]),
        })

    def tearDown(self) -> None:
        TradeFeeRegistry.clear()
        super().tearDown()

    # -- OrderExecutorConfig: single-sided, resolved directly from execution_strategy --

    def _order_config(self, execution_strategy: ExecutionStrategy) -> OrderExecutorConfig:
        chaser_config = (LimitChaserConfig(distance=Decimal("0.001"), refresh_threshold=Decimal("0.002"))
                         if execution_strategy == ExecutionStrategy.LIMIT_CHASER else None)
        return OrderExecutorConfig(
            id="test", timestamp=1234567890, connector_name="binance", trading_pair="BTC-USDT",
            side=TradeType.BUY, amount=Decimal("1"), price=Decimal("50000"),
            chaser_config=chaser_config, execution_strategy=execution_strategy)

    def test_order_executor_limit_maker_uses_maker_rate(self):
        cost = _resolve_backtesting_trade_cost(self._order_config(ExecutionStrategy.LIMIT_MAKER))
        self.assertEqual(cost, float(BINANCE_MAKER))

    def test_order_executor_market_uses_taker_rate(self):
        cost = _resolve_backtesting_trade_cost(self._order_config(ExecutionStrategy.MARKET))
        self.assertEqual(cost, float(BINANCE_TAKER))

    def test_order_executor_limit_chaser_uses_taker_rate(self):
        cost = _resolve_backtesting_trade_cost(self._order_config(ExecutionStrategy.LIMIT_CHASER))
        self.assertEqual(cost, float(BINANCE_TAKER))

    def test_order_executor_plain_limit_uses_maker_rate(self):
        cost = _resolve_backtesting_trade_cost(self._order_config(ExecutionStrategy.LIMIT))
        self.assertEqual(cost, float(BINANCE_MAKER))

    # -- GridExecutorConfig: explicit order type for both entry and take-profit legs --

    def _grid_config(self, open_order_type: OrderType, take_profit_order_type: OrderType) -> GridExecutorConfig:
        return GridExecutorConfig(
            id="test", timestamp=1234567890, connector_name="binance", trading_pair="BTC-USDT",
            side=TradeType.BUY, start_price=Decimal("49000"), end_price=Decimal("51000"),
            limit_price=Decimal("49000"), total_amount_quote=Decimal("100"),
            triple_barrier_config=TripleBarrierConfig(
                open_order_type=open_order_type, take_profit_order_type=take_profit_order_type))

    def test_grid_executor_both_legs_limit_uses_pure_maker(self):
        cost = _resolve_backtesting_trade_cost(self._grid_config(OrderType.LIMIT, OrderType.LIMIT))
        self.assertEqual(cost, float(BINANCE_MAKER))

    def test_grid_executor_market_take_profit_averages_maker_and_taker(self):
        cost = _resolve_backtesting_trade_cost(self._grid_config(OrderType.LIMIT, OrderType.MARKET))
        self.assertEqual(cost, float((BINANCE_MAKER + BINANCE_TAKER) / 2))

    # -- PositionExecutorConfig: entry type known, exit type is path-dependent (proxied by taker) --

    def _position_config(self, open_order_type: OrderType) -> PositionExecutorConfig:
        return PositionExecutorConfig(
            id="test", timestamp=1234567890, connector_name="binance", trading_pair="BTC-USDT",
            side=TradeType.BUY, entry_price=Decimal("50000"), amount=Decimal("1"),
            triple_barrier_config=TripleBarrierConfig(open_order_type=open_order_type))

    def test_position_executor_limit_open_averages_maker_and_taker(self):
        cost = _resolve_backtesting_trade_cost(self._position_config(OrderType.LIMIT))
        self.assertEqual(cost, float((BINANCE_MAKER + BINANCE_TAKER) / 2))

    def test_position_executor_market_open_uses_pure_taker(self):
        cost = _resolve_backtesting_trade_cost(self._position_config(OrderType.MARKET))
        self.assertEqual(cost, float(BINANCE_TAKER))

    # -- DCAExecutorConfig: entry is always maker (taker mode isn't simulated) --

    def test_dca_executor_averages_maker_and_taker(self):
        config = DCAExecutorConfig(
            id="test", timestamp=1234567890, connector_name="binance", trading_pair="BTC-USDT",
            side=TradeType.BUY, amounts_quote=[Decimal("10")], prices=[Decimal("50000")])
        cost = _resolve_backtesting_trade_cost(config)
        self.assertEqual(cost, float((BINANCE_MAKER + BINANCE_TAKER) / 2))

    # -- Fallback and registry precedence --

    def test_unknown_connector_falls_back_to_the_default_trade_cost(self):
        config = self._order_config(ExecutionStrategy.MARKET)
        config.connector_name = "not_a_real_connector"
        self.assertEqual(_resolve_backtesting_trade_cost(config), _DEFAULT_TRADE_COST)

    def test_pair_without_a_registry_rate_falls_back_to_the_static_default_schema(self):
        # BTC-FDUSD has no entry in the registry (only BTC-USDT was seeded in setUp), so this
        # resolves through binance's static default schema (0.1%/0.1%), not the promo rate.
        config = OrderExecutorConfig(
            id="test", timestamp=1234567890, connector_name="binance", trading_pair="BTC-FDUSD",
            side=TradeType.BUY, amount=Decimal("1"), price=Decimal("1"),
            execution_strategy=ExecutionStrategy.LIMIT_MAKER)
        self.assertEqual(_resolve_backtesting_trade_cost(config), 0.001)


if __name__ == "__main__":
    unittest.main()
