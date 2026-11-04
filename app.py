from flask import Flask, jsonify
import requests, time, hmac, hashlib, json, os, threading
from datetime import datetime, timedelta

app = Flask(__name__)

# === UPTIME ===
start_time = datetime.utcnow()
def get_uptime():
    diff = datetime.utcnow() - start_time
    s = int(diff.total_seconds())
    d = s // 86400; h = (s % 86400)//3600; m = (s % 3600)//60; sec = s%60
    return f"{d}d {h}h {m}m {sec}s" if d>0 else f"{h}h {m}m {sec}s"

DELTA_API_KEY = os.getenv("DELTA_API_KEY", "")
DELTA_API_SECRET = os.getenv("DELTA_API_SECRET", "")
BASE_URL = "https://api.india.delta.exchange"

SYMBOLS = ["BTC", "ETH", "XAUT"]
BASE_LOT = 1

bots = {}
for sym in SYMBOLS:
    bots[sym] = {"pnl":0,"wins":0,"loss":0,"spot":0,"ema20":0,"ema50":0,"price_history":[],"atr":200,"supertrend":"BULL","in_trade":False,"side":"","entry":0,"symbol_traded":"","highest":0}

last_msgs = []
msg_lock = threading.Lock()

def get_ist(): return datetime.utcnow() + timedelta(hours=5,minutes=30)

