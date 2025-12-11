// Kotak Trading Terminal - Frontend JavaScript

// ===== State =====
const state = {
    authenticated: false,
    paperMode: true,
    liveViewMode: false,  // Toggle to view live data while in paper mode
    wsConnected: false,
    selectedSymbol: null,
    watchlist: [],
    orders: [],
    positions: [],
    holdings: [],
    trades: [],
    transactionType: 'B'
};

// ===== Socket.IO Connection =====
const socket = io();

socket.on('connect', () => {
    console.log('Socket connected');
    updateConnectionStatus(true);
});

socket.on('disconnect', () => {
    console.log('Socket disconnected');
    updateConnectionStatus(false);
});

socket.on('price_update', (data) => {
    updateWatchlistPrice(data);
    if (state.selectedSymbol === `${data.instrument_token}_${data.exchange_segment}`) {
        updatePriceInfo(data);
    }
});

socket.on('depth_update', (data) => {
    if (state.selectedSymbol === `${data.instrument_token}_${data.exchange_segment}`) {
        updateMarketDepth(data);
    }
});

socket.on('order_update', (data) => {
    showToast(`Order ${data.order_id}: ${data.status}`, data.status === 'complete' ? 'success' : 'info');
    refreshOrders();
    refreshPositions();
});

socket.on('connection_status', (data) => {
    state.paperMode = data.paper_mode;
    updateTradingMode();
});

// ===== API Helpers =====
async function api(url, options = {}) {
    const response = await fetch(url, {
        ...options,
        headers: {
            'Content-Type': 'application/json',
            ...options.headers
        }
    });
    return response.json();
}

// ===== UI Updates =====
function updateConnectionStatus(connected) {
    state.wsConnected = connected;
    const statusEl = document.getElementById('ws-status');
    const dot = statusEl.querySelector('.status-dot');
    const text = statusEl.querySelector('span:last-child');

    if (connected) {
        dot.classList.remove('disconnected');
        dot.classList.add('connected');
        text.textContent = 'Connected';
    } else {
        dot.classList.remove('connected');
        dot.classList.add('disconnected');
        text.textContent = 'Disconnected';
    }
}

function updateTradingMode() {
    const modeEl = document.getElementById('trading-mode');

    // If viewing live data, don't override the live view state
    if (state.liveViewMode) {
        modeEl.textContent = 'VIEWING LIVE';
        modeEl.classList.add('viewing-live');
        modeEl.classList.remove('paper', 'live');
        return;
    }

    if (state.paperMode) {
        modeEl.textContent = 'PAPER';
        modeEl.classList.remove('live', 'viewing-live');
        modeEl.classList.add('paper');
    } else {
        modeEl.textContent = 'LIVE';
        modeEl.classList.remove('paper', 'viewing-live');
        modeEl.classList.add('live');
    }
}

function updateDashboard(data) {
    // Update P&L
    const pnlEl = document.getElementById('day-pnl');
    const pnl = data.total_pnl || 0;
    pnlEl.textContent = `${pnl >= 0 ? '+' : ''}₹${pnl.toFixed(2)}`;
    pnlEl.classList.remove('positive', 'negative');
    pnlEl.classList.add(pnl >= 0 ? 'positive' : 'negative');

    // Update positions count
    document.getElementById('positions-count').textContent = data.positions_count || 0;

    // Update available margin
    const margin = data.available_margin || 0;
    document.getElementById('available-margin').textContent = `₹${margin.toLocaleString()}`;
}

function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    container.appendChild(toast);

    setTimeout(() => toast.remove(), 4000);
}

// ===== Live View Toggle =====
function setupLiveViewToggle() {
    const toggleBtn = document.getElementById('live-toggle-btn');

    toggleBtn.addEventListener('click', () => {
        if (!state.authenticated) {
            showToast('Please login first to view live data', 'error');
            return;
        }

        state.liveViewMode = !state.liveViewMode;
        updateLiveViewMode();

        // Refresh all data with the new view mode
        refreshAll();

        if (state.liveViewMode) {
            showToast('Now viewing LIVE data from Kotak API', 'error');
        } else {
            showToast('Switched back to Paper Trading view', 'info');
        }
    });
}

