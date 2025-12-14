# Kotak Trading Terminal - WebSocket Manager

import threading
import json
import time
from typing import Optional, Dict, List, Callable, Any
from dataclasses import dataclass, field
from datetime import datetime
from collections import defaultdict

from terminal.auth_manager import AuthManager
from terminal.config import Config

# Module-level load time - resets on hot reload
_MODULE_LOAD_TIME = time.time()
print(f"[WebSocket] Module loaded at {_MODULE_LOAD_TIME}")


@dataclass
class MarketData:
    """Real-time market data for an instrument"""
    instrument_token: str
    exchange_segment: str
    trading_symbol: str = ""
    ltp: float = 0.0
    last_traded_qty: int = 0
    volume: int = 0
    open_price: float = 0.0
    high_price: float = 0.0
    low_price: float = 0.0
    close_price: float = 0.0
    change: float = 0.0
    change_percent: float = 0.0
    bid_price: float = 0.0
    ask_price: float = 0.0
    bid_qty: int = 0
    ask_qty: int = 0
    open_interest: int = 0
    total_buy_qty: int = 0
    total_sell_qty: int = 0
    lower_circuit: float = 0.0
    upper_circuit: float = 0.0
    week_52_high: float = 0.0
    week_52_low: float = 0.0
    last_update: datetime = field(default_factory=datetime.now)


@dataclass
class DepthLevel:
    """Single level of market depth"""
    price: float = 0.0
    quantity: int = 0
    orders: int = 0


@dataclass
class MarketDepth:
    """Market depth (order book) data"""
    instrument_token: str
    exchange_segment: str
    trading_symbol: str = ""
    bids: List[DepthLevel] = field(default_factory=list)
    asks: List[DepthLevel] = field(default_factory=list)
    last_update: datetime = field(default_factory=datetime.now)