def delta_signature(method, path, query, payload):
    ts = str(int(time.time()))
    msg = method + ts + path + query + payload
    sig = hmac.new(DELTA_API_SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()
    return sig, ts

def get_price(symbol):
    b = bots[symbol]
    try:
        r = requests.get(f"{BASE_URL}/v2/tickers/{symbol}USD", timeout=5).json()
        price = float(r['result']['spot_price'])
        b["price_history"].append(price)
        if len(b["price_history"])>100: b["price_history"].pop(0)
        if b["ema20"]==0: b["ema20"]=price; b["ema50"]=price
        else: b["ema20"]=b["ema20"]*0.95+price*0.05; b["ema50"]=b["ema50"]*0.98+price*0.02
        if len(b["price_history"])>=14:
            tr = [abs(b["price_history"][i]-b["price_history"][i-1]) for i in range(1,len(b["price_history"]))]
            b["atr"]=max(sum(tr[-14:])/14, 80 if symbol=="BTC" else 20)
        b["spot"]=price; return price
    except: return b["spot"] or 0

def get_supertrend(symbol):
    b=bots[symbol]
    if b["ema20"]>b["ema50"] and b["spot"]>b["ema20"]: b["supertrend"]="BULL"
    elif b["ema20"]<b["ema50"] and b["spot"]<b["ema20"]: b["supertrend"]="BEAR"
    return b["supertrend"]

def get_options_symbol(price, side, asset="BTC"):
    try:
        expiry = (get_ist()+timedelta(days=1)).strftime("%d%m%y")
        if asset=="BTC":
            strike = int(price//500)*500
            strike = strike-500 if side=="CE" else strike+500
        elif asset=="ETH":
            strike = int(price//10)*10
            strike = strike-10 if side=="CE" else strike+10
        else:
            strike = int(price//10)*10
            strike = strike-10 if side=="CE" else strike+10
        opt = "C" if side=="CE" else "P"
        return f"{opt}-{asset}-{strike}-{expiry}"
    except:
        expiry = (get_ist()+timedelta(days=1)).strftime("%d%m%y")
        opt = "C" if side=="CE" else "P"
        return f"{opt}-{asset}-{int(price)}-{expiry}"

def place_delta_order(symbol, action):
    if not DELTA_API_KEY or len(DELTA_API_KEY)<10:
        return {"status":"SIMULATION"}
    try:
        path="/v2/orders"
        payload_dict={"product_symbol":symbol,"size":BASE_LOT,"side":"buy" if action=="B" else "sell","order_type":"market_order"}
        payload_str=json.dumps(payload_dict)
        sig,ts=delta_signature("POST",path,"",payload_str)
        headers={"api-key":DELTA_API_KEY,"timestamp":ts,"signature":sig,"Content-Type":"application/json"}
        r=requests.post(BASE_URL+path,data=payload_str,headers=headers,timeout=10)
        return r.json()
    except Exception as e:
        return {"error":str(e)}

# ===== FIX 1: CHECK DELTA POSITIONS - SOURCE OF TRUTH =====
def get_live_positions():
    if not DELTA_API_KEY or len(DELTA_API_KEY)<10:
        return {}
    try:
        path="/v2/positions?state=open"
        sig,ts=delta_signature("GET",path,"","")
        headers={"api-key":DELTA_API_KEY,"timestamp":ts,"signature":sig,"Content-Type":"application/json"}
        r=requests.get(BASE_URL+path,headers=headers,timeout=10).json()
        live={}
        for p in r.get("result",[]):
            sym=p.get("product_symbol","")
            size=float(p.get("size",0))
            if size==0: continue
            for asset in SYMBOLS:
                if f"-{asset}-" in sym:
                    live[asset]={"symbol":sym,"size":size,"entry_price":float(p.get("entry_price",0))}
        return live
    except Exception as e:
        print("POS ERR",e)
        return {}

def sync_from_exchange():
    live=get_live_positions()
    for sym in SYMBOLS:
        b=bots[sym]
        if sym in live:
            # Delta has position -> we ARE in trade, even after restart
            if not b["in_trade"]:
                b["in_trade"]=True
                b["symbol_traded"]=live[sym]["symbol"]
                b["side"]="CE" if live[sym]["symbol"].startswith("C-") else "PE"
                b["entry"]=b["spot"] if b["entry"]==0 else b["entry"]
                b["highest"]=0
        else:
            # No position in Delta -> truly free
            if b["in_trade"]:
                # Was in trade but Delta shows closed (manual close / expired)
                # Don't auto-reset if we just placed order 5 sec ago - handled by loop
                pass
    return live

# ===== FIX 2: SAFE EXIT - NEVER CREATE SHORT =====
def safe_exit(sym, trail):
    b=bots[sym]
    live=get_live_positions()
    # If no LONG position in Delta, DON'T sell - just reset RAM
    if sym not in live or live[sym]["symbol"] != b["symbol_traded"] or live[sym]["size"] <= 0:
        print(f"EXIT SKIPPED {sym} - No LONG in Delta, prevents SHORT")
        b["in_trade"]=False
        b["symbol_traded"]=""
        return f"EXIT SKIPPED {sym} - No LONG, RAM reset (SHORT prevented)"
    res=place_delta_order(b["symbol_traded"],"S")
    if res.get("status")=="SIMULATION" or res.get("success"):
        b["pnl"]+=trail
        if trail>=0: b["wins"]+=1
        else: b["loss"]+=1
        b["in_trade"]=False
        msg=f"EXIT {sym} P&L ${trail:.0f}"
        b["symbol_traded"]=""
        return msg
    else:
        return f"EXIT FAILED {sym} {res}"

def run_trading_logic():
    msgs=[]
    # Sync first - FIX for restart amnesia
    live=sync_from_exchange()
    for sym in SYMBOLS:
        price=get_price(sym); st=get_supertrend(sym); b=bots[sym]
        if not b["in_trade"]:
            # FIX: Double-check Delta before entry
            if sym in live:
                b["in_trade"]=True
                b["symbol_traded"]=live[sym]["symbol"]
                b["side"]="CE" if live[sym]["symbol"].startswith("C-") else "PE"
                msgs.append(f"SYNCED {sym} Already in {b['symbol_traded']} from Delta")
                continue
            if st=="BULL" and price>b["ema20"]:
                temp=get_options_symbol(price,"CE",sym)
                res=place_delta_order(temp,"B")
                # FIX: Only set in_trade=True if order REALLY succeeded
                if res.get("status")=="SIMULATION" or res.get("success"):
                    b["side"]="CE"; b["entry"]=price; b["highest"]=0; b["symbol_traded"]=temp; b["in_trade"]=True
                    msgs.append(f"NEW ENTRY {sym} CALL {temp} @ ${price:.0f}")
                else:
                    msgs.append(f"ENTRY FAILED {sym} {temp} {res}")
            elif st=="BEAR" and price<b["ema20"]:
                temp=get_options_symbol(price,"PE",sym)
                res=place_delta_order(temp,"B")
                if res.get("status")=="SIMULATION" or res.get("success"):
                    b["side"]="PE"; b["entry"]=price; b["highest"]=0; b["symbol_traded"]=temp; b["in_trade"]=True
                    msgs.append(f"NEW ENTRY {sym} PUT {temp} @ ${price:.0f}")
                else:
                    msgs.append(f"ENTRY FAILED {sym} {temp} {res}")
            else:
                msgs.append(f"SCANNING {sym} ${price:.0f} ST:{st}")
        else:
            curr=(price-b["entry"]) if b["side"]=="CE" else (b["entry"]-price)
            if curr>b["highest"]: b["highest"]=curr
            trail=b["highest"]-(b["atr"]*0.5) if b["highest"]>=(b["atr"]*0.5) else -b["atr"]
            if curr<=trail:
                msgs.append(safe_exit(sym, trail))
            else:
                msgs.append(f"IN TRADE {sym} {b['side']} Move ${curr:.0f} Trail ${trail:.0f}")
    return msgs

# ===== FIX 3: BACKGROUND LOOP - Trading NOT on page refresh =====
def background_loop():
    global last_msgs
    while True:
        try:
            msgs=run_trading_logic()
            with msg_lock:
                last_msgs=msgs
            time.sleep(15)
        except Exception as e:
            print("LOOP ERR",e)
            time.sleep(10)

# Start loop ONCE when app starts
threading.Thread(target=background_loop, daemon=True).start()

@app.route('/')
def home():
    ist=get_ist()
    has_keys=bool(DELTA_API_KEY and len(DELTA_API_KEY)>10)
    with msg_lock:
        msgs=list(last_msgs)
    html=f"<h1>DELTA BOT-2 LIVE ✅ Uptime: {get_uptime()}</h1><p>Mode: {'REAL ✅' if has_keys else 'SIM'} | Started: {start_time.strftime('%H:%M UTC')} | Now: {ist.strftime('%H:%M:%S IST')}</p><p><b>FIXED v3:</b> Background Loop + Delta Sync + No SHORT</p><hr>"
    for sym in SYMBOLS:
        b=bots[sym]; html+=f"<p><b>{sym}</b>: ${b['spot']:.2f} EMA {b['ema20']:.0f}/{b['ema50']:.0f} ST {b['supertrend']} InTrade:{b['in_trade']} {b['side']} | {b['symbol_traded']}</p>"
    html+="<hr>"+"<br>".join(msgs)+"<p><a href='/status'>JSON STATUS</a></p><script>setTimeout(()=>location.reload(),10000)</script>"
    return html

@app.route('/status')
def status():
    ist=get_ist(); has_keys=bool(DELTA_API_KEY and len(DELTA_API_KEY)>10)
    with msg_lock:
        msgs=list(last_msgs)
    return jsonify({
        "uptime":get_uptime(),
        "mode":"REAL" if has_keys else "SIM",
        "time":ist.strftime('%d-%m-%Y %H:%M:%S IST'),
        "total_pnl":sum(bots[s]["pnl"] for s in SYMBOLS),
        "bots":{s:{"spot":bots[s]["spot"],"ema20":int(bots[s]["ema20"]),"supertrend":bots[s]["supertrend"],"in_trade":bots[s]["in_trade"],"side":bots[s]["side"],"symbol_traded":bots[s]["symbol_traded"],"pnl":bots[s]["pnl"]} for s in SYMBOLS},
        "messages":msgs,
        "version":"v3 FIXED - Background + Delta Sync"
    })

if __name__=='__main__': app.run(host='0.0.0.0',port=10000)