function updateLiveViewMode() {
    const toggleBtn = document.getElementById('live-toggle-btn');
    const modeEl = document.getElementById('trading-mode');

    if (state.liveViewMode) {
        // Enable live view mode
        document.body.classList.add('live-view-mode');
        toggleBtn.classList.add('active');
        toggleBtn.querySelector('span:last-child').textContent = 'Exit Live';
        modeEl.textContent = 'VIEWING LIVE';
        modeEl.classList.add('viewing-live');
        modeEl.classList.remove('paper');
    } else {
        // Disable live view mode
        document.body.classList.remove('live-view-mode');
        toggleBtn.classList.remove('active');
        toggleBtn.querySelector('span:last-child').textContent = 'View Live';
        modeEl.classList.remove('viewing-live');
        if (state.paperMode) {
            modeEl.textContent = 'PAPER';
            modeEl.classList.add('paper');
        } else {
            modeEl.textContent = 'LIVE';
            modeEl.classList.add('live');
        }
    }
}

// ===== Orders =====
async function refreshOrders() {
    const endpoint = state.liveViewMode ? '/api/live/orders' : '/api/orders';
    const result = await api(endpoint);
    if (result.success) {
        state.orders = result.data || [];
        renderOrders();
    }
}

function renderOrders() {
    const tbody = document.getElementById('orders-table-body');

    if (!state.orders || state.orders.length === 0) {
        tbody.innerHTML = '<tr class="empty-row"><td colspan="7">No orders today</td></tr>';
        return;
    }

    tbody.innerHTML = state.orders.map(order => {
        // Handle both paper trading format and Kotak API format
        const symbol = order.trading_symbol || order.trdSym || order.sym || 'N/A';
        const timeStr = order.order_time || order.ordDtTm || order.ordEntTm;
        const txnType = order.transaction_type || order.trnsTp || 'B';
        const qty = order.quantity || order.qty || 0;
        const price = order.price || order.prc || order.avgPrc || 0;
        const status = order.status || order.ordSt || order.stat || 'unknown';
        const orderId = order.order_id || order.nOrdNo || '';

        // Parse time - handle different formats
        let time = '--';
        if (timeStr) {
            try {
                // Handle "22-Jan-2025 14:28:01" format
                const parsed = new Date(timeStr);
                if (!isNaN(parsed)) {
                    time = parsed.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' });
                } else {
                    // Try extracting time part directly
                    const match = timeStr.match(/(\d{1,2}:\d{2})/);
                    time = match ? match[1] : timeStr.split(' ')[1] || '--';
                }
            } catch (e) {
                time = '--';
            }
        }

        const typeClass = txnType === 'B' ? 'positive' : 'negative';
        const statusClass = status.toLowerCase();

        return `
            <tr>
                <td>${time}</td>
                <td><strong>${symbol}</strong></td>
                <td class="${typeClass}">${txnType === 'B' ? 'BUY' : 'SELL'}</td>
                <td>${qty}</td>
                <td>₹${parseFloat(price).toFixed(2)}</td>
                <td><span class="status-badge ${statusClass}">${status}</span></td>
                <td>
                    ${status === 'open' || status === 'pending' ?
                `<button onclick="cancelOrder('${orderId}')" class="btn-icon" title="Cancel">×</button>` :
                ''}
                </td>
            </tr>
        `;
    }).join('');
}

async function cancelOrder(orderId) {
    const result = await api(`/api/orders/${orderId}`, { method: 'DELETE' });

    if (result.success) {
        showToast('Order cancelled', 'success');
        refreshOrders();
    } else {
        showToast(result.error || 'Failed to cancel order', 'error');
    }
}

