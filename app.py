from flask import Flask, jsonify
import requests, time, hmac, hashlib, json, os
from datetime import datetime, timedelta

app = Flask(__name__)

DELTA_API_KEY = os.getenv("DELTA_API_KEY", "YOUR_KEY")
DELTA_API_SECRET = os.getenv("DELTA_API_SECRET", "YOUR_SECRET")
BASE_URL = "https://api.india.delta.exchange"

qty = 1  # 1 Lot = 1 Contract (for options, not 0.01 BTC)
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

def get_btc_price():
    global spot, ema20, ema50, price_history, atr
    try:
        r = requests.get(f"{BASE_URL}/v2/tickers/BTCUSD", timeout=5).json()
        price = float(r['result']['spot_price'])
        price_history.append(price)
        if len(price_history) > 100: price_history.pop(0)
        if ema20 == 0: ema20 = price; ema50 = price
        else: ema20 = ema20*0.95 + price*0.05; ema50 = ema50*0.98 + price*0.02
        if len(price_history) >= 14:
            tr_list = [abs(price_history[i]-price_history[i-1]) for i in range(1,len(price_history))]
            atr = sum(tr_list[-14:]) / 14
            atr = max(atr, 80)
        spot = price
        return price
    except: return spot or 76700

def get_supertrend():
    global supertrend_direction
    if ema20 > ema50 and spot > ema20: supertrend_direction = "BULL"
    elif ema20 < ema50 and spot < ema20: supertrend_direction = "BEAR"
    return supertrend_direction

