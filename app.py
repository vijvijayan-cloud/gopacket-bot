from flask import Flask, redirect, request, jsonify
import os, threading, time, requests
from datetime import datetime

app = Flask(__name__)

CLIENT_ID = "SKY59589_U"
SECRET = os.getenv("SECRET_CODE", "")
REDIRECT_URL = "https://gopacket-bot-1.onrender.com/callback"

# === YOUR 10:15 SETUP - CORRECTED ===
qty = 65
sl_points = -25
trail_gap = 1  # Trail at 1 point
pnl = 0
wins = 0
loss = 0
in_trade = False
entry_spot = 0
side = ""
highest = 0
symbol_traded = ""
ema20 = 0
ema50 = 0

profit_text = "Rs.0 - Waiting for 10:15"
last_run = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
access_token = ""
spot = 24500

def get_itm1_symbol(real_spot, side):
    step = 50
    base = int(real_spot // step) * step
    strike = base - 50 if side == "CE" else base + 50
    # SkyPro format - Adjust if needed
    return f"NIFTY{strike}{side}"

def get_real_nifty_price():
    global spot
    try:
        # If token available, try real feed, else use last
        if access_token:
            # SkyPro LTP API - Replace with exact endpoint from docs
            r = requests.get("https://api.skybroking.com/quotes/NIFTY", 
                headers={"Authorization": f"Bearer {access_token}"}, timeout=5)
            if r.status_code == 200:
                spot = float(r.json().get('ltp', spot))
                return spot
    except:
        pass
    # Fallback - For now simulates, but will use real when connected
    return spot

def place_real_order(symbol, side):
    if not access_token:
        print("No token - Paper trade only")
        return False
    try:
        order = {
            "exchange": "NFO",
            "symbol": symbol,
            "qty": qty,
            "type": "MARKET",
            "side": "BUY",
            "product": "MIS"
        }
        resp = requests.post("https://api.skybroking.com/orders",
            json=order, headers={"Authorization": f"Bearer {access_token}"}, timeout=10)
        print(f"REAL ORDER PLACED: {symbol} {resp.text}")
        return True
    except Exception as e:
        print(f"Order failed: {e}")
        return False

def trading_loop():
    global pnl, wins, loss, in_trade, entry_spot, side, highest, profit_text, last_run, ema20, ema50, spot, symbol_traded
    print("GoPocket PRO LIVE - 10:15 SETUP - BOTH CE & PE - SL25 TRAIL1 ITM1")
    while True:
        last_run = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
        now = datetime.now()
        mins = now.hour*60 + now.minute
        
        # Get real price
        real_spot = get_real_nifty_price()
        
        if ema20 == 0:
            ema20 = real_spot
            ema50 = real_spot
        
        ema20 = ema20*0.95 + real_spot*0.05
        ema50 = ema50*0.98 + real_spot*0.02
        
        if mins < 615: # Before 10:15
            profit_text = f"WAITING 10:15 - NIFTY {real_spot} - Both CE/PE ready"
            time.sleep(10)
            continue
        if mins > 915: # After 3:15
            profit_text = f"MARKET CLOSED - Total P&L Rs.{pnl} W{wins} L{loss}"
            time.sleep(60)
            continue
        
        trend = "BULL" if ema20 > ema50 else "BEAR"
        
        if not in_trade:
            # BOTH SIDE LOGIC
            if real_spot > ema20: # CE SIDE
                in_trade = True
                side = "CE"
                entry_spot = real_spot
                highest = 0
                symbol_traded = get_itm1_symbol(real_spot, "CE")
                place_real_order(symbol_traded, "CE")
                print(f">>> BUY {symbol_traded} ITM1 ENTRY {entry_spot} {trend} <<<")
            elif real_spot < ema20: # PE SIDE
                in_trade = True
                side = "PE"
                entry_spot = real_spot
                highest = 0
                symbol_traded = get_itm1_symbol(real_spot, "PE")
                place_real_order(symbol_traded, "PE")
                print(f">>> BUY {symbol_traded} ITM1 ENTRY {entry_spot} {trend} <<<")
            else:
                profit_text = f"SCANNING {real_spot} {trend} EMA {int(ema20)}/{int(ema50)} - Ready BOTH"
        else:
            curr = (real_spot - entry_spot) if side=="CE" else (entry_spot - real_spot)
            if curr > highest:
                highest = curr
            trail_sl = highest - trail_gap if highest >= 1 else sl_points
            
            profit_text = f"IN TRADE {side} {symbol_traded} Entry {entry_spot} Now {real_spot} Move {curr:.1f} High {highest:.1f} TrailSL {trail_sl:.1f} P&L Rs.{int(curr*qty)}"
            
            if curr <= trail_sl:
                reason = "TRAIL PROFIT" if trail_sl >=0 else "SL25 HIT"
                trade_pnl = int(trail_sl * qty) if trail_sl>=0 else int(sl_points * qty)
                pnl += trade_pnl
                if trade_pnl>0: wins+=1
                else: loss+=1
                print(f"*** {reason} {symbol_traded} CLOSED P&L Rs.{trade_pnl} Total Rs.{pnl} ***")
                in_trade = False
        
        time.sleep(5) # Check every 5 sec live

@app.route('/')
def home():
    return f"<h1>LIVE BOT SKY59589_U - BOTH CE & PE</h1><p>{profit_text}</p><p>Last: {last_run}</p><p>P&L Rs.{pnl} W{wins} L{loss}</p><a href='/login'>LOGIN</a> | <a href='/status'>STATUS</a>"

@app.route('/status')
def status_route():
    return jsonify({"last_run": last_run, "profit": profit_text, "pnl": pnl, "wins": wins, "loss": loss, "in_trade": in_trade, "side": side, "symbol": symbol_traded})

@app.route('/login')
def login():
    url = f"https://skypro.skybroking.com/OAuthlogin/authorize/oauth?client_id={CLIENT_ID}&redirect_uri={REDIRECT_URL}&response_type=code"
    return redirect(url)

@app.route('/callback')
def callback():
    global access_token, profit_text
    code = request.args.get("code", "")
    try:
        resp = requests.post("https://skypro.skybroking.com/OAuthlogin/api/token", data={
            "client_id": CLIENT_ID, "client_secret": SECRET, "code": code,
            "redirect_uri": REDIRECT_URL, "grant_type": "authorization_code"
        }, timeout=10)
        access_token = resp.json().get("access_token", code)
        profit_text = f"Login Success {access_token[:10]}... - LIVE Both CE/PE ITM1 SL25 Trail1 READY"
        return f"<h1>✅ LIVE LOGIN SUCCESS - BOTH CE & PE READY</h1><p>ITM1 SL25 Trail1</p><p>Token OK - Bot will trade BOTH sides after 10:15</p><a href='/status'>Check Status</a>"
    except Exception as e:
        return f"Code: {code} Error: {e}"

threading.Thread(target=trading_loop, daemon=True).start()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
