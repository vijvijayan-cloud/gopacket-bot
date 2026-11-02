from flask import Flask
import threading, time
from datetime import datetime
app = Flask(__name__)
def bot():
    while True:
        print(f"SKY59589 BOT LIVE {datetime.now()}")
        time.sleep(60)
@app.route('/')
def home():
    return f"<h1>SKY59589 BOT LIVE 24x7 ✅</h1><p>Rs.59964 GoPocket Strategy</p><p>Time:{datetime.now()}</p><p>Coimbatore - Abdul's Workspace</p><p>Link: gopacket-bot.onrender.com</p>"
threading.Thread(target=bot, daemon=True).start()
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
