from flask import Flask, jsonify, request, session, redirect, url_for
import requests, time, hmac, hashlib, json, os, threading
from datetime import datetime, timedelta, timezone

app = Flask(__name__)
app.secret_key = os.getenv("DASHBOARD_SECRET", "delta-bot-secret-123")
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "delta123")
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

# ===== v5.1 - BUTTERFLY INTEGRATED + EXPIRY FIX =====
SETTINGS = {"hard_sl_pct": -15, "trail_start_pct": 15, "trail_gap_pct": 8, "bot_enabled": True, "coins_enabled": {"BTC": True, "ETH": True, "XAUT": True}, "mode": "butterfly", "butterfly_enabled": True, "butterfly_gap_pct": 2.0}
STARTUP_DELAY_SEC = 120
NO_TRADE_HOURS = [0, 1, 2, 3, 4, 5]
HISTORY = []
BUTTERFLY = {"in_trade": False, "is_call": False, "legs": [], "debit": 0, "width": 0, "max_profit": 0, "expiry": "", "entry_time": "", "curr_debit": 0, "pnl_pct": 0}

bots = {}
for sym in SYMBOLS:
    bots[sym] = {"pnl":0,"wins":0,"loss":0,"spot":0,"ema20":0,"ema50":0,"price_history":[],"atr":200,"supertrend":"BULL","in_trade":False,"side":"","entry":0,"symbol_traded":"","highest":0,"entry_premium":0,"curr_premium":0,"highest_pnl_pct":0,"trail_pct":-15}

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
    if b["spot"]>b["ema20"] and b["spot"]>b["ema50"]:
        b["supertrend"]="BULL"
    elif b["spot"]<b["ema20"] and b["spot"]<b["ema50"]:
        b["supertrend"]="BEAR"
    else:
        b["supertrend"]="SIDEWAYS"
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
        path="/v2/positions/margined"
        sig,ts=delta_signature("GET",path,"","")
        headers={"api-key":DELTA_API_KEY,"timestamp":ts,"signature":sig,"Content-Type":"application/json"}
        r=requests.get(BASE_URL+path,headers=headers,timeout=10).json()
        live={}
        results = r.get("result",[])
        if isinstance(results, dict):
            results = results.get("positions",[]) or []
        for p in results:
            sym=p.get("product_symbol","")
            size=float(p.get("size",0))
            if size==0: continue
            if not (sym.startswith("C-") or sym.startswith("P-")):
                continue
            for asset in SYMBOLS:
                if f"-{asset}-" in sym:
                    if asset not in live: live[asset]=[]
                    live[asset].append({"symbol":sym,"size":size,"entry_price":float(p.get("entry_price",0) or 0),"mark_price":float(p.get("mark_price",0) or 0)})
        return live
    except Exception as e:
        print("POS ERR",e)
        return {}

# ===== BUTTERFLY FUNCTIONS - v5.1 FIXED =====
def get_butterfly_legs(price, is_call):
    gap = SETTINGS["butterfly_gap_pct"] / 100
    def r1000(x): return round(x/1000)*1000
    if is_call:
        k1=r1000(price); k2=r1000(price*(1+gap)); k3=r1000(price*(1+gap*2))
    else:
        k1=r1000(price); k2=r1000(price*(1-gap)); k3=r1000(price*(1-gap*2))
    # FIX v5.1: Delta la irukka REAL expiry-a kandupidi - 21 days kitta irukka expiry
    expiry = (get_ist()+timedelta(days=21)).strftime("%d%m%y")
    try:
        r=requests.get(f"{BASE_URL}/v2/products?contract_types=call_options&underlying_asset_symbols=BTC", timeout=15).json()
        now=datetime.utcnow().timestamp()
        best_diff=1e18; best_expiry=None
        for o in r.get('result',[]):
            try:
                exp_str=o.get('settlement_time') or o.get('expiry') or ""
                if not exp_str: continue
                dt=datetime.fromisoformat(exp_str.replace('Z','+00:00'))
                exp=dt.timestamp()
                if exp < now+7*86400: continue
                if exp > now+35*86400: continue
                diff=abs(exp-(now+21*86400))
                if diff<best_diff:
                    best_diff=diff; best_expiry=dt.strftime("%d%m%y")
            except: continue
        if best_expiry: expiry=best_expiry
    except Exception as e:
        print(f"EXPIRY FIND FAIL {e}")
    opt = "C" if is_call else "P"
    s1=f"{opt}-BTC-{int(k1)}-{expiry}"
    s2=f"{opt}-BTC-{int(k2)}-{expiry}"
    s3=f"{opt}-BTC-{int(k3)}-{expiry}"
    print(f"BFLY LEGS {s1} / {s2} / {s3} Expiry {expiry}")
    return [(s1, "B", 1, k1), (s2, "S", 2, k2), (s3, "B", 1, k3)], expiry, abs(k1-k2)

