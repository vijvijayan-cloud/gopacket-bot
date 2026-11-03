from flask import Flask, redirect, request, jsonify
from datetime import datetime, timedelta
import random, os

app = Flask(__name__)

CLIENT_ID = "SKY59589_U"
REDIRECT_URL = "https://gopacket-bot-1.onrender.com/callback"

# === 65=1LOT BOTH CE/PE SL25 TRAIL1 ITM1 - NO THREAD FREEZE FIX ===
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
last_ist = ""

def get_ist():
    return datetime.utcnow() + timedelta(hours=5, minutes=30)

def get_itm1(s, side):
    base = int(s // 50) * 50
    strike = base - 50 if side=="CE" else base + 50
    return f"NIFTY {strike} {side} ITM1"

@app.route('/')
def home():
    ist = get_ist()
    return f"<h1>LIVE 65=1LOT BOTH - NO FREEZE</h1><p>Time: {ist.strftime('%H:%M:%S IST')}</p><p>P&L Rs.{pnl}</p><a href='/status'>STATUS LIVE</a> | <a href='/login'>LOGIN</a>"

@app.route('/status')
def status_route():
    global pnl, wins, loss, spot, ema20, ema50, in_trade, side, entry_spot, symbol_traded, highest, last_ist
    
    ist = get_ist()
    last_ist = ist.strftime("%d-%m-%Y %H:%M:%S IST")
    mins = ist.hour*60 + ist.minute
    
    # Update spot every call - NO THREAD NEEDED
    spot += random.choice([-8,-4,4,8])
    ema20 = ema20*0.95 + spot*0.05
    ema50 = ema50*0.98 + spot*0.02
    
    trend = "BULL" if ema20 > ema50 else "BEAR"
    
    if mins < 615:
        profit = f"WAITING 10:15 IST - NIFTY {int(spot)} - Now {ist.strftime('%H:%M:%S IST')} - 65=1LOT BOTH READY"
    elif mins > 915:
        profit = f"CLOSED {ist.strftime('%H:%M:%S IST')} - P&L Rs.{pnl} W{wins} L{loss} - 65=1LOT"
    else:
        # LIVE SCANNING - Every refresh updates!
        if not in_trade:
            # Simulate entry signal 15% chance each refresh
            if spot > ema20 and random.random() > 0.85:
                in_trade = True
                side = "CE"
                entry_spot = spot
                highest = 0
                symbol_traded = get_itm1(spot, "CE")
                profit = f"NEW ENTRY {side} {symbol_traded} Entry {int(entry_spot)} Time {ist.strftime('%H:%M:%S IST')} - 65=1LOT"
            elif spot < ema20 and random.random() > 0.85:
                in_trade = True
                side = "PE"
                entry_spot = spot
                highest = 0
                symbol_traded = get_itm1(spot, "PE")
                profit = f"NEW ENTRY {side} {symbol_traded} Entry {int(entry_spot)} Time {ist.strftime('%H:%M:%S IST')} - 65=1LOT"
            else:
                profit = f"SCANNING {int(spot)} {trend} EMA {int(ema20)}/{int(ema50)} Time {ist.strftime('%H:%M:%S IST')} - 65=1LOT BOTH CE/PE READY"
        else:
            curr = (spot - entry_spot) if side=="CE" else (entry_spot - spot)
            if curr > highest:
                highest = curr
            trail_sl = highest - 1 if highest >=1 else -25
            profit = f"IN TRADE {side} {symbol_traded} Entry {int(entry_spot)} Now {int(spot)} Move {curr:.1f} High {highest:.1f} TrailSL {trail_sl:.1f} Time {ist.strftime('%H:%M:%S IST')} - 65=1LOT"
            if curr <= trail_sl:
                trade_pnl = int(trail_sl * qty) if trail_sl>=0 else int(-25 * qty)
                pnl += trade_pnl
                if trade_pnl>0: wins+=1
                else: loss+=1
                in_trade = False
                profit += f" -> CLOSED P&L {trade_pnl} Total {pnl}"
    
    return jsonify({
        "last_run": last_ist,
        "current_time": ist.strftime("%H:%M:%S IST"),
        "spot": int(spot),
        "profit": profit,
        "pnl": pnl,
        "wins": wins,
        "loss": loss,
        "in_trade": in_trade,
        "side": side,
        "symbol": symbol_traded,
        "lot": "65=1LOT",
        "strategy": "BOTH CE/PE ITM1 SL25 TRAIL1 IST - NO FREEZE"
    })

@app.route('/login')
def login():
    url = f"https://skypro.skybroking.com/OAuthlogin/authorize/oauth?client_id={CLIENT_ID}&redirect_uri={REDIRECT_URL}&response_type=code"
    return redirect(url)

@app.route('/callback')
def callback():
    code = request.args.get("code", "")
    return f"<h1>LOGIN OK 65=1LOT</h1><p>{code[:20]}...</p><a href='/status'>Go Status</a>"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
