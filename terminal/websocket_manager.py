# Kotak Trading Terminal - WebSocket Manager

import threading
import json
from typing import Optional, Dict, List, Callable, Any
from dataclasses import dataclass, field
from datetime import datetime
from collections import defaultdict

from terminal.auth_manager import AuthManager
from terminal.config import Config


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
        
        self._initialized = True
    
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
            
            # Determine message type
            msg_type = data.get("name", "")
            
            if msg_type == "sf":  # Stock feed
                self._handle_stock_feed(data)
            elif msg_type == "if":  # Index feed
                self._handle_index_feed(data)
            elif msg_type == "dp":  # Depth feed
                self._handle_depth_feed(data)
            elif "ordSt" in data or "nOrdNo" in data:  # Order feed
                self._handle_order_feed(data)
            else:
                # Generic price update
                self._handle_stock_feed(data)
                
        except Exception as e:
            print(f"WebSocket message error: {e}")
    
    def _on_error(self, error):
        """Handle WebSocket error"""
        print(f"WebSocket error: {error}")
        if self._on_connection_change:
            self._on_connection_change({"connected": False, "error": str(error)})
    
    def _on_open(self, message=None):
        """Handle WebSocket connection open"""
        self._is_connected = True
        if self._on_connection_change:
            self._on_connection_change({"connected": True, "message": "Connected"})
    
    def _on_close(self, message=None):
        """Handle WebSocket connection close"""
        self._is_connected = False
        if self._on_connection_change:
            self._on_connection_change({"connected": False, "message": "Disconnected"})
    
    def _handle_stock_feed(self, data: dict):
        """Process stock/derivative feed data"""
        token = str(data.get("tk", ""))
        exchange = data.get("e", "")
        key = f"{token}_{exchange}"
        
        if key not in self._market_data:
            self._market_data[key] = MarketData(
                instrument_token=token,
                exchange_segment=exchange
            )
        
        md = self._market_data[key]
        
        # Update fields from feed
        md.trading_symbol = data.get("ts", md.trading_symbol)
        md.ltp = float(data.get("ltp", md.ltp))
        md.last_traded_qty = int(data.get("ltq", md.last_traded_qty))
        md.volume = int(data.get("v", md.volume))
        md.open_price = float(data.get("op", md.open_price))
        md.high_price = float(data.get("h", md.high_price))
        md.low_price = float(data.get("lo", md.low_price))
        md.close_price = float(data.get("c", md.close_price))
        md.change = float(data.get("cng", md.change))
        md.change_percent = float(data.get("nc", md.change_percent))
        md.bid_price = float(data.get("bp", md.bid_price))
        md.ask_price = float(data.get("sp", md.ask_price))
        md.bid_qty = int(data.get("bq", md.bid_qty))
        md.ask_qty = int(data.get("sq", md.ask_qty))
        md.open_interest = int(data.get("oi", md.open_interest))
        md.total_buy_qty = int(data.get("tbq", md.total_buy_qty))
        md.total_sell_qty = int(data.get("tsq", md.total_sell_qty))
        md.lower_circuit = float(data.get("lcl", md.lower_circuit))
        md.upper_circuit = float(data.get("ucl", md.upper_circuit))
        md.week_52_high = float(data.get("yh", md.week_52_high))
        md.week_52_low = float(data.get("yl", md.week_52_low))
        md.last_update = datetime.now()
        
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
        """Process market depth data"""
        token = str(data.get("tk", ""))
        exchange = data.get("e", "")
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
                price=float(data.get(f"bp{suffix}", 0)),
                quantity=int(data.get(f"bq{suffix}", 0)),
                orders=int(data.get(f"bno{i+1}", 0))
            )
            depth.bids.append(bid)
        
        # Parse ask levels
        depth.asks = []
        for i in range(5):
            suffix = str(i+1) if i > 0 else ""
            ask = DepthLevel(
                price=float(data.get(f"sp{suffix}", 0)),
                quantity=int(data.get(f"bs{suffix}", 0)),
                orders=int(data.get(f"sno{i+1}", 0))
            )
            depth.asks.append(ask)
        
        if self._on_depth_update:
            self._on_depth_update(self._market_depth_to_dict(depth))
    
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
            # Set up callbacks
            client.on_message = self._on_message
            client.on_error = self._on_error
            client.on_open = self._on_open
            client.on_close = self._on_close
            
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
            
            return {
                "success": True,
                "subscribed_count": len(instrument_tokens),
                "message": f"Subscribed to {len(instrument_tokens)} instruments"
            }
        except Exception as e:
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
            client.subscribe_to_orderfeed()
            self._is_order_feed_connected = True
            return {"success": True, "message": "Subscribed to order feed"}
        except Exception as e:
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