def place_butterfly(price, is_call):
    legs, expiry, width = get_butterfly_legs(price, is_call)
    p1=get_option_premium(legs[0][0]); p2=get_option_premium(legs[1][0]); p3=get_option_premium(legs[2][0])
    debit = p1 - 2*p2 + p3
    print(f"BFLY PREMIUMS p1=${p1:.0f} p2=${p2:.0f} p3=${p3:.0f} Debit=${debit:.0f}")
    if debit <= 0:
        return f"BUTTERFLY SKIP - Debit ${debit:.0f} invalid - p1 ${p1:.0f} p2 ${p2:.0f} p3 ${p3:.0f} - Check Expiry {expiry}"
    if not DELTA_API_KEY or len(DELTA_API_KEY)<10:
        BUTTERFLY.update({"in_trade":True,"is_call":is_call,"legs":[{"symbol":l[0],"action":l[1],"size":l[2],"strike":l[3]} for l in legs],"debit":debit,"width":width,"max_profit":width-debit,"expiry":expiry,"entry_time":get_ist().strftime("%d-%m %H:%M"),"curr_debit":debit,"pnl_pct":0})
        return f"BUTTERFLY SIM ENTRY {'CALL' if is_call else 'PUT'} {legs[0][0]} / {legs[1][0]} / {legs[2][0]} Debit ${debit:.0f} MaxProfit ${width-debit:.0f}"
    results=[]
    for sym, action, size, strike in legs:
        res=place_delta_order(sym, action, size=size)
        results.append(res)
        time.sleep(1)
    ok = all(r.get("status")=="SIMULATION" or r.get("success") for r in results)
    if ok:
        BUTTERFLY.update({"in_trade":True,"is_call":is_call,"legs":[{"symbol":l[0],"action":l[1],"size":l[2],"strike":l[3]} for l in legs],"debit":debit,"width":width,"max_profit":width-debit,"expiry":expiry,"entry_time":get_ist().strftime("%d-%m %H:%M"),"curr_debit":debit,"pnl_pct":0})
        HISTORY.insert(0, {"time": get_ist().strftime("%H:%M:%S"), "sym": "BTC", "symbol": f"BFLY {'CALL' if is_call else 'PUT'} {legs[0][0]}", "reason": f"BFLY ENTRY Debit ${debit:.0f}", "pnl_pct": 0, "pnl_amt": -debit})
        return f"BUTTERFLY REAL ENTRY {'CALL' if is_call else 'PUT'} Debit ${debit:.0f} MaxProfit ${width-debit:.0f}"
    else:
        return f"BUTTERFLY ENTRY FAILED {results}"

def exit_butterfly(reason):
    if not BUTTERFLY["in_trade"]:
        return "No Butterfly to exit"
    for leg in BUTTERFLY["legs"]:
        rev = "S" if leg["action"]=="B" else "B"
        place_delta_order(leg["symbol"], rev, size=leg["size"])
        time.sleep(0.5)
    pnl = BUTTERFLY["curr_debit"] - BUTTERFLY["debit"]
    BUTTERFLY["in_trade"]=False
    BUTTERFLY["legs"]=[]
    HISTORY.insert(0, {"time": get_ist().strftime("%H:%M:%S"), "sym": "BTC", "symbol": "BFLY EXIT", "reason": reason, "pnl_pct": round(BUTTERFLY["pnl_pct"],1), "pnl_amt": round(pnl,2)})
    return f"BUTTERFLY EXIT {reason} PnL ${pnl:.0f}"

