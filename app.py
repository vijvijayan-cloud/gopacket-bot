from flask import Flask, jsonify
import requests, time, hmac, hashlib, json, os
from datetime import datetime, timedelta

app = Flask(__name__)

DELTA_API_KEY = os.getenv("DELTA_API_KEY", "")
DELTA_API_SECRET = os.getenv("DELTA_API_SECRET", "")
BASE_URL = "https://api.india.delta.exchange"

qty = 1
pnl_total=0; wins=0; loss=0

ASSETS = ["BTC", "ETH", "XAUT"]  # All 3 have options!

states = {}
for asset in ASSETS:
    states[asset] = {
        "spot":0, "ema20":0, "ema50":0, "history":[], "atr":200,
        "st":"BULL", "in_trade":False, "side":"", "entry":0, 
        "symbol":"", "highest":0, "pnl":0
    }

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
        # XAUT price from your screenshot 3901.29
        st["history"].append(price)
        if len(st["history"]) > 100: st["history"].pop(0)
        if st["ema20"] == 0: st["ema20"]=price; st["ema50"]=price
        else: st["ema20"]=st["ema20"]*0.95 + price*0.05; st["ema50"]=st["ema50"]*0.98 + price*0.02
        if len(st["history"]) >= 14:
            tr = [abs(st["history"][i]-st["history"][i-1]) for i in range(1,len(st["history"]))]
            base_atr = 80 if asset=="BTC" else 50 if asset=="ETH" else 10
            st["atr"] = max(sum(tr[-14:])/14, base_atr)
        st["spot"]=price
        return price
    except:
        return st["spot"] or (76000 if asset=="BTC" else 3800 if asset=="ETH" else 3901)

def get_supertrend(asset):
    st = states[asset]
    if st["ema20"] > st["ema50"] and st["spot"] > st["ema20"]: st["st"]="BULL"
    elif st["ema20"] < st["ema50"] and st["spot"] < st["ema20"]: st["st"]="BEAR"
    return st["st"]

