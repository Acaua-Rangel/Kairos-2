"""Live maker/taker fee rates published by connectors, keyed by exchange and trading pair.

Connectors that can query their real fee rates (e.g. Binance's ``/sapi/v1/asset/tradeFee`` and
``/fapi/v1/commissionRate``) publish here from their ``_update_trading_fees()`` implementation —
already invoked on startup and periodically by ``ExchangePyBase._trading_fees_polling_loop``. This
gives ``build_trade_fee``/``build_perpetual_trade_fee`` (kairos/core/utils/estimate_fee.py) a
per-pair, real-rate source to check before falling back to the static ``TradeFeeSchema``.

A plain global registry (mirroring ``TradeFeeSchemaLoader``) is used instead of threading a
trading_pair through every fee-related signature, since ``build_trade_fee`` is a module-level
function called from Cython strategy code (kairos/strategy/*.pyx) with no connector instance in
hand — only the connector's name.
"""
from typing import Dict, Optional

from kairos.core.data_type.trade_fee import MakerTakerExchangeFeeRates


class TradeFeeRegistry:
    _rates: Dict[str, Dict[str, MakerTakerExchangeFeeRates]] = {}

    @classmethod
    def set_rates(cls, exchange_name: str, rates: Dict[str, MakerTakerExchangeFeeRates]) -> None:
        """Replace the full set of known rates for ``exchange_name`` (one refresh cycle's worth)."""
        cls._rates[exchange_name] = rates

    @classmethod
    def rates_for(cls, exchange_name: str, trading_pair: str) -> Optional[MakerTakerExchangeFeeRates]:
        return cls._rates.get(exchange_name, {}).get(trading_pair)

    @classmethod
    def clear(cls, exchange_name: Optional[str] = None) -> None:
        """Drop cached rates — for a single connector, or all of them (mainly for tests)."""
        if exchange_name is None:
            cls._rates.clear()
        else:
            cls._rates.pop(exchange_name, None)