// ===== Positions =====
async function refreshPositions() {
    const endpoint = state.liveViewMode ? '/api/live/positions' : '/api/positions';
    const result = await api(endpoint);
    if (result.success) {
        state.positions = result.data || [];
        renderPositions();
    }
}

function renderPositions() {
    const tbody = document.getElementById('positions-table-body');

    if (!state.positions || state.positions.length === 0) {
        tbody.innerHTML = '<tr class="empty-row"><td colspan="6">No open positions</td></tr>';
        return;
    }

    tbody.innerHTML = state.positions.map(pos => {
        // Handle both paper trading format and Kotak API format
        const symbol = pos.trading_symbol || pos.trdSym || pos.sym || 'N/A';
        const exchange = pos.exchange_segment || pos.exSeg || 'nse_cm';

        // Calculate net quantity from Kotak API format
        let netQty = pos.net_qty;
        if (netQty === undefined) {
            const cfBuyQty = parseInt(pos.cfBuyQty) || 0;
            const cfSellQty = parseInt(pos.cfSellQty) || 0;
            const flBuyQty = parseInt(pos.flBuyQty) || 0;
            const flSellQty = parseInt(pos.flSellQty) || 0;
            const totalBuyQty = cfBuyQty + flBuyQty;
            const totalSellQty = cfSellQty + flSellQty;
            netQty = totalBuyQty - totalSellQty;
        }

        const avgPrice = pos.avg_price || pos.avgPrc || 0;
        const ltp = pos.ltp || pos.ltp || 0;

        // Calculate P&L
        let totalPnl = pos.total_pnl;
        if (totalPnl === undefined) {
            // Simple P&L calculation: (LTP - Avg Price) * Net Qty
            totalPnl = (parseFloat(ltp) - parseFloat(avgPrice)) * netQty;
        }

        const pnlClass = totalPnl >= 0 ? 'positive' : 'negative';
        const qtyClass = netQty >= 0 ? 'positive' : 'negative';

        return `
            <tr>
                <td><strong>${symbol}</strong></td>
                <td class="${qtyClass}">${netQty}</td>
                <td>₹${parseFloat(avgPrice).toFixed(2)}</td>
                <td>₹${parseFloat(ltp || 0).toFixed(2)}</td>
                <td class="${pnlClass}">₹${parseFloat(totalPnl || 0).toFixed(2)}</td>
                <td>
                    <button onclick="exitPosition('${symbol}', '${exchange}', ${netQty})" 
                            class="btn-icon" title="Exit">↗</button>
                </td>
            </tr>
        `;
    }).join('');
}

async function exitPosition(symbol, exchange, qty) {
    const txnType = qty > 0 ? 'S' : 'B';
    const absQty = Math.abs(qty);

    // Get LTP for market order (simplified for paper trading)
    const result = await api('/api/orders', {
        method: 'POST',
        body: JSON.stringify({
            trading_symbol: symbol,
            exchange_segment: exchange,
            transaction_type: txnType,
            order_type: 'MKT',
            product: 'MIS',
            quantity: absQty,
            price: 0
        })
    });

    if (result.success) {
        showToast(`Position exit order placed`, 'success');
        refreshOrders();
        refreshPositions();
    } else {
        showToast(result.error || 'Failed to exit position', 'error');
    }
}

// ===== Holdings =====
async function refreshHoldings() {
    const endpoint = state.liveViewMode ? '/api/live/holdings' : '/api/holdings';
    const result = await api(endpoint);
    if (result.success) {
        state.holdings = result.data || [];
        renderHoldings();
    }
}

