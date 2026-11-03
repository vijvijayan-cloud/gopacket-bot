from flask import Flask, jsonify
import requests, time, hmac, hashlib, json, os
from datetime import datetime, timedelta

app = Flask(__name__)

DELTA_API_KEY = os.getenv("DELTA_API_KEY", "")
DELTA_API_SECRET = os.getenv("DELTA_API_SECRET", "")
BASE_URL = "https://api.india.delta.exchange"

qty = 1
ASSETS = ["BTC","ETH","XAUT"]
states = {a:{"spot":0,"ema20":0,"ema50":0,"history":[],"atr":80,"st":"BULL","in_trade":False,"side":"","entry":0,"symbol":"","highest":0,"pnl":0} for a in ASSETS}

def get_ist(): return datetime.utcnow() + timedelta(hours=5, minutes=30)

def delta_signature(m,p,q,pl):
    ts=str(int(time.time())); msg=m+ts+p+q+pl
    return hmac.new(DELTA_API_SECRET.encode(),msg.encode(),hashlib.sha256).hexdigest(), ts

def get_price(a):
    s=states[a]
    try:
        r=requests.get(f"{BASE_URL}/v2/tickers/{a}USD",timeout=5).json()
        pr=float(r['result']['spot_price'])
        s["history"].append(pr)
        if len(s["history"])>100: s["history"].pop(0)
        if s["ema20"]==0: s["ema20"]=pr; s["ema50"]=pr
        else: s["ema20"]=s["ema20"]*0.95+pr*0.05; s["ema50"]=s["ema50"]*0.98+pr*0.02
        if len(s["history"])>=14:
            tr=[abs(s["history"][i]-s["history"][i-1]) for i in range(1,len(s["history"]))]
            s["atr"]=max(sum(tr[-14:])/14, 80 if a=="BTC" else 15 if a=="ETH" else 5)
        s["spot"]=pr; return pr
    except: return s["spot"] or 77000

def get_st(a):
    s=states[a]
    s["st"]="BULL" if s["ema20"]>s["ema50"] else "BEAR"
    return s["st"]

def get_sym(asset,price,side):
    try:
        r=requests.get(f"{BASE_URL}/v2/products?contract_types=call_options,put_options&underlying_asset_symbols={asset}",timeout=10).json()
        prods=r.get('result',[])
        step=500 if asset=="BTC" else 100 if asset=="ETH" else 10
        tgt=int(price//step)*step
        tgt = tgt-step if side=="CE" else tgt+step
        best=None; bd=1e9
        for p in prods:
            if p.get('contract_type')!=('call_options' if side=="CE" else 'put_options'): continue
            st=float(p.get('strike_price',0)); d=abs(st-tgt)
            if d<bd and st>0: bd=d; best=p
        return best['symbol'] if best else None
    except: return None

def place_order(sym,act):
    try:
        path="/v2/orders"
        pd={"product_symbol":sym,"size":int(qty),"side":"buy" if act=="B" else "sell","order_type":"market_order"}
        ps=json.dumps(pd); sig,ts=delta_signature("POST",path,"",ps)
        hdr={"api-key":DELTA_API_KEY,"timestamp":ts,"signature":sig,"Content-Type":"application/json"}
        r=requests.post(BASE_URL+path,data=ps,headers=hdr,timeout=10)
        res=r.json()
        print(f"ORDER {sym} {act} => {res}")
        return {"success":res.get('success',False),"res":res}
    except Exception as e: return {"success":False,"res":str(e)}

@app.route('/')
def home():
    html="<h1>🚀 MULTI BOT BTC+ETH+XAUT LOCKED</h1>"
    for a in ASSETS:
        p=get_price(a); s=states[a]
        color="🟢 IN TRADE" if s["in_trade"] else "⚪ SCANNING"
        html+=f"<p><b>{a}</b>: ${p:.2f} ST:{s['st']} {color} {s['symbol']} {s['side']} PnL ${s['pnl']:.2f}</p>"
    html+="<p><a href='/status'>STATUS</a> | <a href='/reset'>RESET ALL</a> | <a href='/reset/BTC'>RESET BTC</a> | <a href='/reset/ETH'>RESET ETH</a> | <a href='/reset/XAUT'>RESET XAUT</a></p>"
    html+="<script>setTimeout(()=>location.reload(),15000)</script>"
    return html

@app.route('/reset')
@app.route('/reset/<asset>')
def reset(asset=None):
    if asset and asset in states:
        s=states[asset]; s["in_trade"]=False; s["side"]=""; s["entry"]=0; s["highest"]=0; s["symbol"]=""
        return jsonify({f"RESET {asset}":"Done - Will open new trade on next scan"})
    elif not asset:
        for a in ASSETS:
            s=states[a]; s["in_trade"]=False; s["side"]=""; s["entry"]=0; s["highest"]=0; s["symbol"]=""
        return jsonify({"RESET ALL":"Done"})
    return jsonify({"error":"invalid"})

@app.route('/status')
def status():
    ist=get_ist(); results={}; summ=[]
    for asset in ASSETS:
        s=states[asset]; price=get_price(asset); st=get_st(asset); msg=""
        
        # LOCK: If already in trade, don't open another for same asset
        if not s["in_trade"]:
            side="CE" if st=="BULL" else "PE"
            sym=get_sym(asset,price,side)
            if sym:
                res=place_order(sym,"B")
                if res["success"]:
                    s["side"]=side; s["entry"]=price; s["highest"]=0; s["symbol"]=sym; s["in_trade"]=True
                    msg=f"NEW LIVE {asset} {side} {sym} @ ${price:.1f} ST:{st}"
                else:
                    # Don't spam orders, just scan if failed
                    msg=f"SCANNING {asset} ${price:.1f} ST:{st} Waiting... Order failed: {res['res'].get('error',{}).get('code','') if isinstance(res['res'],dict) else ''}"
            else:
                msg=f"SCANNING {asset} ${price:.1f} ST:{st} No symbol"
        else:
            curr=(price-s["entry"]) if s["side"]=="CE" else (s["entry"]-price)
            if curr>s["highest"]: s["highest"]=curr
            trail=s["highest"]-(s["atr"]*0.5) if s["highest"]>=s["atr"]*0.5 else -s["atr"]
            msg=f"IN TRADE {asset} {s['side']} {s['symbol']} Entry ${s['entry']:.1f} Now ${price:.1f} Move ${curr:.1f} High ${s['highest']:.1f} TrailSL ${trail:.1f}"
            if curr<=trail:
                res=place_order(s["symbol"],"S")
                trade_pnl=trail
                s["pnl"]+=trade_pnl
                s["in_trade"]=False
                msg+=f" -> EXIT P&L ${trade_pnl:.1f} {res['res']}"
        
        results[asset]={"price":price,"st":st,"in_trade":s["in_trade"],"side":s["side"],"symbol":s["symbol"],"profit":msg,"pnl":s["pnl"]}
        summ.append(msg)
    
    return jsonify({"time":ist.strftime("%d-%m-%Y %H:%M:%S IST"),"assets":results,"summary":" | ".join(summ),"mode":"REAL MULTI LOCKED BTC+ETH+XAUT"})

if __name__=='__main__': app.run(host='0.0.0.0',port=10000)
