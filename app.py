from flask import Flask, jsonify
import requests, time, hmac, hashlib, json, os
from datetime import datetime, timedelta

app = Flask(__name__)

DELTA_API_KEY = os.getenv("DELTA_API_KEY", "")
DELTA_API_SECRET = os.getenv("DELTA_API_SECRET", "")
BASE_URL = "https://api.india.delta.exchange"

# === FIXED: INTEGER SIZE ===
qty = 1  # MUST BE INTEGER FOR OPTIONS

pnl=0; wins=0; loss=0; spot=0; ema20=0; ema50=0
price_history=[]; atr=200; supertrend_direction="BULL"
in_trade=False; side=""; entry=0; symbol_traded=""; highest=0; order_id=""

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
    except: return spot or 76770

def get_supertrend():
    global supertrend_direction
    if ema20 > ema50 and spot > ema20: supertrend_direction = "BULL"
    elif ema20 < ema50 and spot < ema20: supertrend_direction = "BEAR"
    return supertrend_direction

def get_delta_options_symbol(btc_price, side):
    try:
        r = requests.get(f"{BASE_URL}/v2/products?contract_types=call_options,put_options&underlying_asset_symbols=BTC", timeout=10).json()
        products = r.get('result', [])
        target_strike = int(btc_price // 500) * 500
        target_strike = target_strike - 500 if side=="CE" else target_strike + 500
        best = None; best_diff = 999999
        for p in products:
            try:
                strike = float(p.get('strike_price', 0))
                ctype = p.get('contract_type', '')
                wanted_type = 'call_options' if side=="CE" else 'put_options'
                if ctype != wanted_type: continue
                diff = abs(strike - target_strike)
                if diff < best_diff and strike > 0:
                    best_diff = diff
                    best = p
            except: continue
        if best:
            return best['symbol']
    except Exception as e:
        print(f"Symbol error {e}")
    expiry = (get_ist() + timedelta(days=1)).strftime("%d%m%y")
    strike = int(btc_price // 500)*500
    strike = strike - 500 if side=="CE" else strike + 500
    return f"{'C' if side=='CE' else 'P'}-BTC-{strike}-{expiry}"

def place_delta_order(symbol, action):
    global order_id
    if not DELTA_API_KEY or len(DELTA_API_KEY) < 10:
        return {"success": False, "status": "SIMULATION"}
    try:
        path = "/v2/orders"
        # FIX: size MUST be int
        payload_dict = {"product_symbol": symbol, "size": int(qty), "side": "buy" if action=="B" else "sell", "order_type": "market_order"}
        payload_str = json.dumps(payload_dict)
        sig, ts = delta_signature("POST", path, "", payload_str)
        headers = {"api-key": DELTA_API_KEY, "timestamp": ts, "signature": sig, "Content-Type":"application/json"}
        r = requests.post(BASE_URL+path, data=payload_str, headers=headers, timeout=10)
        result = r.json()
        print(f"ORDER {symbol} => {result}")
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
    return f"<h1>DELTA BOT FINAL</h1><p>BTC ${price:.1f} ST {supertrend_direction} qty={qty} (int)</p><p><a href='/status'>STATUS</a> | <a href='/reset'>RESET</a></p>"

@app.route('/reset')
def reset():
    global in_trade, side, entry, highest, symbol_traded
    in_trade=False; side=""; entry=0; highest=0; symbol_traded=""
    return jsonify({"reset": "Done! in_trade cleared", "qty": qty, "qty_type": str(type(qty))})

@app.route('/status')
def status():
    global in_trade, side, entry, highest, pnl, wins, loss, symbol_traded
    ist = get_ist(); price = get_btc_price(); st = get_supertrend()
    profit=""
    if not in_trade:
        bull_ok = (st == "BULL" and price > ema20)
        bear_ok = (st == "BEAR" and price < ema20)
        if bull_ok:
            sym = get_delta_options_symbol(price, "CE")
            res = place_delta_order(sym, "B")
            if res.get('success'):
                side="CE"; entry=price; highest=0; symbol_traded=sym; in_trade=True
                profit = f"NEW REAL ENTRY {side} {symbol_traded} @ ${price:.0f} {res['status']}"
            else:
                profit = f"ORDER FAILED {sym} {res} BTC ${price:.0f} ST:{st}"
        elif bear_ok:
            sym = get_delta_options_symbol(price, "PE")
            res = place_delta_order(sym, "B")
            if res.get('success'):
                side="PE"; entry=price; highest=0; symbol_traded=sym; in_trade=True
                profit = f"NEW REAL ENTRY {side} {symbol_traded} @ ${price:.0f} {res['status']}"
            else:
                profit = f"ORDER FAILED {sym} {res} BTC ${price:.0f} ST:{st}"
        else:
            profit = f"SCANNING BTC ${price:.0f} ST:{st} EMA {ema20:.0f}/{ema50:.0f} ATR ${atr:.0f} qty={qty} Time {ist.strftime('%H:%M:%S IST')}"
    else:
        curr = (price-entry) if side=="CE" else (entry-price)
        if curr > highest: highest = curr
        trail_sl = highest - (atr*0.5) if highest >= (atr*0.5) else -atr
        profit = f"IN TRADE {side} {symbol_traded} Entry ${entry:.0f} Now ${price:.0f} Move ${curr:.0f} High ${highest:.0f} TrailSL ${trail_sl:.0f}"
        if curr <= trail_sl:
            res = place_delta_order(symbol_traded, "S")
            pnl += trail_sl * int(qty) * 10
            in_trade=False
            profit += f" -> EXIT {res.get('status')} P&L ${trail_sl:.0f}"
    
    return jsonify({"time": ist.strftime("%d-%m-%Y %H:%M:%S IST"), "btc": price, "ema20": int(ema20), "ema50": int(ema50), "atr": int(atr), "supertrend": st, "profit": profit, "pnl": pnl, "in_trade": in_trade, "side": side, "symbol": symbol_traded, "qty": int(qty), "qty_type": "int - FIXED", "mode": "REAL"})

if __name__ == '__main__': app.run(host='0.0.0.0', port=10000)
