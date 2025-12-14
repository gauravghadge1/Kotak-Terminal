# Kotak Trading Terminal - Order Manager

import threading
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import uuid
import copy

from terminal.config import Config
from terminal.auth_manager import AuthManager


class OrderStatus(Enum):
    PENDING = "pending"
    OPEN = "open"
    COMPLETE = "complete"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    MODIFIED = "modified"


class TransactionType(Enum):
    BUY = "B"
    SELL = "S"


class OrderType(Enum):
    LIMIT = "L"
    MARKET = "MKT"
    STOP_LOSS = "SL"
    STOP_LOSS_MARKET = "SL-M"


class ProductType(Enum):
    NRML = "NRML"
    CNC = "CNC"
    MIS = "MIS"
    CO = "CO"
    BO = "BO"


@dataclass
class Order:
    """Represents a trading order"""
    order_id: str
    trading_symbol: str
    exchange_segment: str
    transaction_type: str
    order_type: str
    product: str
    quantity: int
    price: float
    trigger_price: float = 0.0
    disclosed_quantity: int = 0
    validity: str = "DAY"
    status: str = "pending"
    filled_quantity: int = 0
    average_price: float = 0.0
    order_time: datetime = field(default_factory=datetime.now)
    is_paper: bool = True
    rejection_reason: str = ""
    exchange_order_id: str = ""
    tag: str = ""


