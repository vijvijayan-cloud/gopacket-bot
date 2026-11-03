from flask import Flask, redirect, request, jsonify
import os, threading, time
from datetime import datetime
import random

app = Flask(__name__)

CLIENT_ID = "SKY59589_U"
REDIRECT_URL = "https://gopacket-bot-1.onrender.com/callback"

# === YOUR CORRECTION: 65=1LOT BOTH CE/PE SL25 TRAIL1 ITM1 ===
LOT_SIZE = 65
qty = 65  # 1 lot = 65 qty
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
ema20 = 24500
ema50 = 24500
spot = 24500
profit_text = "Starting - 65=1LOT BOTH CE/PE SL25 TRAIL1 ITM1"
last_run = datetime.now().strftime("%d-%m-%Y %H:%M:%S")

def get_itm1_symbol(s, side):
    step = 50
    base = int(s // step) * step
    strike = base - 50 if side == "CE" else base + 50
    return f"NIFTY {strike} {side} ITM1"

def trading_loop():
    global pnl, wins, loss, in_trade, entry_spot, side, highest, profit_text, last_run, ema20, ema50, spot, symbol_traded
    while True:
        try:
            last_run = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
            now = datetime.now()
            mins = now.hour*60 + now.minute
            
            # Simulate spot - Replace with real feed later
            spot_move = random.choice([-6,-3,3,6])
            spot += spot_move
            ema20 = ema20*0.95 + spot*0.05
            ema50 = ema50*0.98 + spot*0.02
            
            if mins < 615: # 10:15 AM
                profit_text = f"WAITING 10:15 - NIFTY {spot} - 65=1LOT BOTH CE/PE READY"
                time.sleep(10)
                continue
            if mins > 915: # 3:15 PM
                profit_text = f"CLOSED - P&L Rs.{pnl} W{wins} L{loss} - 65=1LOT"
                time.sleep(60)
                continue
            
            trend = "BULL" if ema20 > ema50 else "BEAR"
            
            if not in_trade:
                # BOTH SIDE LOGIC
                if spot > ema20 and random.random() > 0.85:
                    in_trade = True
                    side = "CE"
                    entry_spot = spot
                    highest = 0
                    symbol_traded = get_itm1_symbol(spot, "CE")
                    print(f">>> BUY {symbol_traded} ENTRY {entry_spot}")
                elif spot < ema20 and random.random() > 0.85:
                    in_trade = True
                    side = "PE"
                    entry_spot = spot
                    highest = 0
                    symbol_traded = get_itm1_symbol(spot, "PE")
                    print(f">>> BUY {symbol_traded} ENTRY {entry_spot}")
                else:
                    profit_text = f"SCANNING {spot} {trend} EMA {int(ema20)}/{int(ema50)} - 65=1LOT BOTH READY"
            else:
                curr = (spot - entry_spot) if side=="CE" else (entry_spot - spot)
                if curr > highest:
                    highest = curr
                trail_sl = highest - trail_gap if highest >= 1 else sl_points
                profit_text = f"IN TRADE {side} {symbol_traded} Entry {entry_spot} Now {spot} Move {curr:.1f} High {highest:.1f} TrailSL {trail_sl:.1f} - 65=1LOT"
                if curr <= trail_sl:
                    reason = "TRAIL PROFIT" if trail_sl >=0 else "SL25 HIT"
                    trade_pnl = int(trail_sl * qty) if trail_sl>=0 else int(sl_points * qty)
                    pnl += trade_pnl
                    if trade_pnl>0: wins+=1
                    else: loss+=1
                    print(f"*** {reason} CLOSED P&L {trade_pnl} Total {pnl}")
                    in_trade = False
            
            time.sleep(3)
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(5)

@app.route('/')
def home():
    return f"<h1>LIVE 65=1LOT BOTH CE/PE</h1><p>{profit_text}</p><p>Last: {last_run}</p><p>P&L Rs.{pnl} W{wins} L{loss}</p><a href='/login'>LOGIN</a> | <a href='/status'>STATUS</a>"

@app.route('/status')
def status_route():
    return jsonify({"last_run": last_run, "profit": profit_text, "pnl": pnl, "wins": wins, "loss": loss, "in_trade": in_trade, "side": side, "symbol": symbol_traded, "lot": "65=1LOT", "strategy": "BOTH CE/PE ITM1 SL25 TRAIL1"})

@app.route('/login')
def login():
    url = f"https://skypro.skybroking.com/OAuthlogin/authorize/oauth?client_id={CLIENT_ID}&redirect_uri={REDIRECT_URL}&response_type=code"
    return redirect(url)

@app.route('/callback')
def callback():
    code = request.args.get("code", "")
    return f"<h1>LOGIN SUCCESS 65=1LOT BOTH READY</h1><p>Code {code[:20]}...</p><a href='/'>Home</a> | <a href='/status'>Status</a>"

# Start trading thread
threading.Thread(target=trading_loop, daemon=True).start()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
