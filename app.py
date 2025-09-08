import os
import time
import html
import logging
import random
import string
from threading import Thread
from typing import Optional, Dict, Any
from dataclasses import dataclass

import telebot
from telebot import types
from flask import Flask, jsonify

# === CONFIGURATION ===
@dataclass
class BotConfig:
    TOKEN: str = os.getenv('BOT_TOKEN', '8368212048:AAF094UtSmRBYB98JUtVwYHzREuVicQFIOs')
    ADMIN_ID: int = int(os.getenv('ADMIN_ID', '7276479457'))
    CHANNEL_URL: str = 'https://t.me/kuznya_music'
    EXAMPLES_URL: str = 'https://t.me/kuznya_music/41'
    WEBHOOK_PORT: int = int(os.getenv('PORT', 8080))
    MAX_MESSAGE_LENGTH: int = 4000
    RATE_LIMIT_MESSAGES: int = 5

# === FLASK HEALTH ENDPOINT ===
app = Flask(__name__)

@app.route('/ping', methods=['GET', 'HEAD'])
def ping():
    return '', 200

def run_flask():
    app.run(
        host='0.0.0.0',
        port=BotConfig.WEBHOOK_PORT,
        debug=False,
        threaded=True
    )

# ... (далі увесь твій код, запуск Thread - замість Flask(__name__).run...)

if __name__ == "__main__":
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    # далі запуск polling бота