function renderHoldings() {
    const tbody = document.getElementById('holdings-table-body');

    if (!state.holdings || state.holdings.length === 0) {
        tbody.innerHTML = '<tr class="empty-row"><td colspan="6">No holdings</td></tr>';
        return;
    }

    tbody.innerHTML = state.holdings.map(h => {
        const pnlClass = h.pnl >= 0 ? 'positive' : 'negative';

        return `
            <tr>
                <td><strong>${h.symbol}</strong></td>
                <td>${h.quantity}</td>
                <td>₹${parseFloat(h.average_price).toFixed(2)}</td>
                <td>₹${parseFloat(h.current_price).toFixed(2)}</td>
                <td>₹${parseFloat(h.current_value).toFixed(2)}</td>
                <td class="${pnlClass}">₹${h.pnl.toFixed(2)} (${h.pnl_percent.toFixed(2)}%)</td>
            </tr>
        `;
    }).join('');
}

// ===== Trades =====
async function refreshTrades() {
    const endpoint = state.liveViewMode ? '/api/live/trades' : '/api/trades';
    const result = await api(endpoint);
    if (result.success) {
        state.trades = result.data || [];
        renderTrades();
    }
}

function renderTrades() {
    const tbody = document.getElementById('trades-table-body');

    if (!state.trades || state.trades.length === 0) {
        tbody.innerHTML = '<tr class="empty-row"><td colspan="6">No trades today</td></tr>';
        return;
    }

    tbody.innerHTML = state.trades.map(trade => {
        // Handle both paper trading format and Kotak API format
        const symbol = trade.trading_symbol || trade.trdSym || trade.sym || 'N/A';
        const timeStr = trade.order_time || trade.flTm || trade.exTm;
        const txnType = trade.transaction_type || trade.trnsTp || 'B';
        const filledQty = trade.filled_quantity || trade.fldQty || 0;
        const avgPrice = trade.average_price || trade.avgPrc || 0;

        // Parse time - handle different formats
        let time = '--';
        if (timeStr) {
            try {
                const parsed = new Date(timeStr);
                if (!isNaN(parsed)) {
                    time = parsed.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' });
                } else {
                    // Handle "14:28:16" or "22-Jan-2025 14:28:01" format
                    const match = timeStr.match(/(\d{1,2}:\d{2})/);
                    time = match ? match[1] : timeStr;
                }
            } catch (e) {
                time = timeStr || '--';
            }
        }

        const typeClass = txnType === 'B' ? 'positive' : 'negative';
        const value = parseFloat(filledQty) * parseFloat(avgPrice);

        return `
            <tr>
                <td>${time}</td>
                <td><strong>${symbol}</strong></td>
                <td class="${typeClass}">${txnType === 'B' ? 'BUY' : 'SELL'}</td>
                <td>${filledQty}</td>
                <td>₹${parseFloat(avgPrice).toFixed(2)}</td>
                <td>₹${value.toFixed(2)}</td>
            </tr>
        `;
    }).join('');
}

// ===== Watchlist =====
function updateWatchlistPrice(data) {
    const key = `${data.instrument_token}_${data.exchange_segment}`;
    const item = document.querySelector(`.watchlist-item[data-key="${key}"]`);

    if (item) {
        const priceEl = item.querySelector('.price');
        const changeEl = item.querySelector('.change');
        const oldPrice = parseFloat(priceEl.dataset.price) || 0;
        const newPrice = data.ltp;

        priceEl.textContent = `₹${newPrice.toFixed(2)}`;
        priceEl.dataset.price = newPrice;

        const changePercent = data.change_percent;
        changeEl.textContent = `${changePercent >= 0 ? '+' : ''}${changePercent.toFixed(2)}%`;
        changeEl.classList.remove('positive', 'negative');
        changeEl.classList.add(changePercent >= 0 ? 'positive' : 'negative');

        // Flash animation
        if (newPrice > oldPrice) {
            item.classList.add('price-up');
            setTimeout(() => item.classList.remove('price-up'), 500);
        } else if (newPrice < oldPrice) {
            item.classList.add('price-down');
            setTimeout(() => item.classList.remove('price-down'), 500);
        }
    }
}

