from flask import Flask, jsonify
import requests, time, hmac, hashlib, json, os
from datetime import datetime, timedelta

app = Flask(__name__)

# === UPTIME TRACKING - NEW ===
start_time = datetime.utcnow()
def get_uptime():
    diff = datetime.utcnow() - start_time
    total_seconds = int(diff.total_seconds())
    days = total_seconds // 86400
    hours = (total_seconds % 86400) // 3600
    mins = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    if days > 0:
        return f"{days}d {hours}h {mins}m {secs}s"
    else:
        return f"{hours}h {mins}m {secs}s"

# === DELTA API KEYS ===
DELTA_API_KEY = os.getenv("DELTA_API_KEY", "YOUR_DELTA_API_KEY_HERE")
DELTA_API_SECRET = os.getenv("DELTA_API_SECRET", "YOUR_DELTA_API_SECRET_HERE")
BASE_URL = "https://api.india.delta.exchange"

# === CONFIG - 3 ASSETS ===
SYMBOLS = ["BTC", "ETH", "XAUT"]
BASE_LOT = 0.01

# Per-symbol state
bots = {}
for sym in SYMBOLS:
    bots[sym] = {
        "pnl": 0, "wins": 0, "loss": 0, "spot": 0,
        "ema20": 0, "ema50": 0, "price_history": [],
        "atr": 200, "supertrend": "BULL",
        "in_trade": False, "side": "", "entry": 0,
        "symbol_traded": "", "highest": 0,
        "current_iv": 0
    }

balance = 0
order_id = ""

def get_ist(): 
    return datetime.utcnow() + timedelta(hours=5, minutes=30)

