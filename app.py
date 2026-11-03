from flask import Flask, jsonify
import requests, time, hmac, hashlib, json, os
from datetime import datetime, timedelta

app = Flask(__name__)

DELTA_API_KEY = os.getenv("DELTA_API_KEY", "")
DELTA_API_SECRET = os.getenv("DELTA_API_SECRET", "")
BASE_URL = "https://api.india.delta.exchange"

qty = 1
pnl_total=0; wins=0; loss=0
ASSETS = ["BTC", "ETH", "XAUT"]

states = {}
for asset in ASSETS:
    states[asset] = {"spot":0,"ema20":0,"ema50":0,"history":[],"atr":200,"st":"BULL","in_trade":False,"side":"","entry":0,"symbol":"","highest":0,"pnl":0}

def get_ist(): return datetime.utcnow() + timedelta(hours=5, minutes=30)

def delta_signature(method, path, query, payload):
    timestamp = str(int(time.time()))
    message = method + timestamp + path + query + payload
    signature = hmac.new(DELTA_API_SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()
    return signature, timestamp

def get_price(asset):
    st = states[asset]
    try:
        ticker = f"{asset}USD"
        r = requests.get(f"{BASE_URL}/v2/tickers/{ticker}", timeout=5).json()
        price = float(r['result']['spot_price'])
        st["history"].append(price)
        if len(st["history"]) > 100: st["history"].pop(0)
        if st["ema20"] == 0: st["ema20"]=price; st["ema50"]=price
        else: st["ema20"]=st["ema20"]*0.95 + price*0.05; st["ema50"]=st["ema50"]*0.98 + price*0.02
        if len(st["history"]) >= 14:
            tr = [abs(st["history"][i]-st["history"][i-1]) for i in range(1,len(st["history"]))]
            st["atr"] = max(sum(tr[-14:])/14, 50 if asset=="BTC" else 10 if asset=="ETH" else 5)
        st["spot"]=price
        return price
    except:
        return st["spot"] or (77000 if asset=="BTC" else 2266 if asset=="ETH" else 3900)

def get_supertrend(asset):
    st = states[asset]
    if st["ema20"] > st["ema50"]: st["st"]="BULL"
    elif st["ema20"] < st["ema50"]: st["st"]="BEAR"
    else: st["st"]="BULL"
    return st["st"]

def get_options_symbol(asset, price, side):
    try:
        r = requests.get(f"{BASE_URL}/v2/products?contract_types=call_options,put_options&underlying_asset_symbols={asset}", timeout=10).json()
        products = r.get('result', [])
        # Filter for nearest expiry (today)
        today_products = [p for p in products if '031126' in p['symbol'] or '061126' in p['symbol']][:50]
        if not today_products: today_products = products
        
        step = 500 if asset=="BTC" else 100 if asset=="ETH" else 10
        target = int(price // step) * step
        if side=="CE": target = target - step
        else: target = target + step
        
        best=None; best_diff=999999
        for p in today_products:
            try:
                strike=float(p.get('strike_price',0))
                ctype=p.get('contract_type','')
                want='call_options' if side=="CE" else 'put_options'
                if ctype!=want: continue
                diff=abs(strike-target)
                if diff<best_diff and strike>0:
                    best_diff=diff; best=p
            except: continue
        if best:
            print(f"FOUND {asset} {best['symbol']} target {target} spot {price}")
            return best['symbol']
    except Exception as e:
        print(f"SYMBOL ERROR {asset} {e}")
    return None

def place_order(symbol, action):
    print(f"TRYING ORDER {symbol} {action} size {qty} type {type(qty)}")
    if not DELTA_API_KEY or len(DELTA_API_KEY)<10:
        return {"success": False, "error": "NO KEYS", "full": "API keys missing"}
    try:
        path="/v2/orders"
        payload_dict={"product_symbol": symbol, "size": int(qty), "side": "buy" if action=="B" else "sell", "order_type": "market_order"}
        payload_str=json.dumps(payload_dict)
        sig, ts = delta_signature("POST", path, "", payload_str)
        headers={"api-key": DELTA_API_KEY, "timestamp": ts, "signature": sig, "Content-Type":"application/json"}
        print(f"HEADERS api-key {DELTA_API_KEY[:5]}... timestamp {ts}")
        r=requests.post(BASE_URL+path, data=payload_str, headers=headers, timeout=10)
        print(f"RESPONSE STATUS {r.status_code} TEXT {r.text[:500]}")
        result=r.json()
        if result.get('success'):
            return {"success": True, "full": result, "result": result.get('result')}
        else:
            # Return FULL error
            return {"success": False, "full": result, "error": result.get('error', result)}
    except Exception as e:
        print(f"ORDER EXCEPTION {e}")
        import traceback; traceback.print_exc()
        return {"success": False, "error": str(e), "full": str(e)}

@app.route('/')
def home():
    return f"<h1>MULTI BOT DEBUG</h1><p>{[(a, get_price(a), states[a]['st']) for a in ASSETS]}</p><a href='/status'>STATUS</a>"

@app.route('/status')
def status():
    global pnl_total
    ist=get_ist()
    results={}; summary=[]
    
    for asset in ASSETS:
        s=states[asset]
        price=get_price(asset)
        st=get_supertrend(asset)
        msg=""
        
        if not s["in_trade"]:
            # For first trade, allow BULL even if price == ema
            side = "CE" if st=="BULL" else "PE"
            sym = get_options_symbol(asset, price, side)
            if not sym:
                msg=f"{asset} NO SYMBOL price ${price:.1f} ST:{st}"
            else:
                res = place_order(sym, "B")
                if res.get('success'):
                    s["side"]=side; s["entry"]=price; s["highest"]=0; s["symbol"]=sym; s["in_trade"]=True
                    msg=f"NEW LIVE {asset} {side} {sym} @ ${price:.1f}"
                else:
                    msg=f"{asset} ORDER FAILED {sym} ERROR:{res.get('full')} price ${price:.1f} ST:{st}"
        else:
            curr = (price-s["entry"]) if s["side"]=="CE" else (s["entry"]-price)
            if curr > s["highest"]: s["highest"]=curr
            trail_sl = s["highest"] - (s["atr"]*0.5) if s["highest"] >= (s["atr"]*0.5) else -s["atr"]
            msg=f"IN TRADE {asset} {s['side']} {s['symbol']} Entry ${s['entry']:.1f} Now ${price:.1f} Move ${curr:.1f} High ${s['highest']:.1f} SL ${trail_sl:.1f}"
            if curr <= trail_sl:
                res = place_order(s["symbol"], "S")
                s["in_trade"]=False
                msg+=f" EXIT {res.get('full')} P&L ${trail_sl:.1f}"
        
        results[asset]={"price": price, "st": st, "in_trade": s["in_trade"], "profit": msg}
        summary.append(msg)
    
    return jsonify({"time": ist.strftime("%H:%M:%S IST"), "assets": results, "summary": " | ".join(summary), "mode": "DEBUG MULTI"})

@app.route('/products/<asset>')
def products(asset):
    r = requests.get(f"{BASE_URL}/v2/products?contract_types=call_options,put_options&underlying_asset_symbols={asset}", timeout=10).json()
    return jsonify(r.get('result', [])[:5])

if __name__ == '__main__': app.run(host='0.0.0.0', port=10000)