function addToWatchlist(token, exchange, symbol) {
    const key = `${token}_${exchange}`;
    if (state.watchlist.find(w => w.key === key)) return;

    state.watchlist.push({ key, token, exchange, symbol });
    renderWatchlist();

    // Subscribe to market data
    api('/api/subscribe', {
        method: 'POST',
        body: JSON.stringify({
            instrument_tokens: [{ instrument_token: token, exchange_segment: exchange }],
            is_depth: true
        })
    });
}

function renderWatchlist() {
    const container = document.getElementById('watchlist');

    if (state.watchlist.length === 0) {
        container.innerHTML = '<div class="empty-state">Add symbols to watchlist</div>';
        return;
    }

    container.innerHTML = state.watchlist.map(w => `
        <div class="watchlist-item" data-key="${w.key}" onclick="selectSymbol('${w.token}', '${w.exchange}', '${w.symbol}')">
            <div>
                <div class="symbol">${w.symbol}</div>
                <div class="exchange">${w.exchange.toUpperCase()}</div>
            </div>
            <div style="text-align: right;">
                <div class="price" data-price="0">₹0.00</div>
                <div class="change">0.00%</div>
            </div>
        </div>
    `).join('');
}

function selectSymbol(token, exchange, symbol) {
    state.selectedSymbol = `${token}_${exchange}`;

    // Update UI
    document.querySelectorAll('.watchlist-item').forEach(el => el.classList.remove('active'));
    document.querySelector(`.watchlist-item[data-key="${state.selectedSymbol}"]`)?.classList.add('active');

    document.getElementById('depth-symbol').textContent = symbol;
    document.getElementById('order-symbol').value = symbol;

    // Get market depth
    api(`/api/market-depth?instrument_token=${token}&exchange_segment=${exchange}`)
        .then(result => {
            if (result.success && result.data) {
                updateMarketDepth(result.data);
            }
        });

    // Get price info
    api(`/api/market-data?instrument_token=${token}&exchange_segment=${exchange}`)
        .then(result => {
            if (result.success && result.data) {
                updatePriceInfo(result.data);
            }
        });
}

// ===== Market Depth =====
function updateMarketDepth(data) {
    const container = document.getElementById('market-depth');
    const bids = data.bids || [];
    const asks = data.asks || [];

    let html = '';
    for (let i = 0; i < 5; i++) {
        const bid = bids[i] || { price: 0, quantity: 0, orders: 0 };
        const ask = asks[i] || { price: 0, quantity: 0, orders: 0 };

        html += `
            <div class="depth-row">
                <div class="bid">${bid.quantity || '-'}</div>
                <div class="bid">${bid.orders || '-'}</div>
                <div class="bid">${bid.quantity || '-'}</div>
                <div class="price-bid">${bid.price ? bid.price.toFixed(2) : '-'}</div>
                <div class="price-ask">${ask.price ? ask.price.toFixed(2) : '-'}</div>
                <div class="ask">${ask.quantity || '-'}</div>
                <div class="ask">${ask.orders || '-'}</div>
                <div class="ask">${ask.quantity || '-'}</div>
            </div>
        `;
    }
    container.innerHTML = html;

    // Update totals
    const totalBid = bids.reduce((sum, b) => sum + (b.quantity || 0), 0);
    const totalAsk = asks.reduce((sum, a) => sum + (a.quantity || 0), 0);
    document.getElementById('total-bid-qty').textContent = totalBid.toLocaleString();
    document.getElementById('total-ask-qty').textContent = totalAsk.toLocaleString();
}

function updatePriceInfo(data) {
    document.getElementById('info-open').textContent = `₹${(data.open || 0).toFixed(2)}`;
    document.getElementById('info-high').textContent = `₹${(data.high || 0).toFixed(2)}`;
    document.getElementById('info-low').textContent = `₹${(data.low || 0).toFixed(2)}`;
    document.getElementById('info-close').textContent = `₹${(data.close || 0).toFixed(2)}`;
    document.getElementById('info-volume').textContent = (data.volume || 0).toLocaleString();
    document.getElementById('info-oi').textContent = (data.open_interest || 0).toLocaleString();
}

