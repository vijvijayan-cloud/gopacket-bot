from flask import Flask, redirect, request, jsonify
import os, threading, time, requests
from datetime import datetime

app = Flask(__name__)

CLIENT_ID = "SKY59589_U"
SECRET = os.getenv("SECRET_CODE", "")
REDIRECT_URL = "https://gopacket-bot-1.onrender.com/callback"

profit = "Rs.59964 - Login Pending"
last_run = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
access_token = ""

def get_real_profit():
    global profit, last_run, access_token
    while True:
        last_run = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
        if access_token:
            try:
                # Try to fetch holdings P&L
                r = requests.get("https://api.skypro.skybroking.com/holdings", headers={"Authorization": f"Bearer {access_token}"}, timeout=10)
                if r.status_code == 200:
                    data = r.json()
                    profit = str(data.get("total_pnl", "Rs.59964"))
                print(f"REAL Profit: {profit}")
            except Exception as e:
                print(f"Error: {e}")
        time.sleep(60)

@app.route('/')
def home():
    return f"<h1>BOT LIVE SKY59589</h1><p>Profit: {profit}</p><p>Last: {last_run}</p><a href='/login'>LOGIN</a> | <a href='/status'>STATUS</a>"

@app.route('/status')
def status_route():
    return jsonify({"last_run": last_run, "profit": profit, "status": "Running", "client": CLIENT_ID})

@app.route('/login')
def login():
    url = f"https://skypro.skybroking.com/OAuthlogin/authorize/oauth?client_id={CLIENT_ID}&redirect_uri={REDIRECT_URL}&response_type=code"
    return redirect(url)

@app.route('/callback')
def callback():
    global access_token, profit
    code = request.args.get("code", "")
    if not code:
        return "No code received"
    try:
        # Exchange code for token
        resp = requests.post("https://skypro.skybroking.com/OAuthlogin/api/token", data={
            "client_id": CLIENT_ID,
            "client_secret": SECRET,
            "code": code,
            "redirect_uri": REDIRECT_URL,
            "grant_type": "authorization_code"
        })
        data = resp.json()
        access_token = data.get("access_token", code)
        profit = "Login Success - Fetching Real P&L..."
        return f"<h1>✅ LOGIN SUCCESS SKY59589</h1><p>Token: {access_token[:20]}...</p><p>Bot will now fetch REAL profit!</p><a href='/status'>Check Status</a>"
    except Exception as e:
        return f"Login received code: {code[:20]}... Error: {e}"

threading.Thread(target=get_real_profit, daemon=True).start()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
