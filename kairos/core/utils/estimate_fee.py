import warnings
from decimal import Decimal
from typing import List, Optional, Tuple

from kairos.client.config.trade_fee_schema_loader import TradeFeeSchemaLoader
from kairos.connector.utils import combine_to_hb_trading_pair
from kairos.core.data_type.common import OrderType, PositionAction, TradeType
from kairos.core.data_type.trade_fee import TokenAmount, TradeFeeBase, TradeFeeSchema
from kairos.core.data_type.trade_fee_registry import TradeFeeRegistry


def _resolve_fee_rate(
    exchange: str,
    is_maker: bool,
    base_currency: str,
    quote_currency: str,
    trade_fee_schema: TradeFeeSchema,
) -> Tuple[Decimal, List[TokenAmount]]:
    """Resolve the maker/taker percent + flat fees to charge, in priority order:

    1. a manual override in conf_fee_overrides.yml — already baked into `trade_fee_schema` by
       `TradeFeeSchemaLoader`, so this just means "skip the registry and use the schema value".
    2. a real per-pair rate published by the connector's `_update_trading_fees()`
       (see TradeFeeRegistry) — only consulted when both currencies are known.
    3. the exchange's static default schema (also `trade_fee_schema`, when neither of the above
       apply).
    """
    default_percent = (
        trade_fee_schema.maker_percent_fee_decimal if is_maker else trade_fee_schema.taker_percent_fee_decimal
    )
    default_fixed_fees = (trade_fee_schema.maker_fixed_fees if is_maker else trade_fee_schema.taker_fixed_fees).copy()

    if (base_currency and quote_currency
            and not TradeFeeSchemaLoader.has_percent_fee_override(exchange, is_maker)):
        trading_pair = combine_to_hb_trading_pair(base_currency, quote_currency)
        rates = TradeFeeRegistry.rates_for(exchange, trading_pair)
        if rates is not None:
            percent = rates.maker if is_maker else rates.taker
            fixed_fees = list(rates.maker_flat_fees if is_maker else rates.taker_flat_fees)
            return percent, fixed_fees

    return default_percent, default_fixed_fees


def resolve_fee_percent(
    exchange: str,
    is_maker: bool,
    base_currency: str = "",
    quote_currency: str = "",
) -> Decimal:
    """Just the maker/taker percent — same 3-layer precedence as `build_trade_fee`/
    `build_perpetual_trade_fee` (manual override > real per-pair rate > static default), without
    building a `TradeFeeBase`. Used where a caller needs the raw rate to price something itself
    (e.g. the backtester estimating a trade cost ahead of any fill).
    """
    trade_fee_schema = TradeFeeSchemaLoader.configured_schema_for_exchange(exchange_name=exchange)
    percent, _ = _resolve_fee_rate(exchange, is_maker, base_currency, quote_currency, trade_fee_schema)
    return percent


def build_trade_fee(
    exchange: str,
    is_maker: bool,
    base_currency: str,
    quote_currency: str,
    order_type: OrderType,
    order_side: TradeType,
    amount: Decimal,
    price: Decimal = Decimal("NaN"),
    extra_flat_fees: Optional[List[TokenAmount]] = None,
) -> TradeFeeBase:
    """
    WARNING: Do not use this method for order sizing. Use the `BudgetChecker` instead.

    Uses the exchange's `TradeFeeSchema` to build a `TradeFee`, given the trade parameters. When a
    real per-pair rate is available for (exchange, base_currency, quote_currency) — and the user
    hasn't manually overridden the fee in conf_fee_overrides.yml — that rate is used instead of the
    schema's static default (see `_resolve_fee_rate` / `TradeFeeRegistry`).
    """
    trade_fee_schema: TradeFeeSchema = TradeFeeSchemaLoader.configured_schema_for_exchange(exchange_name=exchange)
    fee_percent, fixed_fees = _resolve_fee_rate(exchange, is_maker, base_currency, quote_currency, trade_fee_schema)
    if extra_flat_fees is not None and len(extra_flat_fees) > 0:
        fixed_fees = fixed_fees + extra_flat_fees
    trade_fee: TradeFeeBase = TradeFeeBase.new_spot_fee(
        fee_schema=trade_fee_schema,
        trade_type=order_side,
        percent=fee_percent,
        percent_token=trade_fee_schema.percent_fee_token,
        flat_fees=fixed_fees
    )
    return trade_fee


def build_perpetual_trade_fee(
    exchange: str,
    is_maker: bool,
    position_action: PositionAction,
    base_currency: str,
    quote_currency: str,
    order_type: OrderType,
    order_side: TradeType,
    amount: Decimal,
    price: Decimal = Decimal("NaN"),
) -> TradeFeeBase:
    """
    WARNING: Do not use this method for order sizing. Use the `BudgetChecker` instead.

    Uses the exchange's `TradeFeeSchema` to build a `TradeFee`, given the trade parameters. See
    `build_trade_fee` for the per-pair rate resolution this also applies.
    """
    trade_fee_schema = TradeFeeSchemaLoader.configured_schema_for_exchange(exchange_name=exchange)
    percent, fixed_fees = _resolve_fee_rate(exchange, is_maker, base_currency, quote_currency, trade_fee_schema)
    trade_fee = TradeFeeBase.new_perpetual_fee(
        fee_schema=trade_fee_schema,
        position_action=position_action,
        percent=percent,
        percent_token=trade_fee_schema.percent_fee_token,
        flat_fees=fixed_fees)
    return trade_fee


def estimate_fee(exchange: str, is_maker: bool) -> TradeFeeBase:
    """
    WARNING: This method is deprecated and remains only for backward compatibility.
    Use `build_trade_fee` and `build_perpetual_trade_fee` instead.

    Estimate the fee of a transaction on any blockchain.
    exchange is the name of the exchange to query.
    is_maker if true look at fee from maker side, otherwise from taker side.
    """
    warnings.warn(
        "The 'estimate_fee' method is deprecated, use 'build_trade_fee' and 'build_perpetual_trade_fee' instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    trade_fee = build_trade_fee(
        exchange,
        is_maker,
        base_currency="",
        quote_currency="",
        order_type=OrderType.LIMIT,
        order_side=TradeType.BUY,
        amount=Decimal("0"),
        price=Decimal("0"),
    )
    return trade_fee