// ===== Order Form =====
function setupOrderForm() {
    const form = document.getElementById('order-form');
    const txnBtns = document.querySelectorAll('.txn-btn');
    const orderTypeSelect = document.getElementById('order-type');
    const triggerInput = document.getElementById('order-trigger');
    const priceInput = document.getElementById('order-price');

    // Transaction type toggle
    txnBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            txnBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            state.transactionType = btn.dataset.type;

            const submitBtn = document.getElementById('place-order-btn');
            if (state.transactionType === 'B') {
                submitBtn.textContent = 'PLACE BUY ORDER';
                submitBtn.classList.remove('btn-sell');
                submitBtn.classList.add('btn-buy');
            } else {
                submitBtn.textContent = 'PLACE SELL ORDER';
                submitBtn.classList.remove('btn-buy');
                submitBtn.classList.add('btn-sell');
            }
        });
    });

    // Order type change - enable/disable trigger
    orderTypeSelect.addEventListener('change', () => {
        const type = orderTypeSelect.value;
        triggerInput.disabled = !['SL', 'SL-M'].includes(type);
        priceInput.disabled = ['MKT', 'SL-M'].includes(type);
    });

    // Form submission
    form.addEventListener('submit', async (e) => {
        e.preventDefault();

        const orderData = {
            trading_symbol: document.getElementById('order-symbol').value,
            exchange_segment: document.getElementById('order-exchange').value,
            transaction_type: state.transactionType,
            order_type: document.getElementById('order-type').value,
            product: document.getElementById('order-product').value,
            quantity: parseInt(document.getElementById('order-qty').value),
            price: parseFloat(document.getElementById('order-price').value) || 0,
            trigger_price: parseFloat(document.getElementById('order-trigger').value) || 0
        };

        if (!orderData.trading_symbol || !orderData.quantity) {
            showToast('Please fill in symbol and quantity', 'error');
            return;
        }

        const submitBtn = document.getElementById('place-order-btn');
        submitBtn.disabled = true;
        submitBtn.textContent = 'Placing...';

        try {
            const result = await api('/api/orders', {
                method: 'POST',
                body: JSON.stringify(orderData)
            });

            if (result.success) {
                showToast(`Order placed: ${result.order_id || 'Success'}`, 'success');
                form.reset();
                refreshOrders();
                refreshPositions();
            } else {
                showToast(result.error || 'Order failed', 'error');
            }
        } catch (err) {
            showToast('Error placing order', 'error');
        } finally {
            submitBtn.disabled = false;
            submitBtn.textContent = state.transactionType === 'B' ? 'PLACE BUY ORDER' : 'PLACE SELL ORDER';
        }
    });
}

// ===== Login =====
function setupLogin() {
    const loginBtn = document.getElementById('login-btn');
    const modal = document.getElementById('login-modal');
    const closeBtn = modal.querySelector('.modal-close');
    const submitBtn = document.getElementById('submit-login');
    const totpInput = document.getElementById('totp-input');

    loginBtn.addEventListener('click', () => {
        if (state.authenticated) {
            // Logout
            api('/api/auth/logout', { method: 'POST' })
                .then(() => {
                    state.authenticated = false;
                    loginBtn.textContent = 'Login';
                    showToast('Logged out', 'info');
                });
        } else {
            modal.classList.add('active');
            totpInput.focus();
        }
    });

    closeBtn.addEventListener('click', () => modal.classList.remove('active'));
    modal.addEventListener('click', (e) => {
        if (e.target === modal) modal.classList.remove('active');
    });

    submitBtn.addEventListener('click', async () => {
        const totp = totpInput.value;
        if (!totp || totp.length !== 6) {
            showToast('Enter valid 6-digit TOTP', 'error');
            return;
        }

        submitBtn.disabled = true;
        submitBtn.textContent = 'Logging in...';

        try {
            const result = await api('/api/auth/login', {
                method: 'POST',
                body: JSON.stringify({ totp })
            });

            if (result.success) {
                state.authenticated = true;
                state.paperMode = result.paper_mode;
                modal.classList.remove('active');
                loginBtn.textContent = 'Logout';
                updateTradingMode();
                showToast('Login successful', 'success');

                // Subscribe to order feed
                api('/api/subscribe/orderfeed', { method: 'POST' });

                // Refresh all data
                refreshAll();
            } else {
                showToast(result.error || 'Login failed', 'error');
            }
        } catch (err) {
            showToast('Login error', 'error');
        } finally {
            submitBtn.disabled = false;
            submitBtn.textContent = 'Login';
            totpInput.value = '';
        }
    });

    // Enter key on TOTP input
    totpInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') submitBtn.click();
    });
}