class OrderManager:
    """
    Manages order placement, modification, and cancellation.
    Supports both Paper Trading and Live Trading modes.
    """
    
    _instance: Optional['OrderManager'] = None
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
        self._paper_orders: Dict[str, Order] = {}  # Paper trading orders
        self._daily_pnl: float = 0.0
        self._initialized = True
    
    @property
    def is_paper_mode(self) -> bool:
        """Check if running in paper trading mode"""
        return Config.PAPER_TRADING
    
    def _generate_paper_order_id(self) -> str:
        """Generate a unique paper order ID"""
        return f"PAPER_{datetime.now().strftime('%y%m%d')}_{uuid.uuid4().hex[:8].upper()}"
    
    def _validate_order(self, order_params: dict) -> Dict[str, Any]:
        """
        Validate order parameters and risk limits.
        
        Returns:
            dict with 'valid' boolean and 'errors' list
        """
        errors = []
        
        # Check required fields
        required = ['trading_symbol', 'exchange_segment', 'transaction_type', 
                    'order_type', 'product', 'quantity']
        for field_name in required:
            if not order_params.get(field_name):
                errors.append(f"Missing required field: {field_name}")
        
        quantity = int(order_params.get('quantity', 0))
        price = float(order_params.get('price', 0))
        
        # Check max position size
        if quantity > Config.MAX_POSITION_SIZE:
            errors.append(f"Quantity {quantity} exceeds max position size {Config.MAX_POSITION_SIZE}")
        
        # Check max order value
        order_value = quantity * price
        if order_value > Config.MAX_ORDER_VALUE:
            errors.append(f"Order value {order_value} exceeds max {Config.MAX_ORDER_VALUE}")
        
        # Check daily loss limit
        if abs(self._daily_pnl) >= Config.MAX_DAILY_LOSS:
            errors.append(f"Daily loss limit of {Config.MAX_DAILY_LOSS} reached")
        
        return {"valid": len(errors) == 0, "errors": errors}
    
    def place_order(
        self,
        trading_symbol: str,
        exchange_segment: str,
        transaction_type: str,
        order_type: str,
        product: str,
        quantity: int,
        price: float = 0.0,
        trigger_price: float = 0.0,
        disclosed_quantity: int = 0,
        validity: str = "DAY",
        amo: str = "NO",
        tag: str = "",
        **kwargs
    ) -> Dict[str, Any]:
        """
        Place a new order (paper or live based on config).
        
        Args:
            trading_symbol: Trading symbol (e.g., 'RELIANCE-EQ')
            exchange_segment: Exchange segment (e.g., 'nse_cm')
            transaction_type: 'B' for buy, 'S' for sell
            order_type: 'L', 'MKT', 'SL', 'SL-M'
            product: 'NRML', 'CNC', 'MIS', 'CO', 'BO'
            quantity: Order quantity
            price: Limit price (required for L and SL orders)
            trigger_price: Trigger price for SL orders
            disclosed_quantity: Disclosed quantity
            validity: 'DAY', 'IOC', 'GTC'
            amo: After market order 'YES' or 'NO'
            tag: Custom order tag
            
        Returns:
            dict with order details or error
        """
        # Validate order
        validation = self._validate_order({
            'trading_symbol': trading_symbol,
            'exchange_segment': exchange_segment,
            'transaction_type': transaction_type,
            'order_type': order_type,
            'product': product,
            'quantity': quantity,
            'price': price
        })
        
        if not validation['valid']:
            return {
                "success": False,
                "error": "Order validation failed",
                "details": validation['errors']
            }
        
        if self.is_paper_mode:
            return self._place_paper_order(
                trading_symbol, exchange_segment, transaction_type,
                order_type, product, quantity, price, trigger_price,
                disclosed_quantity, validity, tag
            )
        else:
            return self._place_live_order(
                trading_symbol, exchange_segment, transaction_type,
                order_type, product, quantity, price, trigger_price,
                disclosed_quantity, validity, amo, tag, **kwargs
            )
    
    def _place_paper_order(
        self, trading_symbol: str, exchange_segment: str, transaction_type: str,
        order_type: str, product: str, quantity: int, price: float,
        trigger_price: float, disclosed_quantity: int, validity: str, tag: str
    ) -> Dict[str, Any]:
        """Place a paper (simulated) order"""
        order_id = self._generate_paper_order_id()
        
        # Simulate market order fill at current price (in real scenario, get LTP)
        fill_price = price if order_type == "L" else price  # TODO: Get LTP for market orders
        
        order = Order(
            order_id=order_id,
            trading_symbol=trading_symbol,
            exchange_segment=exchange_segment,
            transaction_type=transaction_type,
            order_type=order_type,
            product=product,
            quantity=quantity,
            price=price,
            trigger_price=trigger_price,
            disclosed_quantity=disclosed_quantity,
            validity=validity,
            status="complete" if order_type == "MKT" else "open",
            filled_quantity=quantity if order_type == "MKT" else 0,
            average_price=fill_price if order_type == "MKT" else 0,
            is_paper=True,
            tag=tag
        )
        
        self._paper_orders[order_id] = order
        
        return {
            "success": True,
            "paper_mode": True,
            "order_id": order_id,
            "status": order.status,
            "message": f"Paper order placed: {transaction_type} {quantity} {trading_symbol}",
            "data": self._order_to_dict(order)
        }
    
    def _place_live_order(
        self, trading_symbol: str, exchange_segment: str, transaction_type: str,
        order_type: str, product: str, quantity: int, price: float,
        trigger_price: float, disclosed_quantity: int, validity: str,
        amo: str, tag: str, **kwargs
    ) -> Dict[str, Any]:
        """Place a live order via Kotak API"""
        client = self._auth_manager.client
        
        if not client or not self._auth_manager.is_authenticated:
            return {"success": False, "error": "Not authenticated"}
        
        try:
            result = client.place_order(
                exchange_segment=exchange_segment,
                product=product,
                price=str(price),
                order_type=order_type,
                quantity=str(quantity),
                validity=validity,
                trading_symbol=trading_symbol,
                transaction_type=transaction_type,
                amo=amo,
                disclosed_quantity=str(disclosed_quantity),
                trigger_price=str(trigger_price),
                tag=tag,
                **kwargs
            )
            
            return {
                "success": True,
                "paper_mode": False,
                "data": result
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def modify_order(
        self,
        order_id: str,
        price: Optional[float] = None,
        quantity: Optional[int] = None,
        trigger_price: Optional[float] = None,
        validity: Optional[str] = None,
        order_type: Optional[str] = None,
        disclosed_quantity: Optional[int] = None
    ) -> Dict[str, Any]:
        """Modify an existing order"""
        if self.is_paper_mode:
            return self._modify_paper_order(
                order_id, price, quantity, trigger_price, validity, disclosed_quantity
            )
        else:
            return self._modify_live_order(
                order_id, price, quantity, trigger_price, validity, order_type, disclosed_quantity
            )
    
    def _modify_paper_order(
        self, order_id: str, price: Optional[float], quantity: Optional[int],
        trigger_price: Optional[float], validity: Optional[str], disclosed_quantity: Optional[int]
    ) -> Dict[str, Any]:
        """Modify a paper order"""
        if order_id not in self._paper_orders:
            return {"success": False, "error": f"Order {order_id} not found"}
        
        order = self._paper_orders[order_id]
        
        if order.status in ["complete", "cancelled", "rejected"]:
            return {"success": False, "error": f"Cannot modify order in {order.status} status"}
        
        if price is not None:
            order.price = price
        if quantity is not None:
            order.quantity = quantity
        if trigger_price is not None:
            order.trigger_price = trigger_price
        if validity is not None:
            order.validity = validity
        if disclosed_quantity is not None:
            order.disclosed_quantity = disclosed_quantity
        
        order.status = "modified"
        
        return {
            "success": True,
            "paper_mode": True,
            "message": f"Paper order {order_id} modified",
            "data": self._order_to_dict(order)
        }
    
    def _modify_live_order(
        self, order_id: str, price: Optional[float], quantity: Optional[int],
        trigger_price: Optional[float], validity: Optional[str],
        order_type: Optional[str], disclosed_quantity: Optional[int]
    ) -> Dict[str, Any]:
        """Modify a live order via Kotak API"""
        client = self._auth_manager.client
        
        if not client or not self._auth_manager.is_authenticated:
            return {"success": False, "error": "Not authenticated"}
        
        try:
            modify_params = {"order_id": order_id}
            if price is not None:
                modify_params["price"] = str(price)
            if quantity is not None:
                modify_params["quantity"] = str(quantity)
            if trigger_price is not None:
                modify_params["trigger_price"] = str(trigger_price)
            if validity is not None:
                modify_params["validity"] = validity
            if order_type is not None:
                modify_params["order_type"] = order_type
            if disclosed_quantity is not None:
                modify_params["disclosed_quantity"] = str(disclosed_quantity)
            
            result = client.modify_order(**modify_params)
            return {"success": True, "paper_mode": False, "data": result}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def cancel_order(self, order_id: str, amo: str = "NO") -> Dict[str, Any]:
        """Cancel an existing order"""
        if self.is_paper_mode:
            return self._cancel_paper_order(order_id)
        else:
            return self._cancel_live_order(order_id, amo)
    
    def _cancel_paper_order(self, order_id: str) -> Dict[str, Any]:
        """Cancel a paper order"""
        if order_id not in self._paper_orders:
            return {"success": False, "error": f"Order {order_id} not found"}
        
        order = self._paper_orders[order_id]
        
        if order.status in ["complete", "cancelled", "rejected"]:
            return {"success": False, "error": f"Cannot cancel order in {order.status} status"}
        
        order.status = "cancelled"
        
        return {
            "success": True,
            "paper_mode": True,
            "message": f"Paper order {order_id} cancelled",
            "data": self._order_to_dict(order)
        }
    
    def _cancel_live_order(self, order_id: str, amo: str) -> Dict[str, Any]:
        """Cancel a live order via Kotak API"""
        client = self._auth_manager.client
        
        if not client or not self._auth_manager.is_authenticated:
            return {"success": False, "error": "Not authenticated"}
        
        try:
            result = client.cancel_order(order_id=order_id, amo=amo)
            return {"success": True, "paper_mode": False, "data": result}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def get_order_book(self) -> Dict[str, Any]:
        """Get all orders (paper or live)"""
        if self.is_paper_mode:
            return self._get_paper_order_book()
        else:
            return self._get_live_order_book()
    
    def _get_paper_order_book(self) -> Dict[str, Any]:
        """Get paper order book"""
        orders = [self._order_to_dict(order) for order in self._paper_orders.values()]
        return {
            "success": True,
            "paper_mode": True,
            "data": sorted(orders, key=lambda x: x['order_time'], reverse=True)
        }
    
    def _get_live_order_book(self) -> Dict[str, Any]:
        """Get live order book via Kotak API"""
        client = self._auth_manager.client
        
        if not client or not self._auth_manager.is_authenticated:
            return {"success": False, "error": "Not authenticated"}
        
        try:
            result = client.order_report()
            return {"success": True, "paper_mode": False, "data": result}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def get_trade_history(self, order_id: Optional[str] = None) -> Dict[str, Any]:
        """Get trade history"""
        if self.is_paper_mode:
            # For paper mode, return completed orders as trades
            orders = [
                self._order_to_dict(o) 
                for o in self._paper_orders.values() 
                if o.status == "complete" and (order_id is None or o.order_id == order_id)
            ]
            return {"success": True, "paper_mode": True, "data": orders}
        else:
            client = self._auth_manager.client
            if not client or not self._auth_manager.is_authenticated:
                return {"success": False, "error": "Not authenticated"}
            
            try:
                result = client.trade_report(order_id=order_id)
                return {"success": True, "paper_mode": False, "data": result}
            except Exception as e:
                return {"success": False, "error": str(e)}
    
    def _order_to_dict(self, order: Order) -> dict:
        """Convert Order dataclass to dictionary"""
        return {
            "order_id": order.order_id,
            "trading_symbol": order.trading_symbol,
            "exchange_segment": order.exchange_segment,
            "transaction_type": order.transaction_type,
            "order_type": order.order_type,
            "product": order.product,
            "quantity": order.quantity,
            "price": order.price,
            "trigger_price": order.trigger_price,
            "disclosed_quantity": order.disclosed_quantity,
            "validity": order.validity,
            "status": order.status,
            "filled_quantity": order.filled_quantity,
            "average_price": order.average_price,
            "order_time": order.order_time.isoformat(),
            "is_paper": order.is_paper,
            "rejection_reason": order.rejection_reason,
            "tag": order.tag
        }
    
    def clear_paper_orders(self) -> Dict[str, Any]:
        """Clear all paper orders (reset)"""
        self._paper_orders.clear()
        self._daily_pnl = 0.0
        return {"success": True, "message": "Paper orders cleared"}
