
import os
from flask import Flask

app = Flask(__name__)

@app.route('/')
def home():
    return "<h1>SKY59589 BOT LIVE 24x7 ✅</h1><p>Rs.59964 - Coimbatore</p><p>gopacket-bot is Live!</p>"

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