// ===== Tabs =====
function setupTabs() {
    const tabs = document.querySelectorAll('.tab');

    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            const tabId = tab.dataset.tab;

            tabs.forEach(t => t.classList.remove('active'));
            tab.classList.add('active');

            document.querySelectorAll('.tab-content').forEach(content => {
                content.classList.remove('active');
            });
            document.getElementById(`${tabId}-tab`).classList.add('active');

            // Refresh data for active tab
            switch (tabId) {
                case 'orders': refreshOrders(); break;
                case 'positions': refreshPositions(); break;
                case 'holdings': refreshHoldings(); break;
                case 'trades': refreshTrades(); break;
            }
        });
    });
}

// ===== Refresh All =====
async function refreshAll() {
    await Promise.all([
        refreshOrders(),
        refreshPositions(),
        refreshHoldings(),
        refreshTrades()
    ]);

    // Use live dashboard endpoint when in live view mode
    const dashboardEndpoint = state.liveViewMode ? '/api/live/dashboard' : '/api/dashboard';
    const dashboard = await api(dashboardEndpoint);
    if (dashboard.success) {
        updateDashboard(dashboard.data);
    }
}

// ===== Check Auth Status =====
async function checkAuth() {
    const result = await api('/api/auth/status');
    state.authenticated = result.authenticated;
    state.paperMode = result.paper_mode;

    const loginBtn = document.getElementById('login-btn');
    loginBtn.textContent = state.authenticated ? 'Logout' : 'Login';
    updateTradingMode();

    if (state.authenticated) {
        refreshAll();
    }
}

// ===== Demo Watchlist =====
function addDemoWatchlist() {
    // Add some demo symbols for paper trading
    const demoSymbols = [
        { token: '11536', exchange: 'nse_cm', symbol: 'TCS-EQ' },
        { token: '1594', exchange: 'nse_cm', symbol: 'INFY-EQ' },
        { token: '2885', exchange: 'nse_cm', symbol: 'RELIANCE-EQ' },
        { token: '1333', exchange: 'nse_cm', symbol: 'HDFCBANK-EQ' },
        { token: '3045', exchange: 'nse_cm', symbol: 'SBIN-EQ' }
    ];

    demoSymbols.forEach(s => {
        state.watchlist.push({ key: `${s.token}_${s.exchange}`, ...s });
    });
    renderWatchlist();
}

// ===== Initialize =====
document.addEventListener('DOMContentLoaded', () => {
    setupOrderForm();
    setupLogin();
    setupTabs();
    setupLiveViewToggle();

    checkAuth();
    addDemoWatchlist();

    // Get trading mode
    api('/api/mode').then(result => {
        state.paperMode = result.paper_mode;
        updateTradingMode();
    });

    // Periodic refresh
    setInterval(() => {
        if (state.authenticated) {
            // Use live dashboard endpoint when in live view mode
            const dashboardEndpoint = state.liveViewMode ? '/api/live/dashboard' : '/api/dashboard';
            api(dashboardEndpoint).then(result => {
                if (result.success) updateDashboard(result.data);
            });
        }
    }, 10000);
});
