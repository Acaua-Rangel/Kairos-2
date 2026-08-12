# -*- coding: utf-8 -*-

"""
unit tests for kairos.core.utils.estimate_fee
"""

import unittest
from decimal import Decimal

from kairos.client.config.fee_overrides_config_map import fee_overrides_config_map
from kairos.client.settings import AllConnectorSettings
from kairos.core.data_type.common import OrderType, TradeType
from kairos.core.data_type.trade_fee import DeductedFromReturnsTradeFee, MakerTakerExchangeFeeRates
from kairos.core.data_type.trade_fee_registry import TradeFeeRegistry
from kairos.core.utils.estimate_fee import build_trade_fee, estimate_fee, resolve_fee_percent


class EstimateFeeTest(unittest.TestCase):

    def tearDown(self) -> None:
        # TradeFeeRegistry and fee_overrides_config_map are process-global state.
        TradeFeeRegistry.clear()
        for key in ("binance_maker_percent_fee", "binance_taker_percent_fee"):
            fee_overrides_config_map[key].value = None
        # TradeFeeSchemaLoader._superimpose_overrides mutates AllConnectorSettings' schema object
        # in place and never restores it once an override value is cleared — undo that here so an
        # override test doesn't poison every test that runs after it in this process.
        schema = AllConnectorSettings.get_connector_settings()["binance"].trade_fee_schema
        schema.maker_percent_fee_decimal = Decimal("0.001")
        schema.taker_percent_fee_decimal = Decimal("0.001")
        super().tearDown()

    def test_estimate_fee(self):
        """
        test the estimate_fee function (deprecated passthrough to build_trade_fee)
        """
        self.assertEqual(estimate_fee("binance", True), DeductedFromReturnsTradeFee(percent=Decimal('0.001'), flat_fees=[]))
        self.assertEqual(estimate_fee("binance", False), DeductedFromReturnsTradeFee(percent=Decimal('0.001'), flat_fees=[]))

        # test against exchanges that do not exist in kairos.client.settings.CONNECTOR_SETTINGS
        self.assertRaisesRegex(Exception, "^Invalid connector", estimate_fee, "does_not_exist", True)
        self.assertRaisesRegex(Exception, "Invalid connector", estimate_fee, "does_not_exist", False)

    def test_resolve_fee_percent_uses_static_default_with_no_registry_data(self):
        self.assertEqual(resolve_fee_percent("binance", True, "BTC", "USDT"), Decimal("0.001"))
        self.assertEqual(resolve_fee_percent("binance", False, "BTC", "USDT"), Decimal("0.001"))

    def test_resolve_fee_percent_uses_registry_rate_for_a_known_pair(self):
        """A per-pair rate published by _update_trading_fees() (e.g. Binance's FDUSD 0% maker
        promo) overrides the static default for that pair only."""
        TradeFeeRegistry.set_rates("binance", {
            "BTC-FDUSD": MakerTakerExchangeFeeRates(
                maker=Decimal("0"), taker=Decimal("0.001"), maker_flat_fees=[], taker_flat_fees=[]),
        })

        self.assertEqual(resolve_fee_percent("binance", True, "BTC", "FDUSD"), Decimal("0"))
        self.assertEqual(resolve_fee_percent("binance", False, "BTC", "FDUSD"), Decimal("0.001"))
        # A pair with no registry entry is unaffected.
        self.assertEqual(resolve_fee_percent("binance", True, "BTC", "USDT"), Decimal("0.001"))

    def test_resolve_fee_percent_falls_back_to_default_without_base_or_quote(self):
        """Callers that don't know the pair (e.g. the deprecated estimate_fee()) can't consult the
        registry and always get the static default."""
        TradeFeeRegistry.set_rates("binance", {
            "BTC-FDUSD": MakerTakerExchangeFeeRates(
                maker=Decimal("0"), taker=Decimal("0.001"), maker_flat_fees=[], taker_flat_fees=[]),
        })
        self.assertEqual(resolve_fee_percent("binance", True, "", ""), Decimal("0.001"))

    def test_manual_override_takes_precedence_over_the_registry(self):
        TradeFeeRegistry.set_rates("binance", {
            "BTC-FDUSD": MakerTakerExchangeFeeRates(
                maker=Decimal("0"), taker=Decimal("0.001"), maker_flat_fees=[], taker_flat_fees=[]),
        })
        fee_overrides_config_map["binance_maker_percent_fee"].value = Decimal("0.075")  # 0.075%

        # The override (0.075%) wins over the registry's 0% for this pair.
        self.assertEqual(resolve_fee_percent("binance", True, "BTC", "FDUSD"), Decimal("0.00075"))
        # Taker wasn't overridden, so it still falls through to the registry.
        self.assertEqual(resolve_fee_percent("binance", False, "BTC", "FDUSD"), Decimal("0.001"))

    def test_build_trade_fee_limit_order_resolves_the_registry_rate(self):
        TradeFeeRegistry.set_rates("binance", {
            "BTC-FDUSD": MakerTakerExchangeFeeRates(
                maker=Decimal("0"), taker=Decimal("0.001"), maker_flat_fees=[], taker_flat_fees=[]),
        })
        fee = build_trade_fee("binance", True, "BTC", "FDUSD", OrderType.LIMIT, TradeType.BUY,
                              Decimal("1"), Decimal("50000"))
        self.assertEqual(fee.percent, Decimal("0"))
