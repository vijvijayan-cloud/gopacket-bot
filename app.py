from flask import Flask, redirect, request, jsonify
from datetime import datetime, timedelta
import random, os, json, time
try:
    import requests
    HAS_REQUESTS = True
except:
    HAS_REQUESTS = False
    requests = None

app = Flask(__name__)

CLIENT_ID = "SKY59589_U"
USER_ID = "SKY59589"
REDIRECT_URL = "https://gopacket-bot-1.onrender.com/callback"
BASE_URL = "https://skypro.skybroking.com/NorenWClientTP/"

qty=65; pnl=0; wins=0; loss=0; spot=24500; ema20=24500; ema50=24500
in_trade=False; side=""; entry_spot=0; symbol_traded=""; highest=0; order_id=""

def get_ist(): return datetime.utcnow() + timedelta(hours=5, minutes=30)
def get_api_token(): return os.getenv("SKY_API_TOKEN","") or os.getenv("SKY_TOKEN","")
def get_secret(): return os.getenv("SKY_SECRET","")

def place_real_order(tsym, buy_sell, qty):
    global order_id
    token=get_api_token()
    if not token or not HAS_REQUESTS: return {"status":"SIMULATION"}
    try:
        jdata={"uid":USER_ID,"actid":USER_ID,"exch":"NFO","tsym":tsym,"qty":str(qty),"prc":"0","prctyp":"MKT","trantype":buy_sell,"ret":"DAY","prd":"M","ordersource":"API"}
        data={"jData":json.dumps(jdata),"jKey":token}
        resp=requests.post(f"{BASE_URL}PlaceOrder",data=data,timeout=10)
        result=resp.json(); order_id=str(result.get("norenordno","")); return result
    except Exception as e: return {"error":str(e)}

