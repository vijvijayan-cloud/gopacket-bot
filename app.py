from flask import Flask, redirect, request, jsonify
import os, threading, time
from datetime import datetime

app = Flask(__name__)
CLIENT_ID = os.getenv("CLIENT_ID", "SKY59589_U")
SECRET_CODE = os.getenv("SECRET_CODE", "")
REDIRECT_URL = os.getenv("REDIRECT_URL", "https://gopacket-bot-1.onrender.com/callback")

profit = "Rs.59964"
last_run = datetime.now().strftime("%d-%m-%Y %H:%M:%S")

def bot_thread():
    global last_run
    while True:
        last_run = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
        print(f"{CLIENT_ID} Bot Checking {profit}")
        time.sleep(60)

@app.route('/')
def home():
    return f"<h1>SKY59589 BOT LIVE</h1><p>Client: {CLIENT_ID}</p><p>Profit: {profit}</p><a href='/login'>Login</a>"

@app.route('/status')
def status_route():
    return jsonify({"last_run": last_run, "profit": profit, "status": "Running"})

@app.route('/login')
def login():
    auth_url = f"https://skypro.skybroking.com/OAuthlogin/authorize/oauth?client_id={CLIENT_ID}&redirect_uri={REDIRECT_URL}"
    return redirect(auth_url)

@app.route('/callback')
def callback():
    code = request.args.get("code","")
    return f"<h1>Login Success ✅</h1><p>Auth Code: {code[:20]}...</p>"

if __name__ == '__main__':
    threading.Thread(target=bot_thread, daemon=True).start()
    app.run(host='0.0.0.0', port=10000)
