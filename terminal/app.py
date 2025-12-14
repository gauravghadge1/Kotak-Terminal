# Kotak Trading Terminal - Flask Application

from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit
import os
import sys
from dotenv import load_dotenv

# Load environment variables from .env file in the same directory
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from terminal.config import Config
from terminal.auth_manager import AuthManager
from terminal.order_manager import OrderManager
from terminal.data_manager import DataManager
from terminal.websocket_manager import WebSocketManager

# Initialize Flask app

# Force restart 2
app = Flask(__name__, 
            static_folder='static',
            template_folder='templates')
app.config['SECRET_KEY'] = Config.SECRET_KEY

# Initialize SocketIO for real-time updates
# Use threading mode for background thread emission support
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Initialize managers
auth_manager = AuthManager()
order_manager = OrderManager()
data_manager = DataManager()
ws_manager = WebSocketManager()


# ===== WebSocket Callbacks for Real-time UI Updates =====

def on_price_update(data):
    """Broadcast price updates to connected clients"""
    print(f"[Flask] Emitting price_update: {data.get('instrument_token')} LTP={data.get('ltp')}")
    socketio.emit('price_update', data, namespace='/')

def on_depth_update(data):
    """Broadcast depth updates to connected clients"""
    socketio.emit('depth_update', data, namespace='/')

def on_order_update(data):
    """Broadcast order updates to connected clients"""
    socketio.emit('order_update', data, namespace='/')

def on_connection_change(data):
    """Broadcast connection status changes"""
    socketio.emit('connection_status', data, namespace='/')

# Set callbacks
ws_manager.set_callbacks(
    on_price_update=on_price_update,
    on_depth_update=on_depth_update,
    on_order_update=on_order_update,
    on_connection_change=on_connection_change
)


# ===== Page Routes =====

@app.route('/')
def index():
    """Main trading dashboard"""
    return render_template('index.html', 
                          paper_mode=Config.PAPER_TRADING,
                          config_status=Config.get_status())


# ===== API Routes - Authentication =====

@app.route('/api/auth/status')
def auth_status():
    """Get authentication status"""
    return jsonify({
        **auth_manager.get_session_info(),
        "config_valid": Config.validate()
    })