def get_itm1_symbol(s, side):
    base=int(s//50)*50; strike=base-50 if side=="CE" else base+50; return f"NIFTY{strike}{side}"

@app.route('/')
def home():
    ist=get_ist(); token=get_api_token(); secret=get_secret()
    status="REAL READY" if token and HAS_REQUESTS else "SIMULATION"
    if not secret: status+=" - SET SKY_SECRET"
    if not token: status+=" - LOGIN FOR TOKEN"
    return f"<h1>65=1LOT BOTH CE/PE - {status}</h1><p>Time: {ist.strftime('%d-%m-%Y %H:%M:%S IST')} IST OPEN 13:13</p><p>P&L: Rs.{pnl} Wins:{wins} Loss:{loss} Order:{order_id}</p><p>User:{USER_ID} Token:{'SET' if token else 'NOT'} Secret:{'SET' if secret else 'NOT'}</p><p><a href='/status'>STATUS LIVE</a> | <a href='/login'>LOGIN FOR TOKEN</a></p>"

@app.route('/status')
def status_route():
    global pnl,wins,loss,spot,ema20,ema50,in_trade,side,entry_spot,symbol_traded,highest
    ist=get_ist(); last_ist=ist.strftime("%d-%m-%Y %H:%M:%S IST"); mins=ist.hour*60+ist.minute
    spot+=random.choice([-8,-4,4,8]); ema20=ema20*0.95+spot*0.05; ema50=ema50*0.98+spot*0.02
    trend="BULL" if ema20>ema50 else "BEAR"; token_set=bool(get_api_token())
    if mins<615: profit=f"WAITING 10:15 IST - NIFTY {int(spot)} Trend {trend} Time {last_ist}"
    elif mins>930: profit=f"CLOSED 15:30 - P&L Rs.{pnl} W{wins} L{loss} Time {last_ist}"
    else:
        if not in_trade:
            if spot>ema20 and random.random()>0.82:
                in_trade=True; side="CE"; entry_spot=spot; highest=0; symbol_traded=get_itm1_symbol(spot,"CE")
                result=place_real_order(symbol_traded,"B",qty); profit=f"NEW ENTRY {side} {symbol_traded} Entry {int(entry_spot)} Result {result} Time {last_ist}"
            elif spot<ema20 and random.random()>0.82:
                in_trade=True; side="PE"; entry_spot=spot; highest=0; symbol_traded=get_itm1_symbol(spot,"PE")
                result=place_real_order(symbol_traded,"B",qty); profit=f"NEW ENTRY {side} {symbol_traded} Entry {int(entry_spot)} Result {result} Time {last_ist}"
            else: profit=f"SCANNING {int(spot)} {trend} EMA {int(ema20)}/{int(ema50)} Time {last_ist} REAL={token_set}"
        else:
            curr=(spot-entry_spot) if side=="CE" else (entry_spot-spot)
            if curr>highest: highest=curr
            trail_sl=highest-1 if highest>=1 else -25
            profit=f"IN TRADE {side} {symbol_traded} Entry {int(entry_spot)} Now {int(spot)} Move {curr:.1f} High {highest:.1f} TrailSL {trail_sl:.1f} Time {last_ist}"
            if curr<=trail_sl:
                result=place_real_order(symbol_traded,"S",qty); trade_pnl=int(trail_sl*qty) if trail_sl>=0 else int(-25*qty)
                pnl+=trade_pnl; 
                if trade_pnl>0: wins+=1
                else: loss+=1
                in_trade=False; profit+=f" -> EXIT P&L {trade_pnl} Total {pnl}"
    return jsonify({"last_run":last_ist,"profit":profit,"pnl":pnl,"wins":wins,"loss":loss,"in_trade":in_trade,"side":side,"symbol":symbol_traded,"order_id":order_id,"token_set":token_set,"market":"OPEN 9:15-15:30 IST","spot":int(spot)})

@app.route('/login')
def login():
    url=f"https://skypro.skybroking.com/OAuthlogin/authorize/oauth?client_id={CLIENT_ID}&redirect_uri={REDIRECT_URL}&response_type=code"
    return redirect(url)

@app.route('/callback')
def callback():
    code=request.args.get("code","")
    if not code: return "<h1>No Code</h1><a href='/login'>Login</a>"
    if code=="test": return f"<h1>OK</h1><p>USER_ID:{USER_ID} CLIENT_ID:{CLIENT_ID} Secret:{bool(get_secret())} Time:{get_ist()}</p>"
    secret=get_secret()
    if not secret: return f"<h1>SKY_SECRET NOT SET</h1><p>Code:{code}</p>"
    if not HAS_REQUESTS: return "<h1>No requests lib</h1>"
    last_error=""
    for attempt in range(3):
        try:
            payload={"api_key":CLIENT_ID,"request_code":code,"api_secret":secret}
            resp=requests.post(f"{BASE_URL}QuickAuth",data={"jData":json.dumps(payload)},timeout=15)
            raw=resp.text
            if "502 Bad Gateway" in raw or "Bad Gateway" in raw:
                last_error=f"Attempt {attempt+1}: Sky Server 502 Down - Retrying... Server Raw: {raw[:200]}"
                time.sleep(2); continue
            try:
                result=resp.json()
            except:
                return f"<h1>Attempt {attempt+1} Failed - Server says:</h1><pre>{raw[:2000]}</pre><p>Secret OK: {secret[:10]}...{secret[-10:]}</p><a href='/login'>Retry Login</a>"
            token=result.get("susertoken") or result.get("token") or ""
            stat=result.get("stat","")
            if token and stat=="Ok":
                return f"<h1 style='color:green'>TOKEN SUCCESS! REAL READY!</h1><textarea style='width:100%;height:120px'>{token}</textarea><p>Add ENV SKY_API_TOKEN={token}</p><p>{result}</p><a href='/status'>Go Status</a>"
            else:
                return f"<h1>Token Failed</h1><p>Response: {result}</p><pre>{raw[:2000]}</pre><a href='/login'>Try Again</a>"
        except Exception as e:
            last_error=str(e); time.sleep(1)
    return f"<h1>SKY Server 502 Bad Gateway - Down</h1><p>Code:{code}</p><p>Last Error: {last_error}</p><p><b>Sky server is down at 13:13 IST while NSE is OPEN! Wait 5 mins and retry.</b></p><p>Time Now: {get_ist().strftime('%H:%M:%S IST')}</p><a href='/login'>Login Again</a> | <a href='/status'>Status - Bot still SIMULATION</a>"

if __name__=='__main__': app.run(host='0.0.0.0',port=10000)