def get_options_symbol(asset, price, side):
    try:
        # Get XAUT options specifically - your screenshot shows it exists!
        r = requests.get(f"{BASE_URL}/v2/products?contract_types=call_options,put_options&underlying_asset_symbols={asset}", timeout=10).json()
        products = r.get('result', [])
        
        # Sort by nearest expiry
        products = sorted(products, key=lambda x: x.get('settlement_time',''))
        
        step = 500 if asset=="BTC" else 100 if asset=="ETH" else 10  # XAUT step 10 from screenshot
        target = int(price // step) * step
        # ITM1 from your screenshot: if price 3901, ITM Call is 3890, Put 3910
        target = target - step if side=="CE" else target + step
        
        best=None; best_diff=9999999; nearest_expiry=None
        
        for p in products:
            try:
                strike=float(p.get('strike_price',0))
                ctype=p.get('contract_type','')
                want='call_options' if side=="CE" else 'put_options'
                if ctype!=want: continue
                # Only today/tomorrow expiry
                diff=abs(strike-target)
                if diff<best_diff and strike>0:
                    best_diff=diff; best=p
            except: continue
        
        if best:
            print(f"FOUND {asset} {side} {best['symbol']} Strike {best['strike_price']} Target {target} Spot {price}")
            return best['symbol']
            
    except Exception as e:
        print(f"{asset} symbol error {e}")
    
    return None

def place_order(symbol, action):
    if not DELTA_API_KEY or len(DELTA_API_KEY)<10:
        return {"success": False, "error": "no keys"}
    try:
        path="/v2/orders"
        payload_dict={"product_symbol": symbol, "size": int(qty), "side": "buy" if action=="B" else "sell", "order_type": "market_order"}
        payload_str=json.dumps(payload_dict)
        sig, ts = delta_signature("POST", path, "", payload_str)
        headers={"api-key": DELTA_API_KEY, "timestamp": ts, "signature": sig, "Content-Type":"application/json"}
        r=requests.post(BASE_URL+path, data=payload_str, headers=headers, timeout=10)
        result=r.json()
        print(f"ORDER {symbol} {action} => {result}")
        return {"success": result.get('success', False), "result": result}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.route('/')
def home():
    html="<h1>MULTI-COIN BOT BTC+ETH+XAUT OPTIONS</h1>"
    for a in ASSETS:
        p=get_price(a); html+=f"<p>{a}: ${p:.2f} ST:{states[a]['st']} ATR:${states[a]['atr']:.0f} InTrade:{states[a]['in_trade']}</p>"
    html+="<p><a href='/status'>STATUS</a> | <a href='/reset'>RESET ALL</a> | <a href='/products/BTC'>BTC Products</a> | <a href='/products/ETH'>ETH Products</a> | <a href='/products/XAUT'>XAUT Products</a></p>"
    return html

@app.route('/reset')
@app.route('/reset/<asset>')
def reset(asset=None):
    if asset and asset in states:
        s=states[asset]; s["in_trade"]=False; s["side"]=""; s["entry"]=0; s["highest"]=0; s["symbol"]=""
        return jsonify({f"reset {asset}": "Done"})
    elif not asset:
        for a in ASSETS:
            s=states[a]; s["in_trade"]=False; s["side"]=""; s["entry"]=0; s["highest"]=0; s["symbol"]=""
        return jsonify({"reset ALL": "Done"})
    return jsonify({"error": "invalid"})

@app.route('/products/<asset>')
def products(asset):
    try:
        r = requests.get(f"{BASE_URL}/v2/products?contract_types=call_options,put_options&underlying_asset_symbols={asset}", timeout=10).json()
        prods = r.get('result', [])[:15]
        symbols = [{"symbol": p['symbol'], "strike": p['strike_price'], "type": p['contract_type'], "expiry": p.get('settlement_time')} for p in prods]
        return jsonify(symbols)
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route('/status')
def status():
    global pnl_total, wins, loss
    ist=get_ist()
    results={}; summary=[]
    
    for asset in ASSETS:
        s=states[asset]
        price=get_price(asset)
        st=get_supertrend(asset)
        msg=""
        
        if not s["in_trade"]:
            bull_ok = (st=="BULL" and price > s["ema20"])
            bear_ok = (st=="BEAR" and price < s["ema20"])
            
            if bull_ok or bear_ok:
                side = "CE" if bull_ok else "PE"
                sym = get_options_symbol(asset, price, side)
                if not sym:
                    msg=f"{asset} NO OPTION SYMBOL ${price:.1f} ST:{st}"
                else:
                    res = place_order(sym, "B")
                    if res.get('success'):
                        s["side"]=side; s["entry"]=price; s["highest"]=0; s["symbol"]=sym; s["in_trade"]=True
                        msg=f"NEW REAL ENTRY {asset} {side} {sym} @ ${price:.1f} ST:{st} LIVE!"
                    else:
                        msg=f"{asset} ORDER FAILED {sym} {res.get('result')} ${price:.1f} ST:{st}"
            else:
                msg=f"SCANNING {asset} ${price:.1f} ST:{st} EMA {s['ema20']:.1f}/{s['ema50']:.1f} ATR ${s['atr']:.0f}"
        else:
            curr = (price-s["entry"]) if s["side"]=="CE" else (s["entry"]-price)
            if curr > s["highest"]: s["highest"]=curr
            trail_sl = s["highest"] - (s["atr"]*0.5) if s["highest"] >= (s["atr"]*0.5) else -s["atr"]
            msg=f"IN TRADE {asset} {s['side']} {s['symbol']} Entry ${s['entry']:.1f} Now ${price:.1f} Move ${curr:.1f} High ${s['highest']:.1f} TrailSL ${trail_sl:.1f}"
            if curr <= trail_sl:
                res = place_order(s["symbol"], "S")
                trade_pnl = trail_sl
                s["pnl"]+=trade_pnl; pnl_total+=trade_pnl
                if trade_pnl>0: wins+=1
                else: loss+=1
                s["in_trade"]=False
                msg+=f" -> EXIT {res.get('result')} P&L ${trade_pnl:.1f}"
        
        results[asset]={"price": price, "supertrend": st, "in_trade": s["in_trade"], "side": s["side"], "symbol": s["symbol"], "profit": msg, "pnl": s["pnl"]}
        summary.append(msg)
    
    return jsonify({
        "time": ist.strftime("%d-%m-%Y %H:%M:%S IST"),
        "pnl_total": pnl_total, "wins": wins, "loss": loss,
        "assets": results,
        "summary": " | ".join(summary),
        "mode": "REAL MULTI BTC+ETH+XAUT OPTIONS"
    })

if __name__ == '__main__': app.run(host='0.0.0.0', port=10000)
