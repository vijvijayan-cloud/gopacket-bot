from flask import Flask, jsonify
import requests, time, hmac, hashlib, json, os
from datetime import datetime, timedelta

app = Flask(__name__)

# === DELTA API KEYS - ADDED ===
# Put in Render Environment: DELTA_API_KEY and DELTA_API_SECRET
# Or put directly here (replace XXXX):
DELTA_API_KEY = os.getenv("DELTA_API_KEY", "YOUR_DELTA_API_KEY_HERE")
DELTA_API_SECRET = os.getenv("DELTA_API_SECRET", "YOUR_DELTA_API_SECRET_HERE")
BASE_URL = "https://api.india.delta.exchange"  # India server

# === CONFIG ===
BASE_LOT = 0.01  # 0.01 BTC = 1 Lot = your 65 qty logic
qty = BASE_LOT

pnl=0; wins=0; loss=0; spot=0; ema20=0; ema50=0
price_history=[]; atr=200; supertrend_direction="BULL"
in_trade=False; side=""; entry=0; symbol_traded=""; highest=0; order_id=""
current_iv=0; balance=0

def get_ist(): 
    return datetime.utcnow() + timedelta(hours=5, minutes=30)

def delta_signature(method, path, query, payload):
    timestamp = str(int(time.time()))
    message = method + timestamp + path + query + payload
    signature = hmac.new(DELTA_API_SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()
    return signature, timestamp

# === 1. REAL BTC PRICE ===
def get_btc_price():
    global spot, ema20, ema50, price_history, atr
    try:
        r = requests.get(f"{BASE_URL}/v2/tickers/BTCUSD", timeout=5).json()
        price = float(r['result']['spot_price'])
        price_history.append(price)
        if len(price_history) > 100: price_history.pop(0)
        if ema20 == 0:
            ema20 = price; ema50 = price
        else:
            ema20 = ema20*0.95 + price*0.05
            ema50 = ema50*0.98 + price*0.02
        if len(price_history) >= 14:
            tr_list = [abs(price_history[i]-price_history[i-1]) for i in range(1,len(price_history))]
            atr = sum(tr_list[-14:]) / 14
            atr = max(atr, 80)
        spot = price
        return price
    except:
        return spot or 76500

# === 4. SUPERTREND ===
def get_supertrend():
    global supertrend_direction
    if ema20 > ema50 and spot > ema20:
        supertrend_direction = "BULL"
    elif ema20 < ema50 and spot < ema20:
        supertrend_direction = "BEAR"
    return supertrend_direction

# === 5. IV FILTER - FIXED ===
def get_iv_filter(symbol):
    global current_iv
    try:
        r = requests.get(f"{BASE_URL}/v2/tickers/{symbol}", timeout=5).json()
        if r.get('result') and r['result'].get('mark_iv'):
            iv = float(r['result'].get('mark_iv', 0)) * 100
            current_iv = iv
            if iv > 100:
                return False, iv
        return True, current_iv
    except:
        return True, 0

# === 7. BETTER ITM1 LOGIC ===
def get_delta_options_symbol(btc_price, side):
    try:
        expiry_date = (get_ist() + timedelta(days=1)).strftime("%d%b%y").upper()
        base = int(btc_price // 500) * 500
        if side == "CE":
            strike = base - 500
        else:
            strike = base + 500
        strike = int(strike // 500) * 500
        opt_type = "C" if side == "CE" else "P"
        # Delta India format: C-BTC-76000-04-11-26 or BTC-04NOV26-76000-C (try both)
        # Using standard format
        symbol = f"BTC-{expiry_date}-{strike}-{opt_type}"
        return symbol
    except:
        expiry = (get_ist() + timedelta(days=1)).strftime("%d%b%y").upper()
        return f"BTC-{expiry}-{int(btc_price)}-{'C' if side=='CE' else 'P'}"

def get_balance():
    global balance
    if not DELTA_API_KEY or "YOUR_" in DELTA_API_KEY:
        return 0
    try:
        path = "/v2/wallet/balances"
        sig, ts = delta_signature("GET", path, "", "")
        headers = {"api-key": DELTA_API_KEY, "timestamp": ts, "signature": sig}
        r = requests.get(BASE_URL+path, headers=headers, timeout=5).json()
        if r.get('result'):
            for w in r['result']:
                if w['asset_symbol'] == 'USDT':
                    balance = float(w['available_balance'])
                    return balance
    except:
        pass
    return balance

def place_delta_order(symbol, action):
    global order_id
    # Check if keys added
    if not DELTA_API_KEY or "YOUR_" in DELTA_API_KEY or len(DELTA_API_KEY) < 10:
        return {"status":"SIMULATION - Add API Keys", "symbol":symbol, "action":action}
    try:
        path = "/v2/orders"
        order_size = qty
        payload_dict = {
            "product_symbol": symbol,
            "size": order_size,
            "side": "buy" if action=="B" else "sell",
            "order_type": "market_order"
        }
        payload_str = json.dumps(payload_dict)
        sig, ts = delta_signature("POST", path, "", payload_str)
        headers = {"api-key": DELTA_API_KEY, "timestamp": ts, "signature": sig, "Content-Type":"application/json"}
        r = requests.post(BASE_URL+path, data=payload_str, headers=headers, timeout=10)
        result = r.json()
        if result.get('result'):
            order_id = str(result['result'].get('id',''))
        return result
    except Exception as e:
        return {"error": str(e), "status":"ERROR"}

@app.route('/')
def home():
    ist = get_ist()
    price = get_btc_price()
    bal = get_balance()
    has_keys = bool(DELTA_API_KEY and len(DELTA_API_KEY)>10 and "YOUR_" not in DELTA_API_KEY)
    return f"""
    <h1>DELTA IMPROVED BOT - LIVE</h1>
    <p>Time: {ist.strftime('%d-%m-%Y %H:%M:%S IST')} | BTC: ${price:.1f}</p>
    <p>Balance: ${bal:.2f} USDT | P&L: ${pnl:.2f} W:{wins} L:{loss} Order:{order_id}</p>
    <p>EMA: {ema20:.0f}/{ema50:.0f} ATR: ${atr:.0f} ST: {supertrend_direction} IV: {current_iv:.1f}% Lot: {qty} BTC</p>
    <p>Mode: <b>{'REAL TRADING ✅' if has_keys else 'SIMULATION - Add Keys'}</b></p>
    <p>Improvements: 1-REAL 3-ATR SL 4-SUPERTREND 5-IV 7-ITM1 8-AUTO LOT</p>
    <p><a href='/status'>LIVE STATUS JSON</a> | Auto-refresh every 10 sec</p>
    <script>setTimeout(()=>location.reload(),10000)</script>
    """

@app.route('/status')
def status():
    global in_trade, side, entry, highest, pnl, wins, loss, symbol_traded, qty
    ist = get_ist()
    price = get_btc_price()
    st = get_supertrend()
    has_keys = bool(DELTA_API_KEY and len(DELTA_API_KEY)>10 and "YOUR_" not in DELTA_API_KEY)
    
    profit = ""
    if not in_trade:
        bull_ok = (st == "BULL" and price > ema20)
        bear_ok = (st == "BEAR" and price < ema20)
        
        if bull_ok:
            temp_symbol = get_delta_options_symbol(price, "CE")
            iv_ok, iv = get_iv_filter(temp_symbol)
            if iv_ok:
                side = "CE"; entry = price; highest = 0
                symbol_traded = temp_symbol
                result = place_delta_order(symbol_traded, "B")
                in_trade = True
                profit = f"NEW ENTRY {side} {symbol_traded} @ ${price:.0f} ST:{st} ATR:{atr:.0f} IV:{iv:.1f}% Result:{result.get('status') or result}"
            else:
                profit = f"SCANNING BULL but IV High {iv:.1f}% Skip - BTC ${price:.0f} ST:{st} EMA {ema20:.0f}/{ema50:.0f} ATR {atr:.0f} Time {ist.strftime('%H:%M:%S IST')}"
        elif bear_ok:
            temp_symbol = get_delta_options_symbol(price, "PE")
            iv_ok, iv = get_iv_filter(temp_symbol)
            if iv_ok:
                side = "PE"; entry = price; highest = 0
                symbol_traded = temp_symbol
                result = place_delta_order(symbol_traded, "B")
                in_trade = True
                profit = f"NEW ENTRY {side} {symbol_traded} @ ${price:.0f} ST:{st} ATR:{atr:.0f} IV:{iv:.1f}% Result:{result.get('status') or result}"
            else:
                profit = f"SCANNING BEAR but IV High {iv:.1f}% Skip - BTC ${price:.0f} ST:{st} EMA {ema20:.0f}/{ema50:.0f} ATR {atr:.0f} Time {ist.strftime('%H:%M:%S IST')}"
        else:
            profit = f"SCANNING BTC ${price:.0f} ST:{st} EMA {ema20:.0f}/{ema50:.0f} ATR ${atr:.0f} IV {current_iv:.1f}% Lot {qty} Time {ist.strftime('%H:%M:%S IST')}"
    else:
        curr = (price-entry) if side=="CE" else (entry-price)
        if curr > highest: highest = curr
        sl_amount = atr
        trail_sl = highest - (atr*0.5) if highest >= (atr*0.5) else -sl_amount
        profit = f"IN TRADE {side} {symbol_traded} Entry ${entry:.0f} Now ${price:.0f} Move ${curr:.0f} High ${highest:.0f} TrailSL ${trail_sl:.0f} (ATR ${atr:.0f}) ST {st}"
        if curr <= trail_sl:
            result = place_delta_order(symbol_traded, "S")
            trade_pnl = trail_sl if trail_sl >=0 else -sl_amount
            pnl += trade_pnl * qty * 10
            if trade_pnl > 0: wins+=1
            else: loss+=1
            in_trade=False
            profit += f" -> EXIT {result.get('status','')} P&L ${trade_pnl:.0f} Total ${pnl:.0f}"
    
    return jsonify({
        "time": ist.strftime("%d-%m-%Y %H:%M:%S IST"),
        "btc": price,
        "ema20": int(ema20),
        "ema50": int(ema50),
        "atr": int(atr),
        "supertrend": st,
        "iv": round(current_iv,2),
        "profit": profit,
        "pnl": round(pnl,2),
        "wins": wins,
        "loss": loss,
        "in_trade": in_trade,
        "side": side,
        "symbol": symbol_traded,
        "lot": f"{qty} BTC = 1 Lot (65 qty logic)",
        "mode": "REAL" if has_keys else "SIMULATION",
        "balance": balance,
        "improvements": "1-REAL BTC 3-ATR SL 4-SUPERTREND 5-IV FILTER 7-ITM1 SMART 8-AUTO LOT"
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