def sync_from_exchange():
    live=get_live_positions()
    for sym in SYMBOLS:
        b=bots[sym]
        if sym in live and len(live[sym])>0:
            first=live[sym][0]
            if not b["in_trade"] or b["symbol_traded"] != first["symbol"]:
                b["in_trade"]=True
                b["symbol_traded"]=first["symbol"]
                b["side"]="CE" if first["symbol"].startswith("C-") else "PE"
                if first["entry_price"]>0:
                    b["entry_premium"]=first["entry_price"]
                elif b["entry_premium"]==0:
                    b["entry_premium"]=get_option_premium(b["symbol_traded"])
                b["highest_pnl_pct"]=0
                b["trail_pct"]=SETTINGS["hard_sl_pct"]
            else:
                if first["entry_price"]>0 and abs(first["entry_price"]-b["entry_premium"])/max(b["entry_premium"],0.01) > 0.05:
                    b["entry_premium"]=first["entry_price"]
        else:
            if b["in_trade"]:
                print(f"SYNC CLEAR {sym} - Delta 0, clearing {b['symbol_traded']}")
            b["in_trade"]=False; b["symbol_traded"]=""; b["entry_premium"]=0; b["curr_premium"]=0; b["highest_pnl_pct"]=0; b["trail_pct"]=SETTINGS["hard_sl_pct"]
    return live