@app.route('/api/subscribe', methods=['POST'])
def subscribe():
    """Subscribe to market data"""
    try:
        data = request.json
        tokens_to_subscribe = []
        
        # Check for direct tokens list (preferred)
        if 'instrument_tokens' in data:
            tokens_to_subscribe = data['instrument_tokens']
            
        # Check for script names (legacy/frontend Search dependent)
        elif 'script_names' in data:
            full_names = data['script_names']
            print(f"[API] Subscribe request for names: {full_names}")
            for script_name in full_names:
                 if "(" in script_name and ")" in script_name:
                    parts = script_name.split("(")
                    token_part = parts[-1].replace(")", "").strip()
                    tokens_to_subscribe.append({"instrument_token": token_part, "exchange_segment": "nse_cm"})
        
        if not tokens_to_subscribe:
             return jsonify({"error": "No valid tokens or script names provided"}), 400

        # Subscribe
        print(f"[API] Subscribing to {len(tokens_to_subscribe)} tokens")
        result = ws_manager.subscribe(
            instrument_tokens=tokens_to_subscribe,
            is_index=data.get('is_index', False),
            is_depth=data.get('is_depth', False)
        )
        return jsonify(result)
        
    except Exception as e:
        print(f"[API] Subscribe error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/auth/login', methods=['POST'])
def login():
    """Login with TOTP"""
    data = request.json
    totp = data.get('totp')
    
    if not totp:
        return jsonify({"success": False, "error": "TOTP required"}), 400
    
    result = auth_manager.quick_login(totp)
    return jsonify(result)

@app.route('/api/auth/logout', methods=['POST'])
def logout():
    """Logout"""
    result = auth_manager.logout()
    return jsonify(result)


# ===== API Routes - Orders =====

@app.route('/api/orders', methods=['GET'])
def get_orders():
    """Get order book"""
    return jsonify(order_manager.get_order_book())

@app.route('/api/orders', methods=['POST'])
def place_order():
    """Place new order"""
    data = request.json
    
    result = order_manager.place_order(
        trading_symbol=data.get('trading_symbol'),
        exchange_segment=data.get('exchange_segment'),
        transaction_type=data.get('transaction_type'),
        order_type=data.get('order_type'),
        product=data.get('product'),
        quantity=int(data.get('quantity', 0)),
        price=float(data.get('price', 0)),
        trigger_price=float(data.get('trigger_price', 0)),
        disclosed_quantity=int(data.get('disclosed_quantity', 0)),
        validity=data.get('validity', 'DAY'),
        amo=data.get('amo', 'NO'),
        tag=data.get('tag', '')
    )
    
    # Update paper position if order placed in paper mode
    if result.get('success') and Config.PAPER_TRADING:
        order_data = result.get('data', {})
        if order_data.get('status') == 'complete':
            data_manager.update_paper_position(
                trading_symbol=data.get('trading_symbol'),
                exchange_segment=data.get('exchange_segment'),
                product=data.get('product'),
                quantity=int(data.get('quantity', 0)),
                price=float(data.get('price', 0)) or order_data.get('average_price', 0),
                transaction_type=data.get('transaction_type')
            )
    
    return jsonify(result)

@app.route('/api/orders/<order_id>', methods=['PUT'])
def modify_order(order_id):
    """Modify existing order"""
    data = request.json
    
    result = order_manager.modify_order(
        order_id=order_id,
        price=float(data['price']) if data.get('price') else None,
        quantity=int(data['quantity']) if data.get('quantity') else None,
        trigger_price=float(data['trigger_price']) if data.get('trigger_price') else None,
        validity=data.get('validity'),
        order_type=data.get('order_type'),
        disclosed_quantity=int(data['disclosed_quantity']) if data.get('disclosed_quantity') else None
    )
    
    return jsonify(result)

@app.route('/api/orders/<order_id>', methods=['DELETE'])
def cancel_order(order_id):
    """Cancel order"""
    result = order_manager.cancel_order(order_id)
    return jsonify(result)

@app.route('/api/trades')
def get_trades():
    """Get trade history"""
    order_id = request.args.get('order_id')
    return jsonify(order_manager.get_trade_history(order_id))


# ===== API Routes - Portfolio =====

@app.route('/api/positions')
def get_positions():
    """Get positions"""
    return jsonify(data_manager.get_positions())

@app.route('/api/holdings')
def get_holdings():
    """Get holdings"""
    return jsonify(data_manager.get_holdings())

@app.route('/api/limits')
def get_limits():
    """Get trading limits"""
    segment = request.args.get('segment', 'ALL')
    exchange = request.args.get('exchange', 'ALL')
    product = request.args.get('product', 'ALL')
    return jsonify(data_manager.get_limits(segment, exchange, product))

@app.route('/api/dashboard')
def get_dashboard():
    """Get dashboard summary"""
    return jsonify(data_manager.get_dashboard_summary())

@app.route('/api/margin', methods=['POST'])
def get_margin():
    """Calculate margin required"""
    data = request.json
    result = data_manager.get_margin_required(
        exchange_segment=data.get('exchange_segment'),
        price=float(data.get('price', 0)),
        order_type=data.get('order_type'),
        product=data.get('product'),
        quantity=int(data.get('quantity', 0)),
        instrument_token=data.get('instrument_token'),
        transaction_type=data.get('transaction_type')
    )
    return jsonify(result)


# ===== API Routes - Scrip Search =====

@app.route('/api/search')
def search_scrips():
    """Search for scrips by symbol"""
    query = request.args.get('q', '').strip().upper()
    exchange = request.args.get('exchange', 'nse_cm')
    
    if not query or len(query) < 2:
        return jsonify({"success": False, "error": "Query must be at least 2 characters"})
    
    client = auth_manager.client
    if not client or not auth_manager.is_authenticated:
        return jsonify({"success": False, "error": "Not authenticated"})
    
    try:
        result = client.search_scrip(
            exchange_segment=exchange,
            symbol=query,
            expiry="",
            option_type="",
            strike_price=""
        )
        
        # Parse and simplify results
        scrips = []
        for item in result if isinstance(result, list) else []:
            # Only include EQ (equity) group stocks
            if item.get('pGroup') == 'EQ':
                scrips.append({
                    'token': str(item.get('pSymbol', '')),
                    'symbol': item.get('pSymbolName', ''),
                    'trading_symbol': item.get('pTrdSymbol', ''),
                    'exchange': item.get('pExchSeg', exchange),
                    'description': item.get('pDesc', '')
                })
        
        return jsonify({"success": True, "data": scrips})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


# ===== API Routes - Live Data View (bypass paper mode) =====

@app.route('/api/live/orders')
def get_live_orders():
    """Get live order book directly from Kotak API"""
    client = auth_manager.client
    if not client or not auth_manager.is_authenticated:
        return jsonify({"success": False, "error": "Not authenticated. Please login first."})
    
    try:
        result = client.order_report()
        return jsonify({"success": True, "live": True, "data": result.get("data", [])})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/api/live/trades')
def get_live_trades():
    """Get live trade history directly from Kotak API"""
    client = auth_manager.client
    if not client or not auth_manager.is_authenticated:
        return jsonify({"success": False, "error": "Not authenticated. Please login first."})
    
    try:
        result = client.trade_report()
        return jsonify({"success": True, "live": True, "data": result.get("data", [])})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/api/live/positions')
def get_live_positions():
    """Get live positions directly from Kotak API"""
    client = auth_manager.client
    if not client or not auth_manager.is_authenticated:
        return jsonify({"success": False, "error": "Not authenticated. Please login first."})
    
    try:
        result = client.positions()
        return jsonify({"success": True, "live": True, "data": result.get("data", [])})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/api/live/holdings')
def get_live_holdings():
    """Get live holdings directly from Kotak API"""
    client = auth_manager.client
    if not client or not auth_manager.is_authenticated:
        return jsonify({"success": False, "error": "Not authenticated. Please login first."})
    
    try:
        result = client.holdings()
        return jsonify({"success": True, "live": True, "data": result.get("data", [])})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/api/live/dashboard')
def get_live_dashboard():
    """Get live dashboard summary directly from Kotak API"""
    client = auth_manager.client
    if not client or not auth_manager.is_authenticated:
        return jsonify({"success": False, "error": "Not authenticated. Please login first."})
    
    try:
        # Get live positions P&L
        positions_pnl = 0.0
        positions_count = 0
        positions_result = client.positions()
        if positions_result.get("data"):
            positions_count = len(positions_result["data"])
            for pos in positions_result["data"]:
                # Calculate P&L from position data
                cf_buy_amt = float(pos.get("cfBuyAmt", 0) or 0)
                cf_sell_amt = float(pos.get("cfSellAmt", 0) or 0)
                buy_amt = float(pos.get("buyAmt", 0) or 0)
                sell_amt = float(pos.get("sellAmt", 0) or 0)
                ltp = float(pos.get("ltp", 0) or 0)
                
                cf_buy_qty = int(pos.get("cfBuyQty", 0) or 0)
                cf_sell_qty = int(pos.get("cfSellQty", 0) or 0)
                fl_buy_qty = int(pos.get("flBuyQty", 0) or 0)
                fl_sell_qty = int(pos.get("flSellQty", 0) or 0)
                
                total_buy_amt = cf_buy_amt + buy_amt
                total_sell_amt = cf_sell_amt + sell_amt
                net_qty = (cf_buy_qty + fl_buy_qty) - (cf_sell_qty + fl_sell_qty)
                
                multiplier = float(pos.get("multiplier", 1) or 1)
                gen_num = float(pos.get("genNum", 1) or 1)
                gen_den = float(pos.get("genDen", 1) or 1)
                prc_num = float(pos.get("prcNum", 1) or 1)
                prc_den = float(pos.get("prcDen", 1) or 1)
                
                # P&L formula from Kotak docs
                unrealized = net_qty * ltp * multiplier * (gen_num / gen_den) * (prc_num / prc_den)
                realized = total_sell_amt - total_buy_amt
                total_pnl = realized + unrealized
                positions_pnl += total_pnl
        
        # Get live holdings P&L
        holdings_pnl = 0.0
        holdings_count = 0
        holdings_result = client.holdings()
        if holdings_result.get("data"):
            holdings_count = len(holdings_result["data"])
            for h in holdings_result["data"]:
                quantity = int(h.get("sellableQty", 0) or 0)
                avg_price = float(h.get("avgPrice", 0) or 0)
                ltp = float(h.get("ltp", 0) or 0)
                holdings_pnl += (ltp - avg_price) * quantity
        
        # Get live limits/margin
        available_margin = 0.0
        limits_result = client.limits(segment="ALL", exchange="ALL", product="ALL")
        if limits_result:
            # Parse limits response to get available margin
            if isinstance(limits_result, dict):
                available_margin = float(limits_result.get("availableMargin", 0) or 
                                        limits_result.get("Net", 0) or 
                                        limits_result.get("marginAvailable", 0) or 0)
        
        return jsonify({
            "success": True,
            "live": True,
            "data": {
                "positions_pnl": round(positions_pnl, 2),
                "holdings_pnl": round(holdings_pnl, 2),
                "total_pnl": round(positions_pnl + holdings_pnl, 2),
                "positions_count": positions_count,
                "holdings_count": holdings_count,
                "available_margin": round(available_margin, 2)
            }
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


# ===== API Routes - Market Data =====



@app.route('/api/unsubscribe', methods=['POST'])
def unsubscribe():
    """Unsubscribe from market data"""
    data = request.json
    result = ws_manager.unsubscribe(
        instrument_tokens=data.get('instrument_tokens', []),
        is_index=data.get('is_index', False),
        is_depth=data.get('is_depth', False)
    )
    return jsonify(result)

@app.route('/api/subscribe/orderfeed', methods=['POST'])
def subscribe_orderfeed():
    """Subscribe to order feed"""
    result = ws_manager.subscribe_order_feed()
    return jsonify(result)

@app.route('/api/market-data')
def get_market_data():
    """Get cached market data"""
    token = request.args.get('instrument_token')
    exchange = request.args.get('exchange_segment')
    
    if token and exchange:
        data = ws_manager.get_market_data(token, exchange)
        return jsonify({"success": True, "data": data})
    
    return jsonify(ws_manager.get_all_market_data())

@app.route('/api/market-depth')
def get_market_depth():
    """Get market depth"""
    token = request.args.get('instrument_token')
    exchange = request.args.get('exchange_segment')
    
    if not token or not exchange:
        return jsonify({"success": False, "error": "instrument_token and exchange_segment required"}), 400
    
    data = ws_manager.get_market_depth(token, exchange)
    return jsonify({"success": True, "data": data})

@app.route('/api/subscriptions')
def get_subscriptions():
    """Get current subscriptions"""
    return jsonify(ws_manager.get_subscriptions())


# ===== API Routes - Scrip Search =====

@app.route('/api/scrips/search')
def search_scrip():
    """Search for scrips"""
    if not auth_manager.is_authenticated:
        return jsonify({"success": False, "error": "Not authenticated"}), 401
    
    exchange = request.args.get('exchange_segment', 'nse_cm')
    symbol = request.args.get('symbol', '')
    expiry = request.args.get('expiry')
    option_type = request.args.get('option_type')
    strike = request.args.get('strike_price')
    
    try:
        result = auth_manager.client.search_scrip(
            exchange_segment=exchange,
            symbol=symbol,
            expiry=expiry,
            option_type=option_type,
            strike_price=strike
        )
        return jsonify({"success": True, "data": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


# ===== API Routes - Paper Trading Management =====

@app.route('/api/paper/clear', methods=['POST'])
def clear_paper_data():
    """Clear paper trading data"""
    order_manager.clear_paper_orders()
    data_manager.clear_paper_data()
    return jsonify({"success": True, "message": "Paper trading data cleared"})

@app.route('/api/mode')
def get_mode():
    """Get current trading mode"""
    return jsonify({
        "paper_mode": Config.PAPER_TRADING,
        "authenticated": auth_manager.is_authenticated
    })


# ===== SocketIO Events =====

@socketio.on('connect')
def handle_connect():
    """Handle client connection"""
    emit('connection_status', {'connected': True, 'paper_mode': Config.PAPER_TRADING})

@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection"""
    pass


# ===== Main Entry Point =====

def run_terminal(host=None, port=None, debug=None):
    """Run the trading terminal"""
    host = host or Config.HOST
    port = port or Config.PORT
    debug = debug if debug is not None else Config.DEBUG
    
    print(f"""
+==============================================================+
|           KOTAK TRADING TERMINAL v1.0                        |
+==============================================================+
|  Mode: {'PAPER TRADING' if Config.PAPER_TRADING else 'LIVE TRADING'}                                        |
|  URL:  http://{host}:{port}                                  |
+==============================================================+
    """)
    
    socketio.run(app, host=host, port=port, debug=debug, allow_unsafe_werkzeug=True)


if __name__ == '__main__':
    run_terminal()