class WebSocketManager:
    """
    Manages WebSocket connections for real-time market data and order feeds.
    """
    
    _instance: Optional['WebSocketManager'] = None
    _lock = threading.Lock()
    
    def __new__(cls):
        """Singleton pattern"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._auth_manager = AuthManager()
        
        # Subscriptions
        self._subscribed_tokens: Dict[str, dict] = {}  # key -> {instrument_token, exchange_segment}
        self._depth_tokens: set = set()
        self._index_tokens: set = set()
        
        # Data storage
        self._market_data: Dict[str, MarketData] = {}
        self._market_depth: Dict[str, MarketDepth] = {}
        self._order_updates: List[dict] = []
        
        # Callbacks for UI updates
        self._on_price_update: Optional[Callable] = None
        self._on_depth_update: Optional[Callable] = None
        self._on_order_update: Optional[Callable] = None
        self._on_connection_change: Optional[Callable] = None
        
        # Connection state
        self._is_connected = False
        self._is_order_feed_connected = False
        self._sdk_callbacks_set = False
        
        self._initialized = True
    
    def _setup_sdk_callbacks(self):
        """Set up callbacks on the NeoAPI client - must be done BEFORE subscribing"""
        client = self._auth_manager.client
        if not client:
            return False
        
        if self._sdk_callbacks_set:
            return True
        
        # Set callbacks on the NeoAPI client
        # These are called by the SDK's internal __on_message, __on_error, etc.
        client.on_message = self._on_message
        client.on_error = self._on_error
        client.on_open = self._on_open
        client.on_close = self._on_close
        
        self._sdk_callbacks_set = True
        print("[WebSocket] SDK callbacks registered")
        return True
    
    @property
    def is_connected(self) -> bool:
        return self._is_connected
    
    @property
    def is_order_feed_connected(self) -> bool:
        return self._is_order_feed_connected
    
    # ===== Callback Registration =====
    
    def set_callbacks(
        self,
        on_price_update: Optional[Callable] = None,
        on_depth_update: Optional[Callable] = None,
        on_order_update: Optional[Callable] = None,
        on_connection_change: Optional[Callable] = None
    ):
        """Set callback functions for WebSocket events"""
        if on_price_update:
            self._on_price_update = on_price_update
        if on_depth_update:
            self._on_depth_update = on_depth_update
        if on_order_update:
            self._on_order_update = on_order_update
        if on_connection_change:
            self._on_connection_change = on_connection_change
    
    # ===== Internal WebSocket Handlers =====
    
    def _on_message(self, message):
        """Handle incoming WebSocket message"""
        try:
            if isinstance(message, str):
                data = json.loads(message)
            else:
                data = message
            
            # DEBUG: Log all incoming messages
            print(f"[WS MESSAGE] Received: {str(data)[:300]}")
            
            # Handle nested format from Kotak WebSocket: {'type': 'stock_feed', 'data': [...]}
            msg_type = data.get("type", "")
            if msg_type == "stock_feed" and "data" in data:
                # Process each item in the data array
                for item in data.get("data", []):
                    item_type = item.get("name", "")
                    if item_type == "sf":  # Stock feed
                        self._handle_stock_feed(item)
                    elif item_type == "if":  # Index feed
                        self._handle_index_feed(item)
                    elif item_type == "dp":  # Depth feed
                        self._handle_depth_feed(item)
                    elif "ordSt" in item or "nOrdNo" in item:  # Order feed
                        self._handle_order_feed(item)
                    else:
                        # Generic - treat as stock feed
                        self._handle_stock_feed(item)
                return
            
            # Handle flat/direct format (legacy support)
            item_type = data.get("name", "")
            if item_type == "sf":  # Stock feed
                self._handle_stock_feed(data)
            elif item_type == "if":  # Index feed
                self._handle_index_feed(data)
            elif item_type == "dp":  # Depth feed
                self._handle_depth_feed(data)
            elif "ordSt" in data or "nOrdNo" in data:  # Order feed
                self._handle_order_feed(data)
            else:
                # Generic price update
                self._handle_stock_feed(data)
                
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"WebSocket message error: {e}", flush=True)
    
    def _on_error(self, error):
        """Handle WebSocket error"""
        print(f"[WS ERROR] {error}")
        if self._on_connection_change:
            self._on_connection_change({"connected": False, "error": str(error)})
    
    def _on_open(self, message=None):
        """Handle WebSocket connection open"""
        print(f"[WS OPEN] WebSocket connected! Message: {message}")
        self._is_connected = True
        if self._on_connection_change:
            self._on_connection_change({"connected": True, "message": "Connected"})
    
    def _on_close(self, message=None):
        """Handle WebSocket connection close"""
        print(f"[WS CLOSE] WebSocket closed. Message: {message}")
        self._is_connected = False
        if self._on_connection_change:
            self._on_connection_change({"connected": False, "message": "Disconnected"})
    
    def _handle_stock_feed(self, data: dict):
        """Process stock/derivative feed data"""
        token = str(data.get("tk", ""))
        exchange = data.get("e", "")
        
        if not token or not exchange:
            return
            
        key = f"{token}_{exchange}"
        
        if key not in self._market_data:
            self._market_data[key] = MarketData(
                instrument_token=token,
                exchange_segment=exchange
            )
        
        md = self._market_data[key]
        
        # Update fields from feed
        md.trading_symbol = data.get("ts", md.trading_symbol)
        
        # Get LTP - may be explicit or calculated from bid/ask
        new_ltp = data.get("ltp")
        bp = data.get("bp")
        sp = data.get("sp")
        
        # DEBUG: Log what we found
        if bp or sp or new_ltp:
            print(f"[PRICE DEBUG] Token {token}: ltp={new_ltp}, bp={bp}, sp={sp}")
        
        if new_ltp:
            md.ltp = float(new_ltp)
        elif bp and sp:
            md.ltp = (float(bp) + float(sp)) / 2
        elif bp:
            md.ltp = float(bp)
        elif sp:
            md.ltp = float(sp)
        
        md.last_traded_qty = int(data.get("ltq", md.last_traded_qty) or 0)
        md.volume = int(data.get("v", md.volume) or 0)
        md.open_price = float(data.get("op", md.open_price) or 0)
        md.high_price = float(data.get("h", md.high_price) or 0)
        md.low_price = float(data.get("lo", md.low_price) or 0)
        md.close_price = float(data.get("c", md.close_price) or 0)
        md.change = float(data.get("cng", md.change) or 0)
        md.change_percent = float(data.get("nc", md.change_percent) or 0)
        md.bid_price = float(data.get("bp", md.bid_price) or 0)
        md.ask_price = float(data.get("sp", md.ask_price) or 0)
        md.bid_qty = int(data.get("bq", md.bid_qty) or 0)
        md.ask_qty = int(data.get("sq", md.ask_qty) or 0)
        md.open_interest = int(data.get("oi", md.open_interest) or 0)
        md.total_buy_qty = int(data.get("tbq", md.total_buy_qty) or 0)
        md.total_sell_qty = int(data.get("tsq", md.total_sell_qty) or 0)
        md.lower_circuit = float(data.get("lcl", md.lower_circuit) or 0)
        md.upper_circuit = float(data.get("ucl", md.upper_circuit) or 0)
        md.week_52_high = float(data.get("yh", md.week_52_high) or 0)
        md.week_52_low = float(data.get("yl", md.week_52_low) or 0)
        md.last_update = datetime.now()
        
        # Debug: Log price updates
        if md.ltp > 0:
            print(f"[WebSocket] Price update: {token} ({exchange}) = Rs.{md.ltp:.2f}")
        
        # Notify callback
        if self._on_price_update:
            self._on_price_update(self._market_data_to_dict(md))
    
    def _handle_index_feed(self, data: dict):
        """Process index feed data"""
        token = str(data.get("tk", ""))
        exchange = data.get("e", "nse_cm")
        key = f"{token}_{exchange}"
        
        if key not in self._market_data:
            self._market_data[key] = MarketData(
                instrument_token=token,
                exchange_segment=exchange
            )
        
        md = self._market_data[key]
        md.ltp = float(data.get("iv", md.ltp))
        md.close_price = float(data.get("ic", md.close_price))
        md.high_price = float(data.get("highPrice", md.high_price))
        md.low_price = float(data.get("lowPrice", md.low_price))
        md.open_price = float(data.get("openingPrice", md.open_price))
        md.change = float(data.get("cng", md.change))
        md.change_percent = float(data.get("nc", md.change_percent))
        md.last_update = datetime.now()
        
        if self._on_price_update:
            self._on_price_update(self._market_data_to_dict(md))
    
    def _handle_depth_feed(self, data: dict):
        """Process market depth data - also updates market prices from depth"""
        token = str(data.get("tk", ""))
        exchange = data.get("e", "")
        
        if not token or not exchange:
            return
            
        key = f"{token}_{exchange}"
        
        if key not in self._market_depth:
            self._market_depth[key] = MarketDepth(
                instrument_token=token,
                exchange_segment=exchange
            )
        
        depth = self._market_depth[key]
        depth.trading_symbol = data.get("ts", depth.trading_symbol)
        depth.last_update = datetime.now()
        
        # Parse bid levels
        depth.bids = []
        for i in range(5):
            suffix = str(i+1) if i > 0 else ""
            bid = DepthLevel(
                price=float(data.get(f"bp{suffix}", 0) or 0),
                quantity=int(data.get(f"bq{suffix}", 0) or 0),
                orders=int(data.get(f"bno{i+1}", 0) or 0)
            )
            depth.bids.append(bid)
        
        # Parse ask levels
        depth.asks = []
        for i in range(5):
            suffix = str(i+1) if i > 0 else ""
            ask = DepthLevel(
                price=float(data.get(f"sp{suffix}", 0) or 0),
                quantity=int(data.get(f"bs{suffix}", 0) or 0),
                orders=int(data.get(f"sno{i+1}", 0) or 0)
            )
            depth.asks.append(ask)
        
        if self._on_depth_update:
            self._on_depth_update(self._market_depth_to_dict(depth))
        
        # ALSO update market data LTP from depth prices
        # Get best bid/ask prices
        bp = data.get("bp")
        sp = data.get("sp")
        
        if bp or sp:
            # Update market data with price from depth
            if key not in self._market_data:
                self._market_data[key] = MarketData(
                    instrument_token=token,
                    exchange_segment=exchange
                )
            
            md = self._market_data[key]
            md.trading_symbol = data.get("ts", md.trading_symbol)
            
            # Calculate LTP from best bid/ask
            if bp and sp:
                md.ltp = (float(bp) + float(sp)) / 2
            elif bp:
                md.ltp = float(bp)
            elif sp:
                md.ltp = float(sp)
            
            md.bid_price = float(bp) if bp else md.bid_price
            md.ask_price = float(sp) if sp else md.ask_price
            
            # Lazy fetch close price if we don't have it
            # Debug: Show close_price value
            print(f"[DEBUG] Token {token}: close_price={md.close_price}, ltp={md.ltp}")
            need_fetch = (md.close_price < 1 and md.ltp > 0)
            print(f"[DEBUG] Token {token}: need_fetch={need_fetch}")
            if need_fetch:
                self._fetch_close_price_async(token, exchange, key)
            
            # Calculate change percent if we have close price
            if md.close_price and md.close_price > 0 and md.ltp > 0:
                md.change = md.ltp - md.close_price
                md.change_percent = ((md.ltp - md.close_price) / md.close_price) * 100
            
            md.last_update = datetime.now()
            
            # DEBUG: Log price updates from depth
            print(f"[DEPTH->PRICE] Token {token}: LTP=Rs.{md.ltp:.2f} Change={md.change_percent:.2f}%")
            
            # Emit price update
            if self._on_price_update:
                self._on_price_update(self._market_data_to_dict(md))
    
    def _fetch_close_price_async(self, token: str, exchange: str, key: str):
        """Fetch close price for a token if not already fetched"""
        # Check if we already have the close price
        md = self._market_data.get(key)
        if md and md.close_price > 0:
            return  # Already have close price
        
        # Initialize fetch attempts if needed
        if not hasattr(self, '_fetch_attempts'):
            self._fetch_attempts = {}
            
        current_module_time = _MODULE_LOAD_TIME
        now = time.time()
        
        # Get last attempt info: (timestamp, module_load_time)
        # If it was just a timestamp (old format), treat as old module time
        last_attempt_data = self._fetch_attempts.get(key)
        
        last_attempt_time = 0
        last_attempt_module = 0
        
        if isinstance(last_attempt_data, (tuple, list)):
            last_attempt_time, last_attempt_module = last_attempt_data
        else:
            last_attempt_time = last_attempt_data or 0
            
        print(f"[DEBUG-FETCH] Token={key} Module={current_module_time} LastMod={last_attempt_module} LastTime={last_attempt_time:.0f}")
        
        # If module reloaded, ignore previous attempts (force fetch)
        if last_attempt_module != current_module_time:
            print(f"[DEBUG-FETCH] Force fetch due to module reload")
            pass # Force fetch
        # Otherwise respect 60s cooldown
        elif now - last_attempt_time < 60:
            print(f"[DEBUG-FETCH] Rate limited: {now - last_attempt_time:.0f}s < 60s")
            return
            
        # Record attempt with current module time
        self._fetch_attempts[key] = (now, current_module_time)
        print(f"[Quotes] Starting fetch thread for {key}...")
        
        # Fetch in background to not block
        import threading
        def fetch():
            try:
                client = self._auth_manager.client
                if not client or not self._auth_manager.is_authenticated:
                    return
                
                instrument_tokens = [{"instrument_token": token, "exchange_segment": exchange}]
                print(f"[Quotes] Fetching close price for {token}...")
                
                result = client.quotes(instrument_tokens=instrument_tokens, quote_type="ohlc")
                print(f"[Quotes] Raw result for {token}: {str(result)[:300]}")
                
                # Try to parse result
                quotes = []
                if isinstance(result, list):
                    quotes = result
                elif isinstance(result, dict):
                    quotes = result.get('data', []) if isinstance(result.get('data'), list) else []
                
                for quote in quotes:
                    # Handle nested OHLC object from API
                    ohlc = quote.get('ohlc', {})
                    if not isinstance(ohlc, dict):
                        ohlc = {}
                        
                    # Try different field names based on API response format
                    # Priority: ohlc.close -> quote.pClose -> quote.close -> quote.c
                    close = float(ohlc.get('close') or quote.get('pClose') or quote.get('close') or quote.get('c') or 0)
                    open_p = float(ohlc.get('open') or quote.get('pOpen') or quote.get('open') or quote.get('o') or 0)
                    high = float(ohlc.get('high') or quote.get('pHigh') or quote.get('high') or quote.get('h') or 0)
                    low = float(ohlc.get('low') or quote.get('pLow') or quote.get('low') or quote.get('l') or 0)
                    
                    if close > 0 and key in self._market_data:
                        md = self._market_data[key]
                        md.close_price = close
                        md.open_price = open_p if open_p > 0 else md.open_price
                        md.high_price = high if high > 0 else md.high_price
                        md.low_price = low if low > 0 else md.low_price
                        print(f"[Quotes] Token {token}: Close={close}")
                        
                        # Recalculate change with new close price
                        if md.ltp > 0:
                            md.change = md.ltp - md.close_price
                            md.change_percent = ((md.ltp - md.close_price) / md.close_price) * 100
                            # Emit updated price
                            if self._on_price_update:
                                self._on_price_update(self._market_data_to_dict(md))
                        break
                        
            except Exception as e:
                print(f"[Quotes] Error fetching: {e}")
        
        threading.Thread(target=fetch, daemon=True).start()
    
    def _handle_order_feed(self, data: dict):
        """Process order update feed"""
        order_update = {
            "order_id": data.get("nOrdNo", ""),
            "status": data.get("ordSt", ""),
            "trading_symbol": data.get("trdSym", ""),
            "quantity": int(data.get("qty", 0)),
            "filled_quantity": int(data.get("fldQty", 0)),
            "price": float(data.get("prc", 0)),
            "transaction_type": data.get("trnsTp", ""),
            "exchange_segment": data.get("exSeg", ""),
            "rejection_reason": data.get("rejRsn", ""),
            "timestamp": datetime.now().isoformat()
        }
        
        self._order_updates.append(order_update)
        
        # Keep only last 100 updates
        if len(self._order_updates) > 100:
            self._order_updates = self._order_updates[-100:]
        
        if self._on_order_update:
            self._on_order_update(order_update)
    
    # ===== Subscription Methods =====
    
    def subscribe(
        self,
        instrument_tokens: List[Dict[str, str]],
        is_index: bool = False,
        is_depth: bool = False
    ) -> Dict[str, Any]:
        """
        Subscribe to market data for instruments.
        
        Args:
            instrument_tokens: List of {instrument_token, exchange_segment}
            is_index: True for index subscriptions
            is_depth: True to include market depth
            
        Returns:
            dict with success status
        """
        client = self._auth_manager.client
        
        if not client or not self._auth_manager.is_authenticated:
            return {"success": False, "error": "Not authenticated"}
        
        try:
            # Set up SDK callbacks BEFORE subscribing
            self._setup_sdk_callbacks()
            
            print(f"[WebSocket] Subscribing to {len(instrument_tokens)} instruments: {instrument_tokens}")
            
            # Subscribe
            client.subscribe(
                instrument_tokens=instrument_tokens,
                isIndex=is_index,
                isDepth=is_depth
            )
            
            # Track subscriptions
            for token_info in instrument_tokens:
                key = f"{token_info['instrument_token']}_{token_info['exchange_segment']}"
                self._subscribed_tokens[key] = token_info
                if is_depth:
                    self._depth_tokens.add(key)
                if is_index:
                    self._index_tokens.add(key)
            
            # Fetch initial quotes to get close price for change calculation
            try:
                print(f"[Quotes] Fetching quotes for {len(instrument_tokens)} instruments...")
                quotes_result = client.quotes(
                    instrument_tokens=instrument_tokens,
                    quote_type="ohlc"
                )
                print(f"[Quotes] Raw response type: {type(quotes_result)}")
                print(f"[Quotes] Raw response: {str(quotes_result)[:500]}")
                
                if isinstance(quotes_result, list):
                    for quote in quotes_result:
                        token = str(quote.get('pSymbol', ''))
                        exchange = quote.get('pExchSeg', '')
                        key = f"{token}_{exchange}"
                        
                        if key not in self._market_data:
                            self._market_data[key] = MarketData(
                                instrument_token=token,
                                exchange_segment=exchange
                            )
                        
                        md = self._market_data[key]
                        md.close_price = float(quote.get('pClose', 0) or 0)
                        md.open_price = float(quote.get('pOpen', 0) or 0)
                        md.high_price = float(quote.get('pHigh', 0) or 0)
                        md.low_price = float(quote.get('pLow', 0) or 0)
                        print(f"[Quotes] Token {token}: Close={md.close_price}")
                elif isinstance(quotes_result, dict):
                    # Maybe it's a dict with 'data' key
                    data = quotes_result.get('data', [])
                    print(f"[Quotes] Dict format, data length: {len(data) if isinstance(data, list) else 'N/A'}")
                    for quote in data if isinstance(data, list) else []:
                        token = str(quote.get('pSymbol', quote.get('instrument_token', '')))
                        exchange = quote.get('pExchSeg', quote.get('exchange_segment', ''))
                        key = f"{token}_{exchange}"
                        
                        if key not in self._market_data:
                            self._market_data[key] = MarketData(
                                instrument_token=token,
                                exchange_segment=exchange
                            )
                        
                        md = self._market_data[key]
                        # Try different field names
                        md.close_price = float(quote.get('pClose', quote.get('close', quote.get('c', 0))) or 0)
                        md.open_price = float(quote.get('pOpen', quote.get('open', quote.get('o', 0))) or 0)
                        md.high_price = float(quote.get('pHigh', quote.get('high', quote.get('h', 0))) or 0)
                        md.low_price = float(quote.get('pLow', quote.get('low', quote.get('l', 0))) or 0)
                        print(f"[Quotes] Token {token}: Close={md.close_price}")
            except Exception as qe:
                print(f"[Quotes] Error fetching quotes: {qe}")
            
            return {
                "success": True,
                "subscribed_count": len(instrument_tokens),
                "message": f"Subscribed to {len(instrument_tokens)} instruments"
            }
        except Exception as e:
            print(f"[WebSocket] Subscribe error: {e}")
            return {"success": False, "error": str(e)}
    
    def unsubscribe(
        self,
        instrument_tokens: List[Dict[str, str]],
        is_index: bool = False,
        is_depth: bool = False
    ) -> Dict[str, Any]:
        """Unsubscribe from market data"""
        client = self._auth_manager.client
        
        if not client or not self._auth_manager.is_authenticated:
            return {"success": False, "error": "Not authenticated"}
        
        try:
            client.un_subscribe(
                instrument_tokens=instrument_tokens,
                isIndex=is_index,
                isDepth=is_depth
            )
            
            # Remove from tracking
            for token_info in instrument_tokens:
                key = f"{token_info['instrument_token']}_{token_info['exchange_segment']}"
                self._subscribed_tokens.pop(key, None)
                self._depth_tokens.discard(key)
                self._index_tokens.discard(key)
                self._market_data.pop(key, None)
                self._market_depth.pop(key, None)
            
            return {"success": True, "message": f"Unsubscribed from {len(instrument_tokens)} instruments"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def subscribe_order_feed(self) -> Dict[str, Any]:
        """Subscribe to order updates feed"""
        client = self._auth_manager.client
        
        if not client or not self._auth_manager.is_authenticated:
            return {"success": False, "error": "Not authenticated"}
        
        try:
            # Set up SDK callbacks BEFORE subscribing
            self._setup_sdk_callbacks()
            
            client.subscribe_to_orderfeed()
            self._is_order_feed_connected = True
            print("[WebSocket] Subscribed to order feed")
            return {"success": True, "message": "Subscribed to order feed"}
        except Exception as e:
            print(f"[WebSocket] Order feed subscribe error: {e}")
            return {"success": False, "error": str(e)}
    
    # ===== Data Access Methods =====
    
    def get_market_data(self, instrument_token: str, exchange_segment: str) -> Optional[Dict[str, Any]]:
        """Get cached market data for an instrument"""
        key = f"{instrument_token}_{exchange_segment}"
        md = self._market_data.get(key)
        return self._market_data_to_dict(md) if md else None
    
    def get_all_market_data(self) -> Dict[str, Any]:
        """Get all cached market data"""
        return {
            "success": True,
            "data": [self._market_data_to_dict(md) for md in self._market_data.values()]
        }
    
    def get_market_depth(self, instrument_token: str, exchange_segment: str) -> Optional[Dict[str, Any]]:
        """Get cached market depth for an instrument"""
        key = f"{instrument_token}_{exchange_segment}"
        depth = self._market_depth.get(key)
        return self._market_depth_to_dict(depth) if depth else None
    
    def get_order_updates(self, limit: int = 20) -> List[dict]:
        """Get recent order updates"""
        return self._order_updates[-limit:]
    
    def get_subscriptions(self) -> Dict[str, Any]:
        """Get current subscriptions"""
        return {
            "success": True,
            "subscribed_tokens": list(self._subscribed_tokens.values()),
            "depth_tokens": list(self._depth_tokens),
            "index_tokens": list(self._index_tokens),
            "is_connected": self._is_connected,
            "is_order_feed_connected": self._is_order_feed_connected
        }
    
    # ===== Helper Methods =====
    
    def _market_data_to_dict(self, md: MarketData) -> dict:
        """Convert MarketData to dictionary"""
        return {
            "instrument_token": md.instrument_token,
            "exchange_segment": md.exchange_segment,
            "trading_symbol": md.trading_symbol,
            "ltp": md.ltp,
            "last_traded_qty": md.last_traded_qty,
            "volume": md.volume,
            "open": md.open_price,
            "high": md.high_price,
            "low": md.low_price,
            "close": md.close_price,
            "change": md.change,
            "change_percent": md.change_percent,
            "bid_price": md.bid_price,
            "ask_price": md.ask_price,
            "bid_qty": md.bid_qty,
            "ask_qty": md.ask_qty,
            "open_interest": md.open_interest,
            "total_buy_qty": md.total_buy_qty,
            "total_sell_qty": md.total_sell_qty,
            "lower_circuit": md.lower_circuit,
            "upper_circuit": md.upper_circuit,
            "week_52_high": md.week_52_high,
            "week_52_low": md.week_52_low,
            "last_update": md.last_update.isoformat()
        }
    
    def _market_depth_to_dict(self, depth: MarketDepth) -> dict:
        """Convert MarketDepth to dictionary"""
        return {
            "instrument_token": depth.instrument_token,
            "exchange_segment": depth.exchange_segment,
            "trading_symbol": depth.trading_symbol,
            "bids": [{"price": b.price, "quantity": b.quantity, "orders": b.orders} for b in depth.bids],
            "asks": [{"price": a.price, "quantity": a.quantity, "orders": a.orders} for a in depth.asks],
            "last_update": depth.last_update.isoformat()
        }
