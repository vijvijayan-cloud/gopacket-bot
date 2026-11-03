from flask import Flask, redirect, request, jsonify
from datetime import datetime, timedelta
import random
import os
import json

# Safe import - Never RED even if requests missing
try:
    import requests
    HAS_REQUESTS = True
except:
    HAS_REQUESTS = False
    requests = None

app = Flask(__name__)

# CONFIG
CLIENT_ID = "SKY59589_U"
REDIRECT_URL = "https://gopacket-bot-1.onrender.com/callback"
BASE_URL = "https://skypro.skybroking.com/NorenWClientTP/"

# TRADING VARS
qty = 65
pnl = 0
wins = 0
loss = 0
spot = 24500
ema20 = 24500
ema50 = 24500
in_trade = False
side = ""
entry_spot = 0
symbol_traded = ""
highest = 0
order_id = ""

def get_ist():
    return datetime.utcnow() + timedelta(hours=5, minutes=30)

def get_api_token():
    return os.getenv("SKY_API_TOKEN", "") or os.getenv("SKY_TOKEN", "")

def get_secret():
    return os.getenv("SKY_SECRET", "")

def place_real_order(tsym, buy_sell, qty):
    global order_id
    token = get_api_token()
    if not token or not HAS_REQUESTS:
        return {"status": "SIMULATION", "msg": f"{buy_sell} {tsym} Qty {qty} - No token/requests, simulation"}
    try:
        jdata = {
            "uid": CLIENT_ID,
            "actid": CLIENT_ID,
            "exch": "NFO",
            "tsym": tsym,
            "qty": str(qty),
            "prc": "0",
            "prctyp": "MKT",
            "trantype": buy_sell,
            "ret": "DAY",
            "prd": "M",
            "ordersource": "API"
        }
        data = {"jData": json.dumps(jdata), "jKey": token}
        resp = requests.post(f"{BASE_URL}PlaceOrder", data=data, timeout=10)
        result = resp.json()
        order_id = str(result.get("norenordno", result.get("orderno", "")))
        print(f"REAL ORDER: {result}")
        return result
    except Exception as e:
        return {"error": str(e)}

