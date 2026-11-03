from flask import Flask, redirect, request, jsonify
import os
from datetime import datetime

app = Flask(__name__)

CLIENT_ID = "SKY59589_U"
REDIRECT_URL = "https://gopacket-bot-1.onrender.com/callback"

# === 65=1LOT BOTH CE/PE SL25 TRAIL1 ITM1 ===
profit_text = "Bot Live - 65=1LOT BOTH CE/PE SL25 TRAIL1 ITM1 Ready"
last_run = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
pnl = 0

@app.route('/')
def home():
    return f"<h1>GoPocket LIVE 65=1LOT</h1><p>{profit_text}</p><p>Last: {last_run}</p><a href='/login'>LOGIN</a> | <a href='/status'>STATUS</a>"

@app.route('/status')
def status_route():
    return jsonify({"last_run": last_run, "profit": profit_text, "pnl": pnl, "status": "Running", "lot": "65=1LOT", "strategy": "BOTH CE/PE ITM1 SL25 TRAIL1"})

@app.route('/login')
def login():
    url = f"https://skypro.skybroking.com/OAuthlogin/authorize/oauth?client_id={CLIENT_ID}&redirect_uri={REDIRECT_URL}&response_type=code"
    return redirect(url)

@app.route('/callback')
def callback():
    code = request.args.get("code", "")
    return f"<h1>LOGIN SUCCESS 65=1LOT</h1><p>Code: {code[:20]}...</p><a href='/'>Home</a>"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