def safe_exit(sym, reason, pnl_pct):
    b=bots[sym]
    live=get_live_positions()
    if sym not in live or len(live[sym])==0:
        b["in_trade"]=False; b["symbol_traded"]=""; b["entry_premium"]=0
        return f"EXIT SKIPPED {sym} - No LONG"
    total_size=0
    target_symbol = b["symbol_traded"]
    symbols_to_exit = []
    for x in live[sym]:
        if x["symbol"]==target_symbol:
            total_size+=x["size"]
            symbols_to_exit.append(x)
    if total_size==0:
        for x in live[sym]:
            total_size+=x["size"]
            symbols_to_exit.append(x)
        target_symbol = symbols_to_exit[0]["symbol"] if symbols_to_exit else target_symbol
    res=place_delta_order(target_symbol,"S",size=int(total_size) if total_size>=1 else 1)
    if res.get("status")=="SIMULATION" or res.get("success"):
        pnl_amt = (b["curr_premium"] - b["entry_premium"]) if b["entry_premium"] else 0
        b["pnl"]+=pnl_amt
        if pnl_pct>=0: b["wins"]+=1
        else: b["loss"]+=1
        HISTORY.insert(0, {"time": get_ist().strftime("%H:%M:%S"), "sym": sym, "symbol": target_symbol, "reason": reason, "pnl_pct": round(pnl_pct,1), "pnl_amt": round(pnl_amt,2)})
        if len(HISTORY)>50: HISTORY.pop()
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
    current_hour = get_ist().hour
    if SETTINGS["mode"]=="butterfly" and SETTINGS["butterfly_enabled"] and SETTINGS["bot_enabled"]:
        btc_price=get_price("BTC"); st=get_supertrend("BTC")
        if not BUTTERFLY["in_trade"]:
            if current_hour in NO_TRADE_HOURS:
                msgs.append(f"BFLY TIME FILTER - Night {current_hour}:00 IST No Entry")
            elif st=="BULL":
                msgs.append(place_butterfly(btc_price, True))
            elif st=="BEAR":
                msgs.append(place_butterfly(btc_price, False))
            else:
                msgs.append(f"BFLY SCANNING BTC ${btc_price:.0f} ST:{st} - SIDEWAYS No Trade")
        else:
            legs=BUTTERFLY["legs"]
            if len(legs)==3:
                p1=get_option_premium(legs[0]["symbol"]); p2=get_option_premium(legs[1]["symbol"]); p3=get_option_premium(legs[2]["symbol"])
                curr_debit=p1-2*p2+p3
                if curr_debit>0: BUTTERFLY["curr_debit"]=curr_debit
                pnl_pct = ((BUTTERFLY["debit"]-curr_debit)/BUTTERFLY["debit"]*100) if BUTTERFLY["debit"]>0 else 0
                BUTTERFLY["pnl_pct"]=pnl_pct
                if pnl_pct <= -50:
                    msgs.append(exit_butterfly(f"BFLY HARD SL -50% Debit ${curr_debit:.0f}"))
                elif pnl_pct >= 50:
                    msgs.append(exit_butterfly(f"BFLY TARGET +50% Debit ${curr_debit:.0f}"))
                else:
                    msgs.append(f"BFLY IN TRADE {'CALL' if BUTTERFLY['is_call'] else 'PUT'} Exp {BUTTERFLY['expiry']} Debit Entry ${BUTTERFLY['debit']:.0f} Curr ${curr_debit:.0f} PNL {pnl_pct:.1f}% MaxProfit ${BUTTERFLY['max_profit']:.0f}")
        return msgs + [f"MODE: BUTTERFLY | BTC ${bots['BTC']['spot']:.0f} ST:{bots['BTC']['supertrend']}"]
    for sym in SYMBOLS:
        price=get_price(sym); st=get_supertrend(sym); b=bots[sym]
        if not b["in_trade"]:
            if not SETTINGS["bot_enabled"]:
                msgs.append(f"PAUSED {sym} - Bot Stopped from Dashboard")
                continue
            if not SETTINGS["coins_enabled"].get(sym, True):
                msgs.append(f"DISABLED {sym} - Coin OFF in Dashboard")
                continue
            if sym in live and len(live[sym])>0:
                b["in_trade"]=True
                b["symbol_traded"]=live[sym][0]["symbol"]
                b["side"]="CE" if live[sym][0]["symbol"].startswith("C-") else "PE"
                msgs.append(f"BLOCKED ENTRY {sym} - Already {len(live[sym])} in Delta: {b['symbol_traded']}")
                continue
            if current_hour in NO_TRADE_HOURS:
                msgs.append(f"TIME FILTER {sym} - Night {current_hour}:00 IST No Entry, Holding")
                continue
            if st=="BULL" and price>b["ema20"] and price>b["ema50"]:
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
                    b["entry_premium"]=prem; b["curr_premium"]=prem; b["highest_pnl_pct"]=0; b["trail_pct"]=SETTINGS["hard_sl_pct"]
                    msgs.append(f"NEW ENTRY {sym} CALL {temp} @ Spot ${price:.0f} Premium ${prem:.2f}")
                else:
                    msgs.append(f"ENTRY FAILED {sym} {temp} {res}")
            elif st=="BEAR" and price<b["ema20"] and price<b["ema50"]:
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
                    b["entry_premium"]=prem; b["curr_premium"]=prem; b["highest_pnl_pct"]=0; b["trail_pct"]=SETTINGS["hard_sl_pct"]
                    msgs.append(f"NEW ENTRY {sym} PUT {temp} @ Spot ${price:.0f} Premium ${prem:.2f}")
                else:
                    msgs.append(f"ENTRY FAILED {sym} {temp} {res}")
            else:
                msgs.append(f"SCANNING {sym} ${price:.0f} ST:{st} - MA Filter: No Trade")
        else:
            live_now = live.get(sym,[])
            if len(live_now)==0:
                b["in_trade"]=False; b["symbol_traded"]=""; b["entry_premium"]=0
                msgs.append(f"SYNC EXIT {sym} - Delta closed, bot cleared")
                continue
            curr_prem=get_option_premium(b["symbol_traded"])
            if curr_prem>0: b["curr_premium"]=curr_prem
            elif live_now[0].get("mark_price",0)>0:
                b["curr_premium"]=live_now[0]["mark_price"]
            if b["entry_premium"]>0 and b["curr_premium"]>0:
                pnl_pct = ((b["curr_premium"] - b["entry_premium"]) / b["entry_premium"]) * 100
            else: pnl_pct = 0
            if pnl_pct > b["highest_pnl_pct"]:
                b["highest_pnl_pct"]=pnl_pct
                if b["highest_pnl_pct"] >= SETTINGS["trail_start_pct"]:
                    b["trail_pct"]=b["highest_pnl_pct"] - SETTINGS["trail_gap_pct"]
                else: b["trail_pct"]=SETTINGS["hard_sl_pct"]
            if pnl_pct <= SETTINGS["hard_sl_pct"]:
                msgs.append(safe_exit(sym, f"HARD SL {SETTINGS['hard_sl_pct']}% HIT", pnl_pct))
            elif b["highest_pnl_pct"] >= SETTINGS["trail_start_pct"] and pnl_pct <= b["trail_pct"]:
                msgs.append(safe_exit(sym, f"TRAIL HIT Trail {b['trail_pct']:.0f}%", pnl_pct))
            else:
                dup = len(live.get(sym,[])) if sym in live else 0
                msgs.append(f"IN TRADE {sym} {b['side']} Premium ${b['curr_premium']:.2f} PNL {pnl_pct:.1f}% High {b['highest_pnl_pct']:.1f}% Trail {b['trail_pct']:.0f}% DeltaPos {dup} Entry ${b['entry_premium']:.2f}")
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

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method=='POST':
        if request.form.get('password')==DASHBOARD_PASSWORD:
            session['logged']=True
            return redirect('/')
        return "<h2>Wrong Password</h2><a href='/login'>Try Again</a>"
    return """<div style='max-width:320px;margin:100px auto;font-family:sans-serif;text-align:center'><h2>🔐 Delta Bot Dashboard</h2><form method='post'><input name='password' type='password' placeholder='Password' style='padding:12px;width:100%;font-size:16px'><br><br><button style='padding:12px 30px;background:#2563eb;color:white;border:none;border-radius:8px;font-size:16px'>Login</button></form><p style='color:#888'>Default: delta123</p></div>"""

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