def get_itm1_symbol(s, side):
    base = int(s // 50) * 50
    strike = base - 50 if side == "CE" else base + 50
    return f"NIFTY{strike}{side}"

@app.route('/')
def home():
    ist = get_ist()
    token = get_api_token()
    secret = get_secret()
    status = "REAL READY" if token and HAS_REQUESTS else "SIMULATION"
    if not secret:
        status += " - SET SKY_SECRET ENV"
    if not token:
        status += " - LOGIN FOR TOKEN"
    return f"""
    <h1>65=1LOT BOTH CE/PE - {status}</h1>
    <p>Time: {ist.strftime('%d-%m-%Y %H:%M:%S IST')}</p>
    <p>P&L: Rs.{pnl} | Wins: {wins} Loss: {loss} | Order: {order_id}</p>
    <p>Has Requests: {HAS_REQUESTS} | Token: {'SET' if token else 'NOT SET'} | Secret: {'SET' if secret else 'NOT SET'}</p>
    <p><a href='/status'>STATUS LIVE</a> | <a href='/login'>LOGIN FOR TOKEN</a> | <a href='/callback?code=test'>TEST CALLBACK</a></p>
    <p>Strategy: ITM1 CE/PE SL -25 Trail 1 point 65=1LOT</p>
    """

@app.route('/status')
def status_route():
    global pnl, wins, loss, spot, ema20, ema50, in_trade, side, entry_spot, symbol_traded, highest
    
    ist = get_ist()
    last_ist = ist.strftime("%d-%m-%Y %H:%M:%S IST")
    mins = ist.hour * 60 + ist.minute
    
    # Simulate spot movement
    spot += random.choice([-8, -4, 4, 8])
    ema20 = ema20 * 0.95 + spot * 0.05
    ema50 = ema50 * 0.98 + spot * 0.02
    trend = "BULL" if ema20 > ema50 else "BEAR"
    token_set = bool(get_api_token())
    
    if mins < 615:  # Before 10:15 IST
        profit = f"WAITING 10:15 IST - NIFTY {int(spot)} Trend {trend} Time {ist.strftime('%H:%M:%S IST')} - 65=1LOT BOTH READY REAL={token_set}"
    elif mins > 915:  # After 15:15 IST
        profit = f"CLOSED Market 15:15 - P&L Rs.{pnl} W{wins} L{loss} Order {order_id} Time {ist.strftime('%H:%M:%S IST')} - 65=1LOT"
    else:
        if not in_trade:
            # Entry logic
            if spot > ema20 and random.random() > 0.82:
                in_trade = True
                side = "CE"
                entry_spot = spot
                highest = 0
                symbol_traded = get_itm1_symbol(spot, "CE")
                result = place_real_order(symbol_traded, "B", qty)
                profit = f"NEW ENTRY {side} {symbol_traded} Entry {int(entry_spot)} Result {result} Time {ist.strftime('%H:%M:%S IST')} - 65=1LOT REAL={token_set}"
            elif spot < ema20 and random.random() > 0.82:
                in_trade = True
                side = "PE"
                entry_spot = spot
                highest = 0
                symbol_traded = get_itm1_symbol(spot, "PE")
                result = place_real_order(symbol_traded, "B", qty)
                profit = f"NEW ENTRY {side} {symbol_traded} Entry {int(entry_spot)} Result {result} Time {ist.strftime('%H:%M:%S IST')} - 65=1LOT REAL={token_set}"
            else:
                profit = f"SCANNING {int(spot)} {trend} EMA {int(ema20)}/{int(ema50)} Time {ist.strftime('%H:%M:%S IST')} - 65=1LOT BOTH CE/PE READY REAL={token_set} HAS_REQ={HAS_REQUESTS}"
        else:
            # In trade - Trail SL
            curr = (spot - entry_spot) if side == "CE" else (entry_spot - spot)
            if curr > highest:
                highest = curr
            trail_sl = highest - 1 if highest >= 1 else -25
            
            profit = f"IN TRADE {side} {symbol_traded} Entry {int(entry_spot)} Now {int(spot)} Move {curr:.1f} High {highest:.1f} TrailSL {trail_sl:.1f} Order {order_id} Time {ist.strftime('%H:%M:%S IST')} - 65=1LOT"
            
            if curr <= trail_sl:
                result = place_real_order(symbol_traded, "S", qty)
                trade_pnl = int(trail_sl * qty) if trail_sl >= 0 else int(-25 * qty)
                pnl += trade_pnl
                if trade_pnl > 0:
                    wins += 1
                else:
                    loss += 1
                in_trade = False
                profit += f" -> EXIT Result {result} P&L {trade_pnl} Total {pnl}"
    
    return jsonify({
        "last_run": last_ist,
        "profit": profit,
        "pnl": pnl,
        "wins": wins,
        "loss": loss,
        "in_trade": in_trade,
        "side": side,
        "symbol": symbol_traded,
        "order_id": order_id,
        "lot": "65=1LOT",
        "has_requests": HAS_REQUESTS,
        "token_set": token_set,
        "secret_set": bool(get_secret()),
        "strategy": "BOTH CE/PE ITM1 SL25 TRAIL1 IST REAL",
        "spot": int(spot),
        "ema20": int(ema20),
        "ema50": int(ema50)
    })

@app.route('/login')
def login():
    url = f"https://skypro.skybroking.com/OAuthlogin/authorize/oauth?client_id={CLIENT_ID}&redirect_uri={REDIRECT_URL}&response_type=code"
    return redirect(url)

@app.route('/callback')
def callback():
    code = request.args.get("code", "")
    if not code:
        return "<h1>No Code</h1><a href='/login'>Login Again</a> | <a href='/status'>Status</a>"
    
    if code == "test":
        return f"<h1>Callback Working!</h1><p>Secret SET? {bool(get_secret())} Token SET? {bool(get_api_token())} Has Requests? {HAS_REQUESTS}</p><a href='/login'>Login</a>"
    
    secret = get_secret()
    if not secret:
        return f"<h1>Code Received: {code[:20]}...</h1><p style='color:red'>ERROR: SKY_SECRET ENV NOT SET!</p><p>Go to Render Dashboard -> Environment -> Add SKY_SECRET = your secret</p><p>Then login again</p><a href='/status'>Status</a>"
    
    if not HAS_REQUESTS:
        return f"<h1>Code: {code}</h1><p>ERROR: requests library not installed, set requirements.txt = Flask + requests</p>"
    
    try:
        payload = {"api_key": CLIENT_ID, "request_code": code, "api_secret": secret}
        resp = requests.post(f"{BASE_URL}QuickAuth", data={"jData": json.dumps(payload)}, timeout=15)
        result = resp.json()
        
        token = result.get("susertoken") or result.get("token") or result.get("access_token") or ""
        
        if token:
            return f"""
            <h1 style='color:green'>TOKEN SUCCESS! REAL READY!</h1>
            <p><b>Token:</b></p>
            <textarea style='width:100%;height:100px'>{token}</textarea>
            <p><b>COPY THIS TOKEN and add to Render ENV:</b></p>
            <p>Key: SKY_API_TOKEN<br>Value: {token}</p>
            <p>Full Response: {result}</p>
            <p><a href='/status'>Go Status - Now REAL</a></p>
            """
        else:
            return f"<h1>Code OK but Token Failed</h1><p>Code: {code}</p><p>Response: {result}</p><p>Check secret correct?</p><a href='/login'>Try Login Again</a>"
    except Exception as e:
        return f"<h1>Code: {code}</h1><p>Error exchanging: {e}</p><p>Check SKY_SECRET</p><a href='/status'>Status</a>"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
