# Kotak Trading Terminal - Data Manager

import threading
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, field
from datetime import datetime

from terminal.auth_manager import AuthManager
from terminal.config import Config


@dataclass
class Position:
    """Represents a trading position"""
    trading_symbol: str
    exchange_segment: str
    product: str
    quantity: int
    buy_quantity: int = 0
    sell_quantity: int = 0
    buy_amount: float = 0.0
    sell_amount: float = 0.0
    cf_buy_qty: int = 0
    cf_sell_qty: int = 0
    cf_buy_amt: float = 0.0
    cf_sell_amt: float = 0.0
    ltp: float = 0.0
    multiplier: float = 1.0
    gen_num: float = 1.0
    gen_den: float = 1.0
    prc_num: float = 1.0
    prc_den: float = 1.0
    lot_size: int = 1
    precision: int = 2
    instrument_token: str = ""


@dataclass 
class Holding:
    """Represents a portfolio holding"""
    symbol: str
    trading_symbol: str
    exchange_segment: str
    quantity: int
    average_price: float
    holding_cost: float
    current_price: float
    market_value: float
    pnl: float = 0.0
    pnl_percent: float = 0.0
    instrument_token: str = ""
    sellable_quantity: int = 0


class DataManager:
    """
    Manages portfolio data - positions, holdings, P&L calculations.
    Implements P&L formulas from Kotak SDK documentation.
    """
    
    _instance: Optional['DataManager'] = None
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
        
        # Paper trading data
        self._paper_positions: Dict[str, Position] = {}
        self._paper_holdings: Dict[str, Holding] = {}
        
        # Cache for live data
        self._positions_cache: Optional[dict] = None
        self._holdings_cache: Optional[dict] = None
        self._limits_cache: Optional[dict] = None
        self._cache_timestamp: Optional[datetime] = None
        
        self._initialized = True
    
    # ===== P&L Calculation Methods (from Kotak docs) =====
    
    def calculate_position_pnl(self, position: Position) -> Dict[str, float]:
        """
        Calculate P&L for a position using Kotak SDK formulas.
        
        From Positions.md:
        - Total Buy Qty = (cfBuyQty + flBuyQty)
        - Total Sell Qty = (cfSellQty + flSellQty)
        - Net Qty = Total Buy Qty - Total Sell Qty
        - Total Buy Amt = (cfBuyAmt + buyAmt)
        - Total Sell Amt = (cfSellAmt + sellAmt)
        - PnL = (Total Sell Amt - Total Buy Amt) + (Net Qty * LTP * multiplier * (genNum/genDen) * (prcNum/prcDen))
        """
        total_buy_qty = position.cf_buy_qty + position.buy_quantity
        total_sell_qty = position.cf_sell_qty + position.sell_quantity
        net_qty = total_buy_qty - total_sell_qty
        
        total_buy_amt = position.cf_buy_amt + position.buy_amount
        total_sell_amt = position.cf_sell_amt + position.sell_amount
        
        # Price factor for derivatives
        price_factor = (
            position.multiplier * 
            (position.gen_num / position.gen_den) * 
            (position.prc_num / position.prc_den)
        )
        
        realized_pnl = total_sell_amt - total_buy_amt
        unrealized_pnl = net_qty * position.ltp * price_factor
        total_pnl = realized_pnl + unrealized_pnl
        
        # Calculate average prices
        if total_buy_qty > 0:
            buy_avg = total_buy_amt / (total_buy_qty * price_factor)
        else:
            buy_avg = 0.0
            
        if total_sell_qty > 0:
            sell_avg = total_sell_amt / (total_sell_qty * price_factor)
        else:
            sell_avg = 0.0
        
        # Determine position average price
        if total_buy_qty > total_sell_qty:
            avg_price = buy_avg
        elif total_buy_qty < total_sell_qty:
            avg_price = sell_avg
        else:
            avg_price = 0.0
        
        return {
            "total_buy_qty": total_buy_qty,
            "total_sell_qty": total_sell_qty,
            "net_qty": net_qty,
            "total_buy_amt": round(total_buy_amt, 2),
            "total_sell_amt": round(total_sell_amt, 2),
            "realized_pnl": round(realized_pnl, 2),
            "unrealized_pnl": round(unrealized_pnl, 2),
            "total_pnl": round(total_pnl, 2),
            "buy_avg_price": round(buy_avg, position.precision),
            "sell_avg_price": round(sell_avg, position.precision),
            "avg_price": round(avg_price, position.precision),
            "ltp": position.ltp
        }
    
    def calculate_holding_pnl(self, holding: Holding) -> Dict[str, float]:
        """Calculate P&L for a holding"""
        current_value = holding.quantity * holding.current_price
        pnl = current_value - holding.holding_cost
        pnl_percent = (pnl / holding.holding_cost * 100) if holding.holding_cost > 0 else 0.0
        
        return {
            "quantity": holding.quantity,
            "average_price": round(holding.average_price, 2),
            "current_price": round(holding.current_price, 2),
            "holding_cost": round(holding.holding_cost, 2),
            "current_value": round(current_value, 2),
            "pnl": round(pnl, 2),
            "pnl_percent": round(pnl_percent, 2)
        }
    
    # ===== Positions =====
    
    def get_positions(self) -> Dict[str, Any]:
        """Get all positions (paper or live)"""
        if Config.PAPER_TRADING:
            return self._get_paper_positions()
        else:
            return self._get_live_positions()
    
    def _get_paper_positions(self) -> Dict[str, Any]:
        """Get paper trading positions with P&L"""
        positions_data = []
        total_pnl = 0.0
        
        for key, position in self._paper_positions.items():
            pnl_data = self.calculate_position_pnl(position)
            positions_data.append({
                "trading_symbol": position.trading_symbol,
                "exchange_segment": position.exchange_segment,
                "product": position.product,
                "instrument_token": position.instrument_token,
                **pnl_data
            })
            total_pnl += pnl_data["total_pnl"]
        
        return {
            "success": True,
            "paper_mode": True,
            "data": positions_data,
            "summary": {
                "total_positions": len(positions_data),
                "total_pnl": round(total_pnl, 2)
            }
        }
    
    def _get_live_positions(self) -> Dict[str, Any]:
        """Get live positions from Kotak API with P&L calculations"""
        client = self._auth_manager.client
        
        if not client or not self._auth_manager.is_authenticated:
            return {"success": False, "error": "Not authenticated"}
        
        try:
            result = client.positions()
            
            if result.get("stat") == "ok" and result.get("data"):
                positions_data = []
                total_pnl = 0.0
                
                for pos in result["data"]:
                    # Parse position data from API response
                    position = Position(
                        trading_symbol=pos.get("trdSym", ""),
                        exchange_segment=pos.get("exSeg", ""),
                        product=pos.get("prod", ""),
                        quantity=int(pos.get("qty", 0)),
                        buy_quantity=int(pos.get("flBuyQty", 0)),
                        sell_quantity=int(pos.get("flSellQty", 0)),
                        buy_amount=float(pos.get("buyAmt", 0)),
                        sell_amount=float(pos.get("sellAmt", 0)),
                        cf_buy_qty=int(pos.get("cfBuyQty", 0)),
                        cf_sell_qty=int(pos.get("cfSellQty", 0)),
                        cf_buy_amt=float(pos.get("cfBuyAmt", 0)),
                        cf_sell_amt=float(pos.get("cfSellAmt", 0)),
                        ltp=float(pos.get("ltp", 0)),
                        multiplier=float(pos.get("multiplier", 1)),
                        gen_num=float(pos.get("genNum", 1)),
                        gen_den=float(pos.get("genDen", 1)),
                        prc_num=float(pos.get("prcNum", 1)),
                        prc_den=float(pos.get("prcDen", 1)),
                        lot_size=int(pos.get("lotSz", 1)),
                        precision=int(pos.get("precision", 2)),
                        instrument_token=pos.get("tok", "")
                    )
                    
                    pnl_data = self.calculate_position_pnl(position)
                    positions_data.append({
                        "trading_symbol": position.trading_symbol,
                        "exchange_segment": position.exchange_segment,
                        "product": position.product,
                        "instrument_token": position.instrument_token,
                        **pnl_data
                    })
                    total_pnl += pnl_data["total_pnl"]
                
                return {
                    "success": True,
                    "paper_mode": False,
                    "data": positions_data,
                    "summary": {
                        "total_positions": len(positions_data),
                        "total_pnl": round(total_pnl, 2)
                    }
                }
            
            return {"success": True, "paper_mode": False, "data": [], "summary": {"total_positions": 0, "total_pnl": 0}}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    # ===== Holdings =====
    
    def get_holdings(self) -> Dict[str, Any]:
        """Get portfolio holdings (paper or live)"""
        if Config.PAPER_TRADING:
            return self._get_paper_holdings()
        else:
            return self._get_live_holdings()
    
    def _get_paper_holdings(self) -> Dict[str, Any]:
        """Get paper holdings with P&L"""
        holdings_data = []
        total_investment = 0.0
        total_current_value = 0.0
        
        for key, holding in self._paper_holdings.items():
            pnl_data = self.calculate_holding_pnl(holding)
            holdings_data.append({
                "symbol": holding.symbol,
                "trading_symbol": holding.trading_symbol,
                "exchange_segment": holding.exchange_segment,
                "instrument_token": holding.instrument_token,
                "sellable_quantity": holding.sellable_quantity,
                **pnl_data
            })
            total_investment += holding.holding_cost
            total_current_value += pnl_data["current_value"]
        
        return {
            "success": True,
            "paper_mode": True,
            "data": holdings_data,
            "summary": {
                "total_holdings": len(holdings_data),
                "total_investment": round(total_investment, 2),
                "total_current_value": round(total_current_value, 2),
                "total_pnl": round(total_current_value - total_investment, 2)
            }
        }
    
    def _get_live_holdings(self) -> Dict[str, Any]:
        """Get live holdings from Kotak API"""
        client = self._auth_manager.client
        
        if not client or not self._auth_manager.is_authenticated:
            return {"success": False, "error": "Not authenticated"}
        
        try:
            result = client.holdings()
            
            if result.get("data"):
                holdings_data = []
                total_investment = 0.0
                total_current_value = 0.0
                
                for h in result["data"]:
                    holding = Holding(
                        symbol=h.get("displaySymbol", ""),
                        trading_symbol=h.get("symbol", ""),
                        exchange_segment=h.get("exchangeSegment", ""),
                        quantity=int(h.get("quantity", 0)),
                        average_price=float(h.get("averagePrice", 0)),
                        holding_cost=float(h.get("holdingCost", 0)),
                        current_price=float(h.get("closingPrice", 0)),
                        market_value=float(h.get("mktValue", 0)),
                        instrument_token=str(h.get("instrumentToken", "")),
                        sellable_quantity=int(h.get("sellableQuantity", 0))
                    )
                    
                    pnl_data = self.calculate_holding_pnl(holding)
                    holdings_data.append({
                        "symbol": holding.symbol,
                        "trading_symbol": holding.trading_symbol,
                        "exchange_segment": holding.exchange_segment,
                        "instrument_token": holding.instrument_token,
                        "sellable_quantity": holding.sellable_quantity,
                        **pnl_data
                    })
                    total_investment += holding.holding_cost
                    total_current_value += pnl_data["current_value"]
                
                return {
                    "success": True,
                    "paper_mode": False,
                    "data": holdings_data,
                    "summary": {
                        "total_holdings": len(holdings_data),
                        "total_investment": round(total_investment, 2),
                        "total_current_value": round(total_current_value, 2),
                        "total_pnl": round(total_current_value - total_investment, 2)
                    }
                }
            
            return {"success": True, "paper_mode": False, "data": [], "summary": {}}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    # ===== Limits =====
    
    def get_limits(self, segment: str = "ALL", exchange: str = "ALL", product: str = "ALL") -> Dict[str, Any]:
        """Get trading limits/funds"""
        if Config.PAPER_TRADING:
            # Return simulated limits for paper trading
            return {
                "success": True,
                "paper_mode": True,
                "data": {
                    "available_cash": 1000000.00,
                    "used_margin": 0.00,
                    "available_margin": 1000000.00,
                    "total_collateral": 0.00
                }
            }
        
        client = self._auth_manager.client
        
        if not client or not self._auth_manager.is_authenticated:
            return {"success": False, "error": "Not authenticated"}
        
        try:
            result = client.limits(segment=segment, exchange=exchange, product=product)
            return {"success": True, "paper_mode": False, "data": result}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    # ===== Margin =====
    
    def get_margin_required(
        self,
        exchange_segment: str,
        price: float,
        order_type: str,
        product: str,
        quantity: int,
        instrument_token: str,
        transaction_type: str
    ) -> Dict[str, Any]:
        """Calculate margin required for an order"""
        if Config.PAPER_TRADING:
            # Simplified margin calculation for paper trading
            margin = price * quantity
            if product in ["MIS", "INTRADAY"]:
                margin = margin * 0.2  # 5x leverage
            elif product == "NRML":
                margin = margin * 0.5  # 2x leverage
            
            return {
                "success": True,
                "paper_mode": True,
                "data": {
                    "required_margin": round(margin, 2),
                    "available_margin": 1000000.00,
                    "can_place_order": margin <= 1000000.00
                }
            }
        
        client = self._auth_manager.client
        
        if not client or not self._auth_manager.is_authenticated:
            return {"success": False, "error": "Not authenticated"}
        
        try:
            result = client.margin_required(
                exchange_segment=exchange_segment,
                price=str(price),
                order_type=order_type,
                product=product,
                quantity=str(quantity),
                instrument_token=instrument_token,
                transaction_type=transaction_type
            )
            return {"success": True, "paper_mode": False, "data": result}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    # ===== Dashboard Summary =====
    
    def get_dashboard_summary(self) -> Dict[str, Any]:
        """Get combined summary for dashboard"""
        positions = self.get_positions()
        holdings = self.get_holdings()
        limits = self.get_limits()
        
        pos_pnl = positions.get("summary", {}).get("total_pnl", 0) if positions.get("success") else 0
        hold_pnl = holdings.get("summary", {}).get("total_pnl", 0) if holdings.get("success") else 0
        
        return {
            "success": True,
            "paper_mode": Config.PAPER_TRADING,
            "data": {
                "positions_pnl": pos_pnl,
                "holdings_pnl": hold_pnl,
                "total_pnl": round(pos_pnl + hold_pnl, 2),
                "positions_count": positions.get("summary", {}).get("total_positions", 0),
                "holdings_count": holdings.get("summary", {}).get("total_holdings", 0),
                "available_margin": limits.get("data", {}).get("available_margin", 0) if limits.get("success") else 0
            }
        }
    
    # ===== Paper Trading Helpers =====
    
    def update_paper_position(self, trading_symbol: str, exchange_segment: str, 
                               product: str, quantity: int, price: float, 
                               transaction_type: str, instrument_token: str = "") -> None:
        """Update paper trading position after order fill"""
        key = f"{trading_symbol}_{exchange_segment}_{product}"
        
        if key not in self._paper_positions:
            self._paper_positions[key] = Position(
                trading_symbol=trading_symbol,
                exchange_segment=exchange_segment,
                product=product,
                quantity=0,
                instrument_token=instrument_token
            )
        
        position = self._paper_positions[key]
        amount = quantity * price
        
        if transaction_type == "B":
            position.buy_quantity += quantity
            position.buy_amount += amount
        else:
            position.sell_quantity += quantity
            position.sell_amount += amount
        
        position.quantity = position.buy_quantity - position.sell_quantity
        position.ltp = price
    
    def clear_paper_data(self) -> Dict[str, Any]:
        """Clear all paper trading data"""
        self._paper_positions.clear()
        self._paper_holdings.clear()
        return {"success": True, "message": "Paper trading data cleared"}