@app.route('/')
def home():
    if not session.get('logged'): return redirect('/login')
    ist=get_ist(); has_keys=bool(DELTA_API_KEY and len(DELTA_API_KEY)>10)
    with msg_lock: msgs=list(last_msgs)
    total_pnl = sum(bots[s]["pnl"] for s in SYMBOLS)
    bfly_html=""
    if BUTTERFLY["in_trade"]:
        legs_str="<br>".join([f"{l['action']} {l['size']}x {l['symbol']} @ {l['strike']:.0f}" for l in BUTTERFLY["legs"]])
        bfly_html=f"""<div style='background:#fef3c7;border:2px solid #f59e0b;border-radius:12px;padding:16px;margin-bottom:16px'><h3 style='margin:0'>🦋 BUTTERFLY IN TRADE - {'CALL' if BUTTERFLY['is_call'] else 'PUT'} | Exp {BUTTERFLY['expiry']}</h3><div style='font-size:13px;margin:8px 0'>{legs_str}</div><div>Debit Entry ${BUTTERFLY['debit']:.0f} | Curr ${BUTTERFLY['curr_debit']:.0f} | Max Profit ${BUTTERFLY['max_profit']:.0f} | PNL {BUTTERFLY['pnl_pct']:.1f}%</div><button onclick="closeBfly()" style='margin-top:10px;padding:10px 20px;background:#dc2626;color:white;border:none;border-radius:8px'>CLOSE BUTTERFLY</button></div>"""
    else:
        bfly_html=f"""<div style='background:#f0fdf4;border:2px solid #16a34a;border-radius:12px;padding:16px;margin-bottom:16px'><h3 style='margin:0'>🦋 BUTTERFLY - FLAT - Waiting for Signal</h3><p style='margin:8px 0;font-size:13px'>Gap {SETTINGS['butterfly_gap_pct']}% | Expiry 21 days | SL -50% Debit | Target +50% Debit</p></div>"""
    live_pnl_html=""
    for sym in SYMBOLS:
        b=bots[sym]
        pnl_pct = ((b["curr_premium"]-b["entry_premium"])/b["entry_premium"]*100) if b["entry_premium"]>0 and b["curr_premium"]>0 and b["in_trade"] else 0
        color = "#16a34a" if pnl_pct>=0 else "#dc2626"
        status = f"InTrade {b['side']} {b['symbol_traded']}" if b["in_trade"] else "FLAT"
        live_pnl_html+=f"""
        <div style='background:white;border-radius:12px;padding:16px;box-shadow:0 2px 8px rgba(0,0,0,0.08)'>
          <div style='display:flex;justify-content:space-between'><b style='font-size:18px'>{sym}</b><span style='background:#eef2ff;padding:4px 10px;border-radius:20px;font-size:12px'>{b['supertrend']}</span></div>
          <div style='font-size:24px;font-weight:bold;margin:8px 0'>${b['spot']:.2f}</div>
          <div style='font-size:13px;color:#666'>EMA {b['ema20']:.0f} / {b['ema50']:.0f}</div>
          <div style='margin:10px 0;font-size:13px'>{status}<br>Entry ${b['entry_premium']:.2f} | Curr ${b['curr_premium']:.2f}</div>
          <div style='font-size:20px;font-weight:bold;color:{color}'>PNL {pnl_pct:.1f}%</div>
          <div style='font-size:12px;color:#888'>High {b['highest_pnl_pct']:.1f}% | Trail {b['trail_pct']:.0f}%</div>
          <button onclick="closeOne('{sym}')" style='margin-top:10px;width:100%;padding:10px;background:#dc2626;color:white;border:none;border-radius:8px'>CLOSE {sym}</button>
        </div>"""
    hist_html=""
    for h in HISTORY[:10]:
        hist_html+=f"<div style='display:flex;justify-content:space-between;padding:8px;border-bottom:1px solid #eee;font-size:13px'><span>{h['time']} {h['sym']} {h['symbol']}</span><span>{h['reason']}</span><b style='color:{'#16a34a' if h['pnl_pct']>=0 else '#dc2626'}'>{h['pnl_pct']}% (${h['pnl_amt']})</b></div>"
    if not hist_html: hist_html="<p style='color:#888;padding:10px'>No exits yet today</p>"
    html=f"""
    <html><head><meta name='viewport' content='width=device-width,initial-scale=1'><title>Delta Bot Dashboard v5.1</title></head>
    <body style='font-family:sans-serif;background:#f1f5f9;margin:0;padding:16px'>
    <div style='max-width:900px;margin:0 auto'>
    <div style='display:flex;justify-content:space-between;align-items:center'><h1 style='margin:0'>🤖 Delta Bot v5.1 Butterfly</h1><a href='/logout' style='color:#666'>Logout</a></div>
    <p>Mode: {'<b style=color:green>REAL ✅</b>' if has_keys else 'SIM'} | Uptime {get_uptime()} | Now {ist.strftime('%H:%M:%S IST')} | Total PNL ${total_pnl:.2f} | <b>Mode: {SETTINGS['mode'].upper()}</b></p>
    {bfly_html}
    <div style='background:white;border-radius:12px;padding:16px;box-shadow:0 2px 8px rgba(0,0,0,0.08);display:flex;gap:10px;flex-wrap:wrap'>
      <button onclick="toggleBot()" style='padding:12px 20px;border:none;border-radius:8px;font-weight:bold;background:{'#dc2626' if SETTINGS['bot_enabled'] else '#16a34a'};color:white'>{'🔴 STOP BOT' if SETTINGS['bot_enabled'] else '🟢 START BOT'}</button>
      <button onclick="toggleMode()" style='padding:12px 20px;border:none;border-radius:8px;font-weight:bold;background:#7c3aed;color:white'>MODE: {SETTINGS['mode'].upper()} - SWITCH</button>
      <button onclick="closeAll()" style='padding:12px 20px;border:none;border-radius:8px;font-weight:bold;background:#f59e0b;color:white'>🚨 CLOSE ALL</button>
      <label>SL <select id='sl' onchange="saveSettings()"><option value='-15' {'selected' if SETTINGS['hard_sl_pct']==-15 else ''}>-15%</option><option value='-20' {'selected' if SETTINGS['hard_sl_pct']==-20 else ''}>-20%</option><option value='-25' {'selected' if SETTINGS['hard_sl_pct']==-25 else ''}>-25%</option><option value='-30' {'selected' if SETTINGS['hard_sl_pct']==-30 else ''}>-30%</option></select></label>
      <label>Trail Start <select id='ts' onchange="saveSettings()"><option value='15' {'selected' if SETTINGS['trail_start_pct']==15 else ''}>+15%</option><option value='20' {'selected' if SETTINGS['trail_start_pct']==20 else ''}>+20%</option><option value='30' {'selected' if SETTINGS['trail_start_pct']==30 else ''}>+30%</option><option value='40' {'selected' if SETTINGS['trail_start_pct']==40 else ''}>+40%</option></select></label>
    </div>
    <div style='display:flex;gap:10px;margin:12px 0;flex-wrap:wrap'>
      <label style='background:white;padding:10px 14px;border-radius:20px'><input type='checkbox' id='cBTC' {'checked' if SETTINGS['coins_enabled']['BTC'] else ''} onchange="saveSettings()"> BTC</label>
      <label style='background:white;padding:10px 14px;border-radius:20px'><input type='checkbox' id='cETH' {'checked' if SETTINGS['coins_enabled']['ETH'] else ''} onchange="saveSettings()"> ETH</label>
      <label style='background:white;padding:10px 14px;border-radius:20px'><input type='checkbox' id='cXAUT' {'checked' if SETTINGS['coins_enabled']['XAUT'] else ''} onchange="saveSettings()"> XAUT</label>
      <span style='padding:10px'>Bot: {'<b style=color:green>RUNNING</b>' if SETTINGS['bot_enabled'] else '<b style=color:red>STOPPED</b>'}</span>
    </div>
    <div style='display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px'>{live_pnl_html}</div>
    <div style='background:white;border-radius:12px;padding:16px;margin-top:16px'><h3 style='margin:0 0 10px'>📜 History (Today)</h3>{hist_html}</div>
    <div style='background:white;border-radius:12px;padding:16px;margin-top:12px'><h3 style='margin:0 0 10px'>📋 Live Logs</h3>{'<br>'.join(msgs)}</div>
    </div>
    <script>
    async function toggleBot(){{ await fetch('/api/toggle_bot',{{method:'POST'}}); location.reload(); }}
    async function toggleMode(){{ await fetch('/api/toggle_mode',{{method:'POST'}}); location.reload(); }}
    async function closeBfly(){{ if(!confirm('Close Butterfly?')) return; let r=await fetch('/api/close_butterfly',{{method:'POST'}}); alert(await r.text()); location.reload(); }}
    async function closeAll(){{ if(!confirm('Close ALL positions in Delta?')) return; let r=await fetch('/api/close_all',{{method:'POST'}}); alert(await r.text()); location.reload(); }}
    async function closeOne(sym){{ if(!confirm('Close '+sym+'?')) return; let r=await fetch('/api/close/'+sym,{{method:'POST'}}); alert(await r.text()); location.reload(); }}
    async function saveSettings(){{ let d={{hard_sl_pct:parseInt(document.getElementById('sl').value), trail_start_pct:parseInt(document.getElementById('ts').value), coins_enabled:{{BTC:document.getElementById('cBTC').checked, ETH:document.getElementById('cETH').checked, XAUT:document.getElementById('cXAUT').checked}}}}; await fetch('/api/settings',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(d)}}); }}
    setTimeout(()=>location.reload(),10000);
    </script>
    </body></html>
    """
    return html

