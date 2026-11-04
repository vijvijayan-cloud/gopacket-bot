from flask import Flask, jsonify
import requests, time, hmac, hashlib, json, os, threading
from datetime import datetime, timedelta

app = Flask(__name__)
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
HARD_SL_PCT = -25
TRAIL_START_PCT = 30
TRAIL_GAP_PCT = 15
STARTUP_DELAY_SEC = 120

bots = {}
for sym in SYMBOLS:
    bots[sym] = {"pnl":0,"wins":0,"loss":0,"spot":0,"ema20":0,"ema50":0,"price_history":[],"atr":200,"supertrend":"BULL","in_trade":False,"side":"","entry":0,"symbol_traded":"","highest":0,"entry_premium":0,"curr_premium":0,"highest_pnl_pct":0,"trail_pct":-25}

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
    expiry = (get_ist()+timedelta(days=1)).strftime("%d%m%y")
    if asset=="BTC":
        strike = int(price//1000)*1000
        strike = strike-1000 if side=="CE" else strike+1000
    elif asset=="ETH":
        strike = int(price//10)*10
        strike = strike-10 if side=="CE" else strike+10
    else:
        strike = int(price//10)*10
        strike = strike-10 if side=="CE" else strike+10
    opt = "C" if side=="CE" else "P"
    return f"{opt}-{asset}-{strike}-{expiry}"

def get_option_premium(symbol):
    try:
        r = requests.get(f"{BASE_URL}/v2/tickers/{symbol}", timeout=5).json()
        res = r.get("result", {})
        for k in ["mark_price","last_price","close","spot_price"]:
            if k in res and res[k]:
                return float(res[k])
        return 0
    except: return 0

def place_delta_order(symbol, action, size=BASE_LOT):
    if not DELTA_API_KEY or len(DELTA_API_KEY)<10:
        return {"status":"SIMULATION"}
    try:
        path="/v2/orders"
        payload_dict={"product_symbol":symbol,"size":size,"side":"buy" if action=="B" else "sell","order_type":"market_order"}
        payload_str=json.dumps(payload_dict)
        sig,ts=delta_signature("POST",path,"",payload_str)
        headers={"api-key":DELTA_API_KEY,"timestamp":ts,"signature":sig,"Content-Type":"application/json"}
        r=requests.post(BASE_URL+path,data=payload_str,headers=headers,timeout=10)
        return r.json()
    except Exception as e:
        return {"error":str(e)}

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
                    if asset not in live: live[asset]=[]
                    live[asset].append({"symbol":sym,"size":size,"entry_price":float(p.get("entry_price",0))})
        return live
    except Exception as e:
        print("POS ERR",e)
        return {}

def sync_from_exchange():
    live=get_live_positions()
    for sym in SYMBOLS:
        b=bots[sym]
        if sym in live and not b["in_trade"]:
            first=live[sym][0]
            b["in_trade"]=True
            b["symbol_traded"]=first["symbol"]
            b["side"]="CE" if first["symbol"].startswith("C-") else "PE"
            if b["entry_premium"]==0:
                b["entry_premium"]=first["entry_price"]
                if b["entry_premium"]==0:
                    b["entry_premium"]=get_option_premium(b["symbol_traded"])
            b["highest_pnl_pct"]=0
            b["trail_pct"]=HARD_SL_PCT
    return live

def safe_exit(sym, reason, pnl_pct):
    b=bots[sym]
    live=get_live_positions()
    if sym not in live or len(live[sym])==0:
        b["in_trade"]=False; b["symbol_traded"]=""; b["entry_premium"]=0
        return f"EXIT SKIPPED {sym} - No LONG, RAM reset (SHORT prevented)"
    total_size=sum([x["size"] for x in live[sym]])
    res=place_delta_order(b["symbol_traded"],"S",size=int(total_size) if total_size>=1 else 1)
    if res.get("status")=="SIMULATION" or res.get("success"):
        pnl_amt = (b["curr_premium"] - b["entry_premium"]) if b["entry_premium"] else 0
        b["pnl"]+=pnl_amt
        if pnl_pct>=0: b["wins"]+=1
        else: b["loss"]+=1
        b["in_trade"]=False; b["symbol_traded"]=""; b["entry_premium"]=0
        return f"EXIT {sym} {reason} PNL {pnl_pct:.1f}% (${pnl_amt:.2f}) Size {total_size}"
    else:
        return f"EXIT FAILED {sym} {res}"

def run_trading_logic():
    msgs=[]
    up_sec = (datetime.utcnow() - start_time).total_seconds()
    live = get_live_positions()
    if up_sec < STARTUP_DELAY_SEC:
        for sym in SYMBOLS:
            get_price(sym); get_supertrend(sym)
        sync_from_exchange()
        return [f"STARTUP WAIT {int(STARTUP_DELAY_SEC-up_sec)}s - Building EMA, No Entry Yet. Delta Live: {sum(len(v) for v in live.values())} pos"]
    live=sync_from_exchange()
    for sym in SYMBOLS:
        price=get_price(sym); st=get_supertrend(sym); b=bots[sym]
        if not b["in_trade"]:
            if sym in live and len(live[sym])>0:
                b["in_trade"]=True
                b["symbol_traded"]=live[sym][0]["symbol"]
                b["side"]="CE" if live[sym][0]["symbol"].startswith("C-") else "PE"
                msgs.append(f"BLOCKED ENTRY {sym} - Already {len(live[sym])} position(s) in Delta: {b['symbol_traded']} - NOT buying duplicate")
                continue
            if st=="BULL" and price>b["ema20"]:
                temp=get_options_symbol(price,"CE",sym)
                live2=get_live_positions()
                if sym in live2 and len(live2[sym])>0:
                    msgs.append(f"BLOCKED ENTRY {sym} - Delta already has {live2[sym][0]['symbol']}")
                    continue
                res=place_delta_order(temp,"B")
                if res.get("status")=="SIMULATION" or res.get("success"):
                    time.sleep(1)
                    prem=get_option_premium(temp)
                    if prem==0: prem=price*0.01
                    b["side"]="CE"; b["entry"]=price; b["highest"]=0; b["symbol_traded"]=temp; b["in_trade"]=True
                    b["entry_premium"]=prem; b["curr_premium"]=prem; b["highest_pnl_pct"]=0; b["trail_pct"]=HARD_SL_PCT
                    msgs.append(f"NEW ENTRY {sym} CALL {temp} @ Spot ${price:.0f} Premium ${prem:.2f}")
                else:
                    msgs.append(f"ENTRY FAILED {sym} {temp} {res}")
            elif st=="BEAR" and price<b["ema20"]:
                temp=get_options_symbol(price,"PE",sym)
                live2=get_live_positions()
                if sym in live2 and len(live2[sym])>0:
                    msgs.append(f"BLOCKED ENTRY {sym} - Delta already has {live2[sym][0]['symbol']}")
                    continue
                res=place_delta_order(temp,"B")
                if res.get("status")=="SIMULATION" or res.get("success"):
                    time.sleep(1)
                    prem=get_option_premium(temp)
                    if prem==0: prem=price*0.01
                    b["side"]="PE"; b["entry"]=price; b["highest"]=price; b["symbol_traded"]=temp; b["in_trade"]=True
                    b["entry_premium"]=prem; b["curr_premium"]=prem; b["highest_pnl_pct"]=0; b["trail_pct"]=HARD_SL_PCT
                    msgs.append(f"NEW ENTRY {sym} PUT {temp} @ Spot ${price:.0f} Premium ${prem:.2f}")
                else:
                    msgs.append(f"ENTRY FAILED {sym} {temp} {res}")
            else:
                msgs.append(f"SCANNING {sym} ${price:.0f} ST:{st}")
        else:
            curr_prem=get_option_premium(b["symbol_traded"])
            if curr_prem>0: b["curr_premium"]=curr_prem
            if b["entry_premium"]>0 and b["curr_premium"]>0:
                pnl_pct = ((b["curr_premium"] - b["entry_premium"]) / b["entry_premium"]) * 100
            else: pnl_pct = 0
            if pnl_pct > b["highest_pnl_pct"]:
                b["highest_pnl_pct"]=pnl_pct
                if b["highest_pnl_pct"] >= TRAIL_START_PCT:
                    b["trail_pct"]=b["highest_pnl_pct"] - TRAIL_GAP_PCT
                else: b["trail_pct"]=HARD_SL_PCT
            if pnl_pct <= HARD_SL_PCT:
                msgs.append(safe_exit(sym, f"HARD SL {HARD_SL_PCT}% HIT", pnl_pct))
            elif b["highest_pnl_pct"] >= TRAIL_START_PCT and pnl_pct <= b["trail_pct"]:
                msgs.append(safe_exit(sym, f"TRAIL HIT Trail {b['trail_pct']:.0f}%", pnl_pct))
            else:
                dup = len(live.get(sym,[])) if sym in live else 0
                msgs.append(f"IN TRADE {sym} {b['side']} Premium ${b['curr_premium']:.2f} PNL {pnl_pct:.1f}% High {b['highest_pnl_pct']:.1f}% Trail {b['trail_pct']:.0f}% DeltaPos {dup}")
    return msgs

def background_loop():
    global last_msgs
    while True:
        try:
            msgs=run_trading_logic()
            with msg_lock: last_msgs=msgs
            time.sleep(15)
        except Exception as e:
            print("LOOP ERR",e)
            time.sleep(10)

threading.Thread(target=background_loop, daemon=True).start()

@app.route('/')
def home():
    ist=get_ist(); has_keys=bool(DELTA_API_KEY and len(DELTA_API_KEY)>10)
    with msg_lock: msgs=list(last_msgs)
    html=f"<h1>DELTA BOT v3.2 LIVE ✅ Uptime: {get_uptime()}</h1><p>Mode: {'REAL ✅' if has_keys else 'SIM'} | Now: {ist.strftime('%H:%M:%S IST')}</p><p><b>SL -25% | Trail Start +30% | Trail Gap 15% | Duplicate Protection ON | 1 Bot Only</b></p><hr>"
    for sym in SYMBOLS:
        b=bots[sym]; html+=f"<p><b>{sym}</b>: ${b['spot']:.2f} EMA {b['ema20']:.0f}/{b['ema50']:.0f} ST {b['supertrend']} InTrade:{b['in_trade']} {b['side']} | {b['symbol_traded']} Prem ${b['curr_premium']:.2f}</p>"
    html+="<hr>"+"<br>".join(msgs)+"<p><a href='/status'>JSON STATUS</a></p><script>setTimeout(()=>location.reload(),10000)</script>"
    return html

@app.route('/status')
def status():
    ist=get_ist(); has_keys=bool(DELTA_API_KEY and len(DELTA_API_KEY)>10)
    with msg_lock: msgs=list(last_msgs)
    return jsonify({"uptime":get_uptime(),"mode":"REAL" if has_keys else "SIM","time":ist.strftime('%d-%m-%Y %H:%M:%S IST'),"total_pnl":sum(bots[s]["pnl"] for s in SYMBOLS),"settings":{"hard_sl_pct":HARD_SL_PCT,"trail_start_pct":TRAIL_START_PCT,"trail_gap_pct":TRAIL_GAP_PCT,"fixed_target":"NONE - Trail Only","duplicate_protection":"ON"},"bots":{s:{"spot":bots[s]["spot"],"ema20":int(bots[s]["ema20"]),"supertrend":bots[s]["supertrend"],"in_trade":bots[s]["in_trade"],"side":bots[s]["side"],"symbol_traded":bots[s]["symbol_traded"],"entry_premium":bots[s]["entry_premium"],"curr_premium":bots[s]["curr_premium"],"pnl":bots[s]["pnl"]} for s in SYMBOLS},"messages":msgs,"version":"v3.2 FINAL - Premium SL + Trail + Duplicate Protection + BTC 1000 Fix"})

if __name__=='__main__': app.run(host='0.0.0.0',port=10000)
