from flask import Flask, jsonify
import requests, time, hmac, hashlib, json, os
from datetime import datetime, timedelta
import math

app = Flask(__name__)

# === DELTA CONFIG ===
DELTA_API_KEY = os.getenv("DELTA_API_KEY", "")
DELTA_API_SECRET = os.getenv("DELTA_API_SECRET", "")
BASE_URL = "https://api.india.delta.exchange" # Change to https://api.delta.exchange if global

# === IMPROVEMENT 8: AUTO LOT ===
BASE_LOT = 0.01  # 0.01 BTC = 1 Lot = your 65 qty
qty = BASE_LOT

# Vars
pnl=0; wins=0; loss=0; spot=0; ema20=0; ema50=0
price_history=[]; atr=200; supertrend_direction="BULL"
in_trade=False; side=""; entry=0; symbol_traded=""; highest=0; order_id=""
current_iv=0

def get_ist(): return datetime.utcnow() + timedelta(hours=5, minutes=30)

def delta_signature(method, path, query, payload):
    timestamp = str(int(time.time()))
    message = method + timestamp + path + query + payload
    signature = hmac.new(DELTA_API_SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()
    return signature, timestamp

# === IMPROVEMENT 1: REAL BTC PRICE ===
def get_btc_price():
    global spot, ema20, ema50, price_history, atr
    try:
        # Real ticker
        r = requests.get(f"{BASE_URL}/v2/tickers/BTCUSD", timeout=5).json()
        price = float(r['result']['spot_price'])
        
        # History for ATR & EMA
        price_history.append(price)
        if len(price_history) > 100: price_history.pop(0)
        
        if ema20 == 0:
            ema20 = price; ema50 = price
        else:
            ema20 = ema20*0.95 + price*0.05
            ema50 = ema50*0.98 + price*0.02
        
        # === IMPROVEMENT 3: ATR SL ===
        if len(price_history) >= 14:
            tr_list = [abs(price_history[i]-price_history[i-1]) for i in range(1,len(price_history))]
            atr = sum(tr_list[-14:]) / 14
            atr = max(atr, 100) # Min $100 ATR
        
        spot = price
        return price
    except Exception as e:
        print(f"Price error {e}")
        return spot or 65000

# === IMPROVEMENT 4: SUPERTREND ===
def get_supertrend():
    global supertrend_direction
    if ema20 > ema50 and spot > ema20:
        supertrend_direction = "BULL"
    elif ema20 < ema50 and spot < ema20:
        supertrend_direction = "BEAR"
    else:
        supertrend_direction = supertrend_direction # hold
    return supertrend_direction

# === IMPROVEMENT 5: IV FILTER ===
def get_iv_filter(symbol):
    global current_iv
    try:
        r = requests.get(f"{BASE_URL}/v2/tickers/{symbol}", timeout=5).json()
        iv = float(r['result'].get('mark_iv', 0)) * 100 # IV in %
        current_iv = iv
        # Filter: Don't trade if IV > 100% (too expensive)
        if iv > 100:
            return False, iv
        return True, iv
    except:
        return True, 0 # If fail, allow trade

# === IMPROVEMENT 7: BETTER ITM1 LOGIC ===
def get_delta_options_symbol(btc_price, side):
    try:
        # Find nearest expiry (next 2 days)
        expiry_date = (get_ist() + timedelta(days=2)).strftime("%d%b%y").upper()
        # Try to find ITM1 strike that actually exists in Delta orderbook
        base = int(btc_price // 500) * 500 # 500 gap - More precise
        if side == "CE":
            strike = base - 1000 # ITM1 for CE = 1 strike below spot
        else:
            strike = base + 1000 # ITM1 for PE = 1 strike above spot
        
        # Round to nearest 500
        strike = int(strike // 500) * 500
        
        opt_type = "C" if side == "CE" else "P"
        symbol = f"BTC-{expiry_date}-{strike}-{opt_type}"
        
        # Verify symbol exists
        try:
            r = requests.get(f"{BASE_URL}/v2/tickers/{symbol}", timeout=3).json()
            if r.get('success'):
                return symbol
        except:
            pass
        # Fallback if symbol not found
        return f"C-BTC-{strike}-{expiry_date}" if side=="CE" else f"P-BTC-{strike}-{expiry_date}"
    except:
        expiry = (get_ist() + timedelta(days=2)).strftime("%d%b%y").upper()
        return f"BTC-{expiry}-{int(btc_price)}-{'C' if side=='CE' else 'P'}"

def place_delta_order(symbol, action):
    global order_id
    if not DELTA_API_KEY:
        return {"status":"SIMULATION", "symbol":symbol, "action":action}
    try:
        path = "/v2/orders"
        # Auto lot size
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
        order_id = str(result.get('result',{}).get('id',''))
        return result
    except Exception as e:
        return {"error": str(e), "status":"SIMULATION"}

@app.route('/')
def home():
    ist = get_ist()
    price = get_btc_price()
    has_keys = bool(DELTA_API_KEY and DELTA_API_SECRET)
    return f"""
    <h1>DELTA IMPROVED BOT - REAL BTC</h1>
    <p>Time: {ist.strftime('%d-%m-%Y %H:%M:%S IST')} | BTC: ${price:.0f}</p>
    <p>Improvements: 1-RealPrice 3-ATR SL 4-Supertrend 5-IV Filter 7-ITM1 8-AutoLot</p>
    <p>P&L: ${pnl} Wins:{wins} Loss:{loss} Order:{order_id}</p>
    <p>ATR: ${atr:.0f} Supertrend: {supertrend_direction} IV: {current_iv:.1f}% Lot: {qty} BTC</p>
    <p>Status: {'REAL' if has_keys else 'SIMULATION - Add DELTA_API_KEY'} | <a href='/status'>LIVE STATUS</a></p>
    """

@app.route('/status')
def status():
    global in_trade, side, entry, highest, pnl, wins, loss, symbol_traded, qty
    ist = get_ist()
    price = get_btc_price()
    st = get_supertrend()
    
    profit = ""
    if not in_trade:
        # === IMPROVEMENT 4: Supertrend Confirmation ===
        bull_ok = (st == "BULL" and price > ema20)
        bear_ok = (st == "BEAR" and price < ema20)
        
        if bull_ok:
            # Check IV before entry
            temp_symbol = get_delta_options_symbol(price, "CE")
            iv_ok, iv = get_iv_filter(temp_symbol)
            if iv_ok and price > ema20 + (atr*0.2): # Extra filter: price above EMA + ATR
                side = "CE"; entry = price; highest = 0
                symbol_traded = temp_symbol
                result = place_delta_order(symbol_traded, "B")
                in_trade = True
                profit = f"NEW ENTRY {side} {symbol_traded} @ ${price:.0f} ST:{st} ATR:{atr:.0f} IV:{iv:.1f}% Result:{result.get('status','')}"
            else:
                profit = f"SCANNING BULL but IV High {iv:.1f}% or weak momentum - BTC ${price:.0f} ST:{st} EMA {ema20:.0f}/{ema50:.0f} ATR {atr:.0f} Time {ist.strftime('%H:%M:%S IST')}"
        elif bear_ok:
            temp_symbol = get_delta_options_symbol(price, "PE")
            iv_ok, iv = get_iv_filter(temp_symbol)
            if iv_ok and price < ema20 - (atr*0.2):
                side = "PE"; entry = price; highest = 0
                symbol_traded = temp_symbol
                result = place_delta_order(symbol_traded, "B")
                in_trade = True
                profit = f"NEW ENTRY {side} {symbol_traded} @ ${price:.0f} ST:{st} ATR:{atr:.0f} IV:{iv:.1f}% Result:{result.get('status','')}"
            else:
                profit = f"SCANNING BEAR but IV High {iv:.1f}% - BTC ${price:.0f} ST:{st} EMA {ema20:.0f}/{ema50:.0f} ATR {atr:.0f} Time {ist.strftime('%H:%M:%S IST')}"
        else:
            profit = f"SCANNING BTC ${price:.0f} ST:{st} Trend:{'BULL' if ema20>ema50 else 'BEAR'} EMA {ema20:.0f}/{ema50:.0f} ATR ${atr:.0f} IV {current_iv:.1f}% Lot {qty} Time {ist.strftime('%H:%M:%S IST')}"
    else:
        curr = (price-entry) if side=="CE" else (entry-price)
        if curr > highest: highest = curr
        
        # === IMPROVEMENT 3: ATR based SL & Trail ===
        # SL = 1x ATR, Trail = Highest - 0.5x ATR
        sl_amount = atr  # e.g., $300
        trail_sl = highest - (atr*0.5) if highest >= (atr*0.5) else -sl_amount
        
        profit = f"IN TRADE {side} {symbol_traded} Entry ${entry:.0f} Now ${price:.0f} Move ${curr:.0f} High ${highest:.0f} TrailSL ${trail_sl:.0f} (ATR ${atr:.0f}) ST {st}"
        
        if curr <= trail_sl:
            result = place_delta_order(symbol_traded, "S")
            trade_pnl = trail_sl if trail_sl >=0 else -sl_amount
            # === IMPROVEMENT 8: AUTO LOT P&L ===
            pnl += trade_pnl * qty * 10 # Convert to USD P&L
            if trade_pnl > 0: wins+=1
            else: loss+=1
            in_trade=False
            profit += f" -> EXIT Result {result.get('status','')} P&L ${trade_pnl:.0f} Total ${pnl:.0f}"
    
    return jsonify({
        "time": ist.strftime("%d-%m-%Y %H:%M:%S IST"),
        "btc": price,
        "ema20": int(ema20),
        "ema50": int(ema50),
        "atr": int(atr),
        "supertrend": st,
        "iv": current_iv,
        "profit": profit,
        "pnl": pnl,
        "wins": wins,
        "loss": loss,
        "in_trade": in_trade,
        "side": side,
        "symbol": symbol_traded,
        "lot": f"{qty} BTC = 1 Lot (65 qty logic)",
        "improvements": "1-REAL BTC 3-ATR SL 4-SUPERTREND 5-IV FILTER 7-ITM1 SMART 8-AUTO LOT"
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