@app.route('/api/toggle_bot', methods=['POST'])
def api_toggle():
    if not session.get('logged'): return "Login required", 401
    SETTINGS["bot_enabled"] = not SETTINGS["bot_enabled"]
    return f"Bot {'STARTED' if SETTINGS['bot_enabled'] else 'STOPPED'}"

@app.route('/api/toggle_mode', methods=['POST'])
def api_toggle_mode():
    if not session.get('logged'): return "Login required", 401
    SETTINGS["mode"] = "single" if SETTINGS["mode"]=="butterfly" else "butterfly"
    return f"Mode switched to {SETTINGS['mode']}"

@app.route('/api/close_butterfly', methods=['POST'])
def api_close_bfly():
    if not session.get('logged'): return "Login required", 401
    return exit_butterfly("MANUAL CLOSE BFLY")

@app.route('/api/settings', methods=['POST'])
def api_settings():
    if not session.get('logged'): return "Login required", 401
    d = request.json or {}
    if "hard_sl_pct" in d: SETTINGS["hard_sl_pct"]=int(d["hard_sl_pct"])
    if "trail_start_pct" in d: SETTINGS["trail_start_pct"]=int(d["trail_start_pct"])
    if "trail_gap_pct" in d: SETTINGS["trail_gap_pct"]=int(d["trail_gap_pct"])
    if "coins_enabled" in d: SETTINGS["coins_enabled"].update(d["coins_enabled"])
    return jsonify(SETTINGS)

