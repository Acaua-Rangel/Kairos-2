import unittest
from decimal import Decimal

from kairos.core.data_type.trade_fee import MakerTakerExchangeFeeRates
from kairos.core.data_type.trade_fee_registry import TradeFeeRegistry


class TradeFeeRegistryTest(unittest.TestCase):
    def tearDown(self) -> None:
        TradeFeeRegistry.clear()
        super().tearDown()

    def test_rates_for_unknown_exchange_or_pair_returns_none(self):
        self.assertIsNone(TradeFeeRegistry.rates_for("binance", "BTC-USDT"))
        TradeFeeRegistry.set_rates("binance", {})
        self.assertIsNone(TradeFeeRegistry.rates_for("binance", "BTC-USDT"))

    def test_set_and_get_rates(self):
        rates = MakerTakerExchangeFeeRates(
            maker=Decimal("0"), taker=Decimal("0.001"), maker_flat_fees=[], taker_flat_fees=[])
        TradeFeeRegistry.set_rates("binance", {"BTC-FDUSD": rates})

        self.assertIs(TradeFeeRegistry.rates_for("binance", "BTC-FDUSD"), rates)
        self.assertIsNone(TradeFeeRegistry.rates_for("binance", "BTC-USDT"))

    def test_set_rates_replaces_the_full_set_for_that_exchange(self):
        first = MakerTakerExchangeFeeRates(
            maker=Decimal("0.001"), taker=Decimal("0.001"), maker_flat_fees=[], taker_flat_fees=[])
        second = MakerTakerExchangeFeeRates(
            maker=Decimal("0"), taker=Decimal("0.0004"), maker_flat_fees=[], taker_flat_fees=[])
        TradeFeeRegistry.set_rates("binance", {"BTC-USDT": first})
        TradeFeeRegistry.set_rates("binance", {"BTC-FDUSD": second})

        # BTC-USDT was in the first refresh but dropped in the second — a stale rate must not linger.
        self.assertIsNone(TradeFeeRegistry.rates_for("binance", "BTC-USDT"))
        self.assertIs(TradeFeeRegistry.rates_for("binance", "BTC-FDUSD"), second)

    def test_exchanges_are_isolated_from_each_other(self):
        spot_rates = MakerTakerExchangeFeeRates(
            maker=Decimal("0.001"), taker=Decimal("0.001"), maker_flat_fees=[], taker_flat_fees=[])
        perp_rates = MakerTakerExchangeFeeRates(
            maker=Decimal("0.0002"), taker=Decimal("0.0004"), maker_flat_fees=[], taker_flat_fees=[])
        TradeFeeRegistry.set_rates("binance", {"BTC-USDT": spot_rates})
        TradeFeeRegistry.set_rates("binance_perpetual", {"BTC-USDT": perp_rates})

        self.assertIs(TradeFeeRegistry.rates_for("binance", "BTC-USDT"), spot_rates)
        self.assertIs(TradeFeeRegistry.rates_for("binance_perpetual", "BTC-USDT"), perp_rates)

    def test_clear_single_exchange_leaves_others_untouched(self):
        rates = MakerTakerExchangeFeeRates(
            maker=Decimal("0"), taker=Decimal("0.001"), maker_flat_fees=[], taker_flat_fees=[])
        TradeFeeRegistry.set_rates("binance", {"BTC-USDT": rates})
        TradeFeeRegistry.set_rates("binance_perpetual", {"BTC-USDT": rates})

        TradeFeeRegistry.clear("binance")

        self.assertIsNone(TradeFeeRegistry.rates_for("binance", "BTC-USDT"))
        self.assertIs(TradeFeeRegistry.rates_for("binance_perpetual", "BTC-USDT"), rates)

    def test_clear_all(self):
        rates = MakerTakerExchangeFeeRates(
            maker=Decimal("0"), taker=Decimal("0.001"), maker_flat_fees=[], taker_flat_fees=[])
        TradeFeeRegistry.set_rates("binance", {"BTC-USDT": rates})
        TradeFeeRegistry.set_rates("binance_perpetual", {"BTC-USDT": rates})

        TradeFeeRegistry.clear()

        self.assertIsNone(TradeFeeRegistry.rates_for("binance", "BTC-USDT"))
        self.assertIsNone(TradeFeeRegistry.rates_for("binance_perpetual", "BTC-USDT"))


if __name__ == "__main__":
    unittest.main()
