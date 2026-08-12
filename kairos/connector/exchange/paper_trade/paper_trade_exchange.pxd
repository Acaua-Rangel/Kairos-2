from libcpp.set cimport set as cpp_set
from libcpp.string cimport string
from libcpp.unordered_map cimport unordered_map
from libcpp.utility cimport pair

from kairos.core.data_type.LimitOrder cimport LimitOrder as CPPLimitOrder
from kairos.core.data_type.OrderExpirationEntry cimport OrderExpirationEntry as CPPOrderExpirationEntry
from kairos.core.data_type.order_book_tracker import OrderBookTracker
from kairos.connector.exchange_base cimport ExchangeBase


ctypedef cpp_set[CPPLimitOrder] SingleTradingPairLimitOrders
ctypedef unordered_map[string, SingleTradingPairLimitOrders].iterator LimitOrdersIterator
ctypedef pair[string, SingleTradingPairLimitOrders] LimitOrdersPair
ctypedef unordered_map[string, SingleTradingPairLimitOrders] LimitOrders
ctypedef cpp_set[CPPLimitOrder].iterator SingleTradingPairLimitOrdersIterator
ctypedef cpp_set[CPPLimitOrder].reverse_iterator SingleTradingPairLimitOrdersRIterator
ctypedef cpp_set[CPPOrderExpirationEntry] LimitOrderExpirationSet
ctypedef cpp_set[CPPOrderExpirationEntry].iterator LimitOrderExpirationSetIterator

cdef class QuantizationParams:
    cdef:
        str trading_pair
        int price_precision
        int price_decimals
        int order_size_precision
        int order_size_decimals


cdef class PaperTradeExchange(ExchangeBase):
    cdef:
        LimitOrders _bid_limit_orders
        LimitOrders _ask_limit_orders
        bint _paper_trade_market_initialized
        dict _trading_pairs
        object _queued_orders
        dict _quantization_params
        object _order_book_trade_listener
        object _market_order_filled_listener
        LimitOrderExpirationSet _limit_order_expiration_set
        object _target_market
        str _exchange_name
        str _fill_model
        dict _queue_volume_ahead
        dict _partial_fill_state
        set _crossing_orders
        double _order_latency
        double _market_order_delay
        object _pending_submissions
        dict _pending_cancels

    cdef c_execute_buy(self, str order_id, str trading_pair, object amount)
    cdef c_execute_sell(self, str order_id, str trading_pair, object amount)
    cdef dict c_fee_collaterals(self, object order_candidate)
    cdef c_deduct_fee_collaterals(self, dict fee_collaterals)
    cdef object c_volume_ahead_of(self, str trading_pair_str, bint is_buy, object price)
    cdef bint c_is_marketable(self, str trading_pair_str, bint is_buy, object price)
    cdef c_insert_limit_order(self,
                              str order_id,
                              str trading_pair_str,
                              bint is_buy,
                              object price,
                              object amount)
    cdef c_submit_limit_order(self,
                              str order_id,
                              str trading_pair_str,
                              bint is_buy,
                              object price,
                              object amount)
    cdef c_apply_cancel(self, str trading_pair_str, str client_order_id)
    cdef c_process_pending_actions(self, double timestamp)
    cdef object c_fill_from_queue(self,
                                  bint is_buy,
                                  LimitOrders *limit_orders_map_ptr,
                                  LimitOrdersIterator *map_it_ptr,
                                  SingleTradingPairLimitOrdersIterator orders_it,
                                  object trade_quantity)
    cdef c_update_filled_quantity(self,
                                  LimitOrdersIterator *map_it_ptr,
                                  SingleTradingPairLimitOrdersIterator orders_it,
                                  object filled_quantity)
    cdef c_process_market_orders(self)
    cdef c_set_balance(self, str currency, object amount)
    cdef object c_get_fee(self,
                          str base_asset,
                          str quote_asset,
                          object order_type,
                          object order_side,
                          object amount,
                          object price,
                          object is_maker=*)
    cdef c_delete_limit_order(self,
                              LimitOrders *limit_orders_map_ptr,
                              LimitOrdersIterator *map_it_ptr,
                              const SingleTradingPairLimitOrdersIterator orders_it)
    cdef c_process_limit_order(self,
                               bint is_buy,
                               LimitOrders *limit_orders_map_ptr,
                               LimitOrdersIterator *map_it_ptr,
                               SingleTradingPairLimitOrdersIterator orders_it,
                               object fill_quantity=*)
    cdef c_process_limit_bid_order(self,
                                   LimitOrders *limit_orders_map_ptr,
                                   LimitOrdersIterator *map_it_ptr,
                                   SingleTradingPairLimitOrdersIterator orders_it,
                                   object fill_quantity=*)
    cdef c_process_limit_ask_order(self,
                                   LimitOrders *limit_orders_map_ptr,
                                   LimitOrdersIterator *map_it_ptr,
                                   SingleTradingPairLimitOrdersIterator orders_it,
                                   object fill_quantity=*)
    cdef c_process_crossed_limit_orders_for_trading_pair(self,
                                                         bint is_buy,
                                                         LimitOrders *limit_orders_map_ptr,
                                                         LimitOrdersIterator *map_it_ptr)
    cdef c_process_crossed_limit_orders(self)
    cdef c_match_trade_to_limit_orders(self, object order_book_trade_event)
    cdef object c_cancel_order_from_orders_map(self,
                                               LimitOrders *orders_map,
                                               str trading_pair_str,
                                               bint cancel_all=*,
                                               str client_order_id=*)
