import os
import requests
from datetime import datetime
from flask import Flask, request, redirect, jsonify, render_template_string

app = Flask(__name__)

# ===== CONFIG - Render Environment la Irundhu Varum =====
ALICE_API_KEY = os.environ.get("ALICE_API_KEY", "")
ALICE_SECRET = os.environ.get("ALICE_SECRET", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# AliceBlue Token - Login Aana Approm Kidaikkum
ACCESS_TOKEN = os.environ.get("ALICE_ACCESS_TOKEN", "")

# ===== TELEGRAM =====
def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram NOT Configured")
        return False
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
        r = requests.post(url, data=data, timeout=10)
        print("Telegram:", r.text)
        return r.status_code == 200
    except Exception as e:
        print("Telegram Error:", e)
        return False

# ===== ALICEBLUE HELPERS =====
def get_ip():
    try:
        return requests.get("https://api.ipify.org", timeout=5).text
    except:
        return "Unknown"

def get_funds():
    if not ACCESS_TOKEN:
        return {"funds": 0, "status": "Login Pannala"}
    try:
        # AliceBlue Funds API - Unga App ku Yetha Maadhiri Maathikonga
        url = "https://ant.aliceblueonline.com/rest/AliceBlueAPIService/api/limits/getRmsLimits"
        headers = {"Authorization": f"Bearer {ACCESS_TOKEN}", "Content-Type": "application/json"}
        r = requests.post(url, headers=headers, json={}, timeout=10)
        return {"funds": r.text[:200], "status": "OK"}
    except Exception as e:
        return {"funds": 0, "status": str(e)}

# ===== ROUTES =====
@app.route('/')
def home():
    ip = get_ip()
    funds = get_funds()
    html = f"""
    <html><head><title>Alice Bot Dashboard</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>body{{font-family:Arial;padding:20px;background:#f5f5f5}} .card{{background:white;padding:20px;border-radius:10px;margin-bottom:15px}} .btn{{display:inline-block;padding:12px 20px;background:#0088cc;color:white;text-decoration:none;border-radius:8px;margin:5px}} .btn2{{background:#28a745}} .btn3{{background:#ff9800}}</style>
    </head><body>
    <h2>🤖 Alice_ygyu_bot Dashboard</h2>
    <div class="card">
        <b>Render IP:</b> {ip}<br>
        <b>Funds:</b> {funds}<br>
        <b>Time:</b> {datetime.now()}<br>
        <b>Telegram Chat ID:</b> {TELEGRAM_CHAT_ID}<br>
        <b>Telegram:</b> {'✅ Configured' if TELEGRAM_BOT_TOKEN else '❌ NOT Configured'}
    </div>
    <div class="card">
        <a class="btn" href="/test_telegram">📩 Test Telegram</a>
        <a class="btn btn2" href="/login">🔐 AliceBlue Login</a>
        <a class="btn btn3" href="/debug">🔍 Debug</a>
    </div>
    <div class="card">
        <h3>IP Whitelist Seinga!</h3>
        <p>AliceBlue Portal la - Indha IP-a Add Pannunga:<br><b>{ip}</b></p>
    </div>
    </body></html>
    """
    return html

@app.route('/test_telegram')
def test_telegram():
    ok = send_telegram(f"✅ Alice Bot Test Success!\nTime: {datetime.now()}\nDashboard Connected!")
    if ok:
        return "✅ Telegram Sent! Unga Telegram Check Pannunga! @Alice_ygyu_bot"
    else:
        return "❌ Telegram Failed! Render Environment la TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID Check Pannunga!"

@app.route('/login')
def login():
    # AliceBlue Login URL
    url = f"https://ant.aliceblueonline.com/?appcode={ALICE_API_KEY}"
    return redirect(url)

@app.route('/callback')
def callback():
    global ACCESS_TOKEN
    code = request.args.get("authCode") or request.args.get("code") or ""
    # Inga - Auth Code vaichu - Access Token Vaanganum
    send_telegram(f"🔐 AliceBlue Login Callback Vandhuduchu!\nCode: {code[:10]}...")
    return f"Login Callback Received! Code: {code[:10]}... <br><a href='/'>Dashboard</a>"

@app.route('/debug')
def debug():
    return jsonify({
        "ip": get_ip(),
        "telegram_configured": bool(TELEGRAM_BOT_TOKEN),
        "chat_id": TELEGRAM_CHAT_ID,
        "alice_api_key_set": bool(ALICE_API_KEY),
        "time": str(datetime.now())
    })

@app.route('/order_test')
def order_test():
    # Test Order Alert
    send_telegram(f"🚀 ORDER PLACED: TEST NIFTY 100 Qty @ 100\nTime: {datetime.now()}")
    return "Order Alert Sent! Telegram Check Pannunga!"

# ===== ORDER PLACE PANNA - INGA ALERT VARUM =====
def place_order(symbol, qty, price):
    # Unga Order Logic Inga Varum
    # Success Aana:
    send_telegram(f"🚀 ORDER PLACED: {symbol} {qty} @ {price}\nTime: {datetime.now()}")
    # Fail Aana:
    # send_telegram(f"❌ ORDER FAILED: {symbol} - Error")

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
