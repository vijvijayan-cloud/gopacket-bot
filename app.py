from flask import Flask, redirect, request, jsonify
import os, threading, time
from datetime import datetime, timedelta
import random

app = Flask(__name__)

CLIENT_ID = "SKY59589_U"
REDIRECT_URL = "https://gopacket-bot-1.onrender.com/callback"

# === 65=1LOT BOTH CE/PE SL25 TRAIL1 ITM1 - IST FIXED ===
LOT_SIZE = 65
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
ema20 = 24500
ema50 = 24500
spot = 24500
profit_text = "Starting..."
last_run = ""

def get_ist_time():
    # UTC to IST +5:30
    utc_now = datetime.utcnow()
    ist_now = utc_now + timedelta(hours=5, minutes=30)
    return ist_now

def get_itm1_symbol(s, side):
    step = 50
    base = int(s // step) * step
    strike = base - 50 if side == "CE" else base + 50
    return f"NIFTY {strike} {side} ITM1"

def trading_loop():
    global pnl, wins, loss, in_trade, entry_spot, side, highest, profit_text, last_run, ema20, ema50, spot, symbol_traded
    while True:
        try:
            ist_now = get_ist_time()
            last_run = ist_now.strftime("%d-%m-%Y %H:%M:%S IST")
            mins = ist_now.hour*60 + ist_now.minute
            
            spot += random.choice([-6,-3,3,6])
            ema20 = ema20*0.95 + spot*0.05
            ema50 = ema50*0.98 + spot*0.02
            
            # NOW IST CORRECT: 615 = 10:15 IST, 915 = 15:15 IST
            if mins < 615:
                profit_text = f"WAITING 10:15 IST - NIFTY {int(spot)} - Time Now {ist_now.strftime('%H:%M IST')} - 65=1LOT BOTH READY"
                time.sleep(10)
                continue
            if mins > 915:
                profit_text = f"CLOSED {ist_now.strftime('%H:%M IST')} - P&L Rs.{pnl} W{wins} L{loss} - 65=1LOT"
                time.sleep(60)
                continue
            
            trend = "BULL" if ema20 > ema50 else "BEAR"
            
            if not in_trade:
                if spot > ema20 and random.random() > 0.85:
                    in_trade = True
                    side = "CE"
                    entry_spot = spot
                    highest = 0
                    symbol_traded = get_itm1_symbol(spot, "CE")
                elif spot < ema20 and random.random() > 0.85:
                    in_trade = True
                    side = "PE"
                    entry_spot = spot
                    highest = 0
                    symbol_traded = get_itm1_symbol(spot, "PE")
                else:
                    profit_text = f"SCANNING {int(spot)} {trend} EMA {int(ema20)}/{int(ema50)} Time {ist_now.strftime('%H:%M:%S IST')} - 65=1LOT BOTH CE/PE READY"
            else:
                curr = (spot - entry_spot) if side=="CE" else (entry_spot - spot)
                if curr > highest:
                    highest = curr
                trail_sl = highest - trail_gap if highest >= 1 else sl_points
                profit_text = f"IN TRADE {side} {symbol_traded} Entry {entry_spot} Now {int(spot)} Move {curr:.1f} High {highest:.1f} TrailSL {trail_sl:.1f} Time {ist_now.strftime('%H:%M IST')} - 65=1LOT"
                if curr <= trail_sl:
                    trade_pnl = int(trail_sl * qty) if trail_sl>=0 else int(sl_points * qty)
                    pnl += trade_pnl
                    if trade_pnl>0: wins+=1
                    else: loss+=1
                    in_trade = False
            
            time.sleep(3)
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(5)

@app.route('/')
def home():
    return f"<h1>LIVE 65=1LOT BOTH IST FIXED</h1><p>{profit_text}</p><p>{last_run}</p><p>P&L Rs.{pnl}</p><a href='/status'>STATUS</a>"

@app.route('/status')
def status_route():
    return jsonify({"last_run": last_run, "profit": profit_text, "pnl": pnl, "wins": wins, "loss": loss, "in_trade": in_trade, "side": side, "symbol": symbol_traded, "lot": "65=1LOT", "strategy": "BOTH CE/PE ITM1 SL25 TRAIL1 IST"})

@app.route('/login')
def login():
    url = f"https://skypro.skybroking.com/OAuthlogin/authorize/oauth?client_id={CLIENT_ID}&redirect_uri={REDIRECT_URL}&response_type=code"
    return redirect(url)

@app.route('/callback')
def callback():
    code = request.args.get("code", "")
    return f"<h1>LOGIN SUCCESS IST FIXED</h1><p>{code[:20]}...</p><a href='/status'>Status</a>"

threading.Thread(target=trading_loop, daemon=True).start()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