@app.route('/api/close_all', methods=['POST'])
def api_close_all():
    if not session.get('logged'): return "Login required", 401
    outs=[]
    if BUTTERFLY["in_trade"]:
        outs.append(exit_butterfly("MANUAL CLOSE ALL BFLY"))
    live=get_live_positions()
    for sym in SYMBOLS:
        if sym in live:
            b=bots[sym]
            pnl_pct = ((b["curr_premium"]-b["entry_premium"])/b["entry_premium"]*100) if b["entry_premium"]>0 and b["curr_premium"]>0 else 0
            outs.append(safe_exit(sym, "MANUAL CLOSE ALL", pnl_pct))
    return " | ".join(outs) if outs else "No positions to close"

@app.route('/api/close/<sym>', methods=['POST'])
def api_close_one(sym):
    if not session.get('logged'): return "Login required", 401
    if sym not in SYMBOLS: return "Invalid", 400
    b=bots[sym]
    pnl_pct = ((b["curr_premium"]-b["entry_premium"])/b["entry_premium"]*100) if b["entry_premium"]>0 and b["curr_premium"]>0 else 0
    return safe_exit(sym, "MANUAL CLOSE", pnl_pct)

@app.route('/api/butterfly')
def api_butterfly():
    if not session.get('logged'): return redirect('/login')
    return jsonify(BUTTERFLY)

@app.route('/status')
def status():
    if not session.get('logged'): return redirect('/login')
    ist=get_ist(); has_keys=bool(DELTA_API_KEY and len(DELTA_API_KEY)>10)
    with msg_lock: msgs=list(last_msgs)
    return jsonify({"uptime":get_uptime(),"mode":"REAL" if has_keys else "SIM","time":ist.strftime('%d-%m-%Y %H:%M:%S IST'),"total_pnl":sum(bots[s]["pnl"] for s in SYMBOLS),"settings":SETTINGS,"butterfly":BUTTERFLY,"bots":{s:{"spot":bots[s]["spot"],"ema20":int(bots[s]["ema20"]),"supertrend":bots[s]["supertrend"],"in_trade":bots[s]["in_trade"],"side":bots[s]["side"],"symbol_traded":bots[s]["symbol_traded"],"entry_premium":bots[s]["entry_premium"],"curr_premium":bots[s]["curr_premium"],"pnl":bots[s]["pnl"]} for s in SYMBOLS},"messages":msgs,"history":HISTORY,"version":"v5.1 Butterfly Integrated + Expiry Fix"})

if __name__=='__main__': app.run(host='0.0.0.0',port=10000)
