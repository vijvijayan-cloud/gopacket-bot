from flask import Flask, redirect, request, jsonify
from datetime import datetime, timedelta
import requests, random, os, json

app = Flask(__name__)

CLIENT_ID = "SKY59589_U"
REDIRECT_URL = "https://gopacket-bot-1.onrender.com/callback"
API_TOKEN = os.getenv("SKY_API_TOKEN", "")
BASE_URL = "https://skypro.skybroking.com/NorenWClientTP/"

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

def place_real_order(tsym, buy_sell, qty):
    global order_id
    if not API_TOKEN:
        return {"error": "SET SKY_API_TOKEN ENV"}
    try:
        jdata = {"uid": CLIENT_ID, "actid": CLIENT_ID, "exch": "NFO", "tsym": tsym, "qty": str(qty), "prc": "0", "prctyp": "MKT", "trantype": buy_sell, "ret": "DAY", "prd": "M", "ordersource": "API"}
        data = {"jData": json.dumps(jdata), "jKey": API_TOKEN}
        resp = requests.post(f"{BASE_URL}PlaceOrder", data=data, timeout=10)
        result = resp.json()
        order_id = str(result.get("norenordno", ""))
        print(f"REAL ORDER: {tsym} {buy_sell} -> {result}")
        return result
    except Exception as e:
        return {"error": str(e)}

def get_itm1(s, side):
    base = int(s // 50) * 50
    strike = base - 50 if side=="CE" else base + 50
    return f"NIFTY{strike}{side}"

@app.route('/')
def home():
    ist = get_ist()
    status = "TOKEN OK" if API_TOKEN else "SET SKY_API_TOKEN IN ENV!"
    return f"<h1>REAL 65=1LOT BOTH</h1><p>{ist.strftime('%H:%M:%S IST')}</p><p>{status}</p><p>P&L {pnl} Order {order_id}</p><a href='/status'>STATUS</a>"

@app.route('/status')
def status_route():
    global pnl, wins, loss, spot, ema20, ema50, in_trade, side, entry_spot, symbol_traded, highest
    ist = get_ist()
    last_ist = ist.strftime("%d-%m-%Y %H:%M:%S IST")
    mins = ist.hour*60 + ist.minute
    spot += random.choice([-8,-4,4,8])
    ema20 = ema20*0.95 + spot*0.05
    ema50 = ema50*0.98 + spot*0.02
    trend = "BULL" if ema20 > ema50 else "BEAR"
    
    if mins < 615:
        profit = f"WAITING 10:15 IST - NIFTY {int(spot)} - {ist.strftime('%H:%M:%S IST')} - 65=1LOT REAL READY"
    elif mins > 915:
        profit = f"CLOSED {ist.strftime('%H:%M:%S IST')} - P&L {pnl} Order {order_id}"
    else:
        if not in_trade:
            if spot > ema20 and random.random() > 0.85:
                in_trade = True; side = "CE"; entry_spot = spot; highest = 0; symbol_traded = get_itm1(spot, "CE")
                result = place_real_order(symbol_traded, "B", qty)
                profit = f"REAL BUY {side} {symbol_traded} Entry {int(entry_spot)} Result {result} {ist.strftime('%H:%M:%S IST')}"
            elif spot < ema20 and random.random() > 0.85:
                in_trade = True; side = "PE"; entry_spot = spot; highest = 0; symbol_traded = get_itm1(spot, "PE")
                result = place_real_order(symbol_traded, "B", qty)
                profit = f"REAL BUY {side} {symbol_traded} Entry {int(entry_spot)} Result {result} {ist.strftime('%H:%M:%S IST')}"
            else:
                profit = f"SCANNING {int(spot)} {trend} EMA {int(ema20)}/{int(ema50)} {ist.strftime('%H:%M:%S IST')} - 65=1LOT BOTH READY REAL"
        else:
            curr = (spot - entry_spot) if side=="CE" else (entry_spot - spot)
            if curr > highest: highest = curr
            trail_sl = highest - 1 if highest >=1 else -25
            profit = f"IN REAL TRADE {side} {symbol_traded} Entry {int(entry_spot)} Now {int(spot)} Move {curr:.1f} High {highest:.1f} TrailSL {trail_sl:.1f} Order {order_id} {ist.strftime('%H:%M:%S IST')}"
            if curr <= trail_sl:
                place_real_order(symbol_traded, "S", qty)
                trade_pnl = int(trail_sl * qty) if trail_sl>=0 else int(-25 * qty)
                pnl += trade_pnl
                if trade_pnl>0: wins+=1
                else: loss+=1
                in_trade = False
                profit += f" -> REAL EXIT P&L {trade_pnl}"
    
    return jsonify({"last_run": last_ist, "profit": profit, "pnl": pnl, "wins": wins, "loss": loss, "in_trade": in_trade, "side": side, "symbol": symbol_traded, "order_id": order_id, "lot": "65=1LOT REAL", "api_token_set": bool(API_TOKEN), "strategy": "BOTH CE/PE ITM1 SL25 TRAIL1 REAL"})

@app.route('/login')
def login():
    url = f"https://skypro.skybroking.com/OAuthlogin/authorize/oauth?client_id={CLIENT_ID}&redirect_uri={REDIRECT_URL}&response_type=code"
    return redirect(url)

@app.route('/callback')
def callback():
    code = request.args.get("code", "")
    return f"<h1>LOGIN OK</h1><p>{code[:30]}...</p><a href='/status'>Status</a>"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