# === NEW: FIND CORRECT SYMBOL FROM DELTA API ===
def get_delta_options_symbol(btc_price, side):
    try:
        # Get all BTC options
        r = requests.get(f"{BASE_URL}/v2/products?contract_types=call_options,put_options&underlying_asset_symbols=BTC", timeout=10).json()
        products = r.get('result', [])
        
        # Find nearest strike
        target_strike = int(btc_price // 500) * 500
        target_strike = target_strike - 500 if side=="CE" else target_strike + 500
        
        best = None
        best_diff = 999999
        
        for p in products:
            # Only near expiry (0-3 days)
            try:
                exp_time = p.get('settlement_time', '')
                # symbol like C-BTC-76000-041125
                strike = float(p.get('strike_price', 0))
                ctype = p.get('contract_type', '')
                
                wanted_type = 'call_options' if side=="CE" else 'put_options'
                if ctype != wanted_type: continue
                
                diff = abs(strike - target_strike)
                # Prefer strikes close to target and expiring soon
                if diff < best_diff and strike > 0:
                    best_diff = diff
                    best = p
            except: continue
        
        if best:
            print(f"FOUND SYMBOL: {best['symbol']} Strike {best['strike_price']} for target {target_strike} side {side}")
            return best['symbol']
    except Exception as e:
        print(f"Symbol find error {e}")
    
    # Fallback - try common formats
    expiry = (get_ist() + timedelta(days=1)).strftime("%d%m%y")
    strike = int(btc_price // 500)*500
    strike = strike - 500 if side=="CE" else strike + 500
    # Try format C-BTC-76000-041125
    return f"{'C' if side=='CE' else 'P'}-BTC-{strike}-{expiry}"

def place_delta_order(symbol, action):
    global order_id
    if not DELTA_API_KEY or "YOUR_" in DELTA_API_KEY or len(DELTA_API_KEY) < 10:
        return {"success": False, "status": "SIMULATION"}
    try:
        path = "/v2/orders"
        payload_dict = {"product_symbol": symbol, "size": qty, "side": "buy" if action=="B" else "sell", "order_type": "market_order"}
        payload_str = json.dumps(payload_dict)
        sig, ts = delta_signature("POST", path, "", payload_str)
        headers = {"api-key": DELTA_API_KEY, "timestamp": ts, "signature": sig, "Content-Type":"application/json"}
        r = requests.post(BASE_URL+path, data=payload_str, headers=headers, timeout=10)
        result = r.json()
        print(f"ORDER {symbol} {action} => {result}")
        if result.get('success'):
            order_id = str(result['result'].get('id',''))
            return {"success": True, "status": "LIVE ORDER PLACED", "result": result}
        else:
            return {"success": False, "status": f"FAILED {result.get('error')}", "result": result}
    except Exception as e:
        return {"success": False, "status": f"ERROR {e}"}

@app.route('/')
def home():
    price = get_btc_price()
    return f"<h1>DELTA BOT</h1><p>BTC ${price:.1f} ST {supertrend_direction} ATR ${atr:.0f}</p><p><a href='/status'>STATUS</a> | <a href='/reset'>RESET</a> | <a href='/products'>CHECK PRODUCTS</a></p>"

@app.route('/reset')
def reset():
    global in_trade, side, entry, highest, symbol_traded
    in_trade=False; side=""; entry=0; highest=0; symbol_traded=""
    return jsonify({"reset": "Done!"})

@app.route('/products')
def products():
    # Debug endpoint to see real symbols
    try:
        r = requests.get(f"{BASE_URL}/v2/products?contract_types=call_options,put_options&underlying_asset_symbols=BTC", timeout=10).json()
        prods = r.get('result', [])[:20]  # first 20
        symbols = [{"symbol": p['symbol'], "strike": p['strike_price'], "type": p['contract_type'], "expiry": p.get('settlement_time')} for p in prods]
        return jsonify(symbols)
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route('/status')
def status():
    global in_trade, side, entry, highest, pnl, wins, loss, symbol_traded
    ist = get_ist(); price = get_btc_price(); st = get_supertrend()
    has_keys = bool(DELTA_API_KEY and len(DELTA_API_KEY)>10 and "YOUR_" not in DELTA_API_KEY)
    profit=""
    if not in_trade:
        bull_ok = (st == "BULL" and price > ema20)
        bear_ok = (st == "BEAR" and price < ema20)
        if bull_ok:
            temp_symbol = get_delta_options_symbol(price, "CE")
            result = place_delta_order(temp_symbol, "B")
            if result.get('success'):
                side="CE"; entry=price; highest=0; symbol_traded=temp_symbol; in_trade=True
                profit = f"NEW REAL ENTRY {side} {symbol_traded} @ ${price:.0f} ST:{st} Result:{result['status']}"
            else:
                profit = f"ORDER FAILED {temp_symbol} {result} BTC ${price:.0f} ST:{st} Time {ist.strftime('%H:%M:%S IST')}"
        elif bear_ok:
            temp_symbol = get_delta_options_symbol(price, "PE")
            result = place_delta_order(temp_symbol, "B")
            if result.get('success'):
                side="PE"; entry=price; highest=0; symbol_traded=temp_symbol; in_trade=True
                profit = f"NEW REAL ENTRY {side} {symbol_traded} @ ${price:.0f} ST:{st} Result:{result['status']}"
            else:
                profit = f"ORDER FAILED {temp_symbol} {result} BTC ${price:.0f} ST:{st}"
        else:
            profit = f"SCANNING BTC ${price:.0f} ST:{st} EMA {ema20:.0f}/{ema50:.0f} ATR ${atr:.0f} Time {ist.strftime('%H:%M:%S IST')}"
    else:
        curr = (price-entry) if side=="CE" else (entry-price)
        if curr > highest: highest = curr
        sl_amount = atr
        trail_sl = highest - (atr*0.5) if highest >= (atr*0.5) else -sl_amount
        profit = f"IN TRADE {side} {symbol_traded} Entry ${entry:.0f} Now ${price:.0f} Move ${curr:.0f} High ${highest:.0f} TrailSL ${trail_sl:.0f}"
        if curr <= trail_sl:
            result = place_delta_order(symbol_traded, "S")
            trade_pnl = trail_sl
            pnl += trade_pnl * qty * 10
            if trade_pnl > 0: wins+=1
            else: loss+=1
            in_trade=False
            profit += f" -> EXIT {result.get('status','')} P&L ${trade_pnl:.0f}"
    
    return jsonify({"time": ist.strftime("%d-%m-%Y %H:%M:%S IST"), "btc": price, "ema20": int(ema20), "ema50": int(ema50), "atr": int(atr), "supertrend": st, "profit": profit, "pnl": pnl, "in_trade": in_trade, "side": side, "symbol": symbol_traded, "mode": "REAL" if has_keys else "SIM"})

if __name__ == '__main__': app.run(host='0.0.0.0', port=10000)
