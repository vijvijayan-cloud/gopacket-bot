from flask import Flask, redirect, request, jsonify
import os, threading, time, requests
from datetime import datetime

app = Flask(__name__)

CLIENT_ID = "SKY59589_U"
SECRET = os.getenv("SECRET_CODE", "YOUR_SECRET_HERE")
REDIRECT_URL = "https://gopacket-bot-1.onrender.com/callback"

# === CORRECTED: 65=1LOT BOTH CE/PE SL25 TRAIL 1PT ITM1 ===
LOT_SIZE = 65  # 1 LOT = 65
qty = 65
sl_points = -25
trail_gap = 1
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
profit_text = "Bot Starting... Waiting for 10:15 - 65=1LOT BOTH READY"
last_run = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
access_token = ""
spot = 24500

def get_itm1_symbol(real_spot, side):
    step = 50
    base = int(real_spot // step) * step
    strike = base - 50 if side == "CE" else base + 50
    return f"NIFTY {strike} {side}"

def trading_loop():
    global pnl, wins, loss, in_trade, entry_spot, side, highest, profit_text, last_run, ema20, ema50, spot, symbol_traded
    print("LIVE: 65=1LOT BOTH CE/PE SL25 TRAIL1 ITM1")
    while True:
        try:
            last_run = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
            now = datetime.now()
            mins = now.hour*60 + now.minute
            
            if ema20 == 0:
                ema20 = spot
                ema50 = spot
            
            ema20 = ema20*0.95 + spot*0.05
            ema50 = ema50*0.98 + spot*0.02
            
            if mins < 615:
                profit_text = f"WAITING 10:15 - NIFTY {spot} - 65=1LOT BOTH CE/PE READY"
                time.sleep(10)
                continue
            if mins > 915:
                profit_text = f"MARKET CLOSED - Total Rs.{pnl} W{wins} L{loss} - 65=1LOT"
                time.sleep(60)
                continue
            
            trend = "BULL" if ema20 > ema50 else "BEAR"
            
            if not in_trade:
                # SIMULATE BOTH SIDE FOR NOW - Replace with real price later
                import random
                if spot > ema20 and random.random() > 0.8:
                    in_trade = True
                    side = "CE"
                    entry_spot = spot
                    highest = 0
                    symbol_traded = get_itm1_symbol(spot, "CE")
                    print(f">>> BUY {symbol_traded} ENTRY {entry_spot}")
                elif spot < ema20 and random.random() > 0.8:
                    in_trade = True
                    side = "PE"
                    entry_spot = spot
                    highest = 0
                    symbol_traded = get_itm1_symbol(spot, "PE")
                    print(f">>> BUY {symbol_traded} ENTRY {entry_spot}")
                profit_text = f"SCANNING {spot} {trend} EMA {int(ema20)}/{int(ema50)} - 65=1LOT BOTH READY"
            else:
                import random
                spot_change = random.choice([-8,-4,4,8])
                curr_spot = spot + spot_change
                curr = (curr_spot - entry_spot) if side=="CE" else (entry_spot - curr_spot)
                if curr > highest:
                    highest = curr
                trail_sl = highest - trail_gap if highest >= 1 else sl_points
                profit_text = f"IN TRADE {side} {symbol_traded} Entry {entry_spot} Move {curr:.1f} High {highest:.1f} TrailSL {trail_sl:.1f} - 65=1LOT"
                if curr <= trail_sl:
                    reason = "TRAIL" if trail_sl >=0 else "SL25"
                    trade_pnl = int(trail_sl * qty) if trail_sl>=0 else int(sl_points * qty)
                    pnl += trade_pnl
                    if trade_pnl>0: wins+=1
                    else: loss+=1
                    in_trade = False
            
            spot += random.choice([-2,2]) if 'random' in locals() else 1
            time.sleep(5)
        except Exception as e:
            print(f"Loop error: {e}")
            time.sleep(5)

@app.route('/')
def home():
    return f"<h1>LIVE BOT 65=1LOT BOTH CE/PE</h1><p>{profit_text}</p><p>Last: {last_run}</p><p>P&L Rs.{pnl}</p><a href='/login'>LOGIN</a> | <a href='/status'>STATUS</a>"

@app.route('/status')
def status_route():
    return jsonify({"last_run": last_run, "profit": profit_text, "pnl": pnl, "wins": wins, "loss": loss, "in_trade": in_trade, "side": side, "symbol": symbol_traded, "lot_info": "65=1LOT"})

@app.route('/login')
def login():
    url = f"https://skypro.skybroking.com/OAuthlogin/authorize/oauth?client_id={CLIENT_ID}&redirect_uri={REDIRECT_URL}&response_type=code"
    return redirect(url)

@app.route('/callback')
def callback():
    global access_token, profit_text
    code = request.args.get("code", "")
    access_token = code
    profit_text = f"Login Success - LIVE 65=1LOT BOTH CE/PE READY"
    return f"<h1>LOGIN SUCCESS 65=1LOT</h1><p>Both CE/PE ITM1 SL25 Trail1 Ready</p><a href='/status'>Status</a>"

# Start thread
t = threading.Thread(target=trading_loop, daemon=True)
t.start()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
