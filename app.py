import os
from flask import Flask
import threading, time
from datetime import datetime

app = Flask(__name__)

def sky_bot():
    print("SKY59589 BOT STARTED")
    while True:
        print(f"BOT LIVE {datetime.now()}")
        time.sleep(60)

@app.route('/')
def home():
    return f"<h1>SKY59589 BOT LIVE 24x7 ✅</h1><p>Rs.59964 - Coimbatore</p><p>{datetime.now()}</p><p>Link: gopacket-bot.onrender.com</p>"

threading.Thread(target=sky_bot, daemon=True).start()

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    print(f"Starting on port {port}")
    app.run(host='0.0.0.0', port=port)
