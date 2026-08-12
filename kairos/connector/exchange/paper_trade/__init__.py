from typing import List

from kairos.client.settings import AllConnectorSettings
from kairos.connector.exchange.paper_trade.paper_trade_exchange import PaperTradeExchange
from kairos.core.data_type.order_book_tracker import OrderBookTracker


def get_order_book_tracker(connector_name: str, trading_pairs: List[str]) -> OrderBookTracker:
    conn_setting = AllConnectorSettings.get_connector_settings()[connector_name]
    try:
        connector_instance = conn_setting.non_trading_connector_instance_with_default_configuration(
            trading_pairs=trading_pairs)
        return connector_instance.order_book_tracker
    except Exception as exception:
        raise Exception(f"Connector {connector_name} OrderBookTracker class not found ({exception})")


def create_paper_trade_market(exchange_name: str, trading_pairs: List[str]):
    # Imported here rather than at module level: the client config imports this package for the fill
    # model names, and config_helpers imports the client config back.
    from kairos.client.config.config_helpers import get_connector_class

    tracker = get_order_book_tracker(connector_name=exchange_name, trading_pairs=trading_pairs)
    return PaperTradeExchange(tracker,
                              get_connector_class(exchange_name),
                              exchange_name=exchange_name)