def delta_signature(method, path, query, payload):
    timestamp = str(int(time.time()))
    message = method + timestamp + path + query + payload
    signature = hmac.new(DELTA_API_SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()
    return signature, timestamp

def get_price(symbol):
    b = bots[symbol]
    try:
        r = requests.get(f"{BASE_URL}/v2/tickers/{symbol}USD", timeout=5).json()
        price = float(r['result']['spot_price'])
        b["price_history"].append(price)
        if len(b["price_history"]) > 100: b["price_history"].pop(0)
        if b["ema20"] == 0:
            b["ema20"] = price; b["ema50"] = price
        else:
            b["ema20"] = b["ema20"]*0.95 + price*0.05
            b["ema50"] = b["ema50"]*0.98 + price*0.02
        if len(b["price_history"]) >= 14:
            tr_list = [abs(b["price_history"][i]-b["price_history"][i-1]) for i in range(1,len(b["price_history"]))]
            b["atr"] = max(sum(tr_list[-14:]) / 14, 80 if symbol=="BTC" else 20)
        b["spot"] = price
        return price
    except:
        return b["spot"] or 0

def get_supertrend(symbol):
    b = bots[symbol]
    if b["ema20"] > b["ema50"] and b["spot"] > b["ema20"]:
        b["supertrend"] = "BULL"
    elif b["ema20"] < b["ema50"] and b["spot"] < b["ema20"]:
        b["supertrend"] = "BEAR"
    return b["supertrend"]

def get_iv_filter(ticker_symbol):
    try:
        r = requests.get(f"{BASE_URL}/v2/tickers/{ticker_symbol}", timeout=5).json()
        if r.get('result') and r['result'].get('mark_iv'):
            iv = float(r['result'].get('mark_iv', 0)) * 100
            return (iv <= 100), iv
        return True, 0
    except:
        return True, 0

def get_options_symbol(btc_price, side, asset="BTC"):
    try:
        expiry_date = (get_ist() + timedelta(days=1)).strftime("%d%b%y").upper()
        base = int(btc_price // 500) * 500 if asset=="BTC" else int(btc_price)
        if side == "CE":
            strike = base - (500 if asset=="BTC" else 0)
        else:
            strike = base + (500 if asset=="BTC" else 0)
        opt_type = "C" if side == "CE" else "P"
        symbol = f"{asset}-{expiry_date}-{strike}-{opt_type}"
        return symbol
    except:
        expiry = (get_ist() + timedelta(days=1)).strftime("%d%b%y").upper()
        return f"{asset}-{expiry}-{int(btc_price)}-{'C' if side=='CE' else 'P'}"

def place_delta_order(symbol, action):
    global order_id
    if not DELTA_API_KEY or "YOUR_" in DELTA_API_KEY or len(DELTA_API_KEY) < 10:
        return {"status":"SIMULATION - Add API Keys", "symbol":symbol, "action":action}
    try:
        path = "/v2/orders"
        payload_dict = {
            "product_symbol": symbol,
            "size": BASE_LOT,
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
    has_keys = bool(DELTA_API_KEY and len(DELTA_API_KEY)>10 and "YOUR_" not in DELTA_API_KEY)
    html = f"""
    <h1>DELTA BOT-2 - LIVE ✅ Uptime: {get_uptime()}</h1>
    <p>Started: {start_time.strftime('%d-%m-%Y %H:%M:%S UTC')} | Now: {ist.strftime('%d-%m-%Y %H:%M:%S IST')}</p>
    <p>Mode: <b>{'REAL TRADING ✅' if has_keys else 'SIMULATION'}</b> | Uptime: <b>{get_uptime()}</b></p>
    <hr>
    """
    for sym in SYMBOLS:
        get_price(sym)
        b = bots[sym]
        html += f"<p><b>{sym}</b>: ${b['spot']:.2f} | EMA {b['ema20']:.0f}/{b['ema50']:.0f} | ST {b['supertrend']} | ATR ${b['atr']:.0f} | InTrade: {b['in_trade']} {b['side']} | PnL ${b['pnl']:.2f} W:{b['wins']} L:{b['loss']}</p>"
    
    html += f"<p><a href='/status'>LIVE STATUS JSON</a> | Auto-refresh 10s</p><script>setTimeout(()=>location.reload(),10000)</script>"
    return html

@app.route('/status')
def status():
    ist = get_ist()
    has_keys = bool(DELTA_API_KEY and len(DELTA_API_KEY)>10 and "YOUR_" not in DELTA_API_KEY)
    result = {
        "uptime": get_uptime(),
        "started": start_time.strftime('%d-%m-%Y %H:%M:%S UTC'),
        "current_time": ist.strftime('%d-%m-%Y %H:%M:%S IST'),
        "mode": "REAL" if has_keys else "SIMULATION",
        "balance": balance,
        "total_pnl": 0,
        "bots": {}
    }
    
    for sym in SYMBOLS:
        price = get_price(sym)
        st = get_supertrend(sym)
        b = bots[sym]
        result["total_pnl"] += b["pnl"]
        
        profit_msg = ""
        if not b["in_trade"]:
            bull_ok = (st == "BULL" and price > b["ema20"])
            bear_ok = (st == "BEAR" and price < b["ema20"])
            if bull_ok:
                temp_sym = get_options_symbol(price, "CE", sym)
                iv_ok, iv = get_iv_filter(temp_sym)
                if iv_ok:
                    b["side"] = "CE"; b["entry"] = price; b["highest"] = 0
                    b["symbol_traded"] = temp_sym
                    res = place_delta_order(b["symbol_traded"], "B")
                    b["in_trade"] = True
                    profit_msg = f"NEW ENTRY {sym} {b['side']} {temp_sym} @ ${price:.0f} ST:{st} IV:{iv:.1f}%"
                else:
                    profit_msg = f"SCANNING {sym} BULL but IV High {iv:.1f}% Skip"
            elif bear_ok:
                temp_sym = get_options_symbol(price, "PE", sym)
                iv_ok, iv = get_iv_filter(temp_sym)
                if iv_ok:
                    b["side"] = "PE"; b["entry"] = price; b["highest"] = 0
                    b["symbol_traded"] = temp_sym
                    res = place_delta_order(b["symbol_traded"], "B")
                    b["in_trade"] = True
                    profit_msg = f"NEW ENTRY {sym} {b['side']} {temp_sym} @ ${price:.0f} ST:{st} IV:{iv:.1f}%"
                else:
                    profit_msg = f"SCANNING {sym} BEAR but IV High {iv:.1f}% Skip"
            else:
                profit_msg = f"SCANNING {sym} ${price:.0f} ST:{st} EMA {b['ema20']:.0f}/{b['ema50']:.0f} ATR ${b['atr']:.0f}"
        else:
            curr = (price-b["entry"]) if b["side"]=="CE" else (b["entry"]-price)
            if curr > b["highest"]: b["highest"] = curr
            sl_amount = b["atr"]
            trail_sl = b["highest"] - (b["atr"]*0.5) if b["highest"] >= (b["atr"]*0.5) else -sl_amount
            profit_msg = f"IN TRADE {sym} {b['side']} Entry ${b['entry']:.0f} Now ${price:.0f} Move ${curr:.0f} High ${b['highest']:.0f} TrailSL ${trail_sl:.0f}"
            if curr <= trail_sl:
                res = place_delta_order(b["symbol_traded"], "S")
                trade_pnl = trail_sl if trail_sl >=0 else -sl_amount
                b["pnl"] += trade_pnl * BASE_LOT * 10
                if trade_pnl > 0: b["wins"]+=1
                else: b["loss"]+=1
                b["in_trade"]=False
                profit_msg += f" -> EXIT P&L ${trade_pnl:.0f}"
        
        result["bots"][sym] = {
            "spot": price,
            "ema20": int(b["ema20"]),
            "ema50": int(b["ema50"]),
            "atr": int(b["atr"]),
            "supertrend": st,
            "in_trade": b["in_trade"],
            "side": b["side"],
            "pnl": round(b["pnl"],2),
            "profit_msg": profit_msg
        }
    
    return jsonify(result)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
