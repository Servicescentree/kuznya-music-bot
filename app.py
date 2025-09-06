import os
import time
import html
import logging
import sqlite3
from threading import Thread
from typing import Optional, Dict, Any
from dataclasses import dataclass
from contextlib import contextmanager

import telebot
from telebot import types
from flask import Flask, request, jsonify
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration
@dataclass
class BotConfig:
    TOKEN: str = os.getenv('BOT_TOKEN', '8368212048:AAFPu81rvI7ISpmtixdgD1cOybAQ6T_rMjI')
    ADMIN_ID: int = 7276479457
    CHANNEL_URL: str = 'https://t.me/kuznya_music'
    EXAMPLES_URL: str = 'https://t.me/kuznya_music/41'
    DATABASE_PATH: str = 'bot_data.db'
    WEBHOOK_PORT: int = int(os.getenv('PORT', 8080))
    MAX_MESSAGE_LENGTH: int = 4000
    RATE_LIMIT_MESSAGES: int = 5

# Text messages
class Messages:
    WELCOME = """Привіт, {}! 👋
Ласкаво просимо до музичної студії Kuznya Music!
Оберіть дію з меню:"""
    
    RECORDING_PROMPT = """🎤 *Запис треку*

Опишіть ваші побажання:
• Запис, Зведення
• Аранжування 
• Референси (приклади)
• Терміни (коли хочете записатись)

_Ваше повідомлення буде передано адміністратору_"""
    
    EXAMPLES_INFO = """🎵 *Наші роботи:*
{}
Тут ви знайдете найкращі зразки нашої творчості!"""
    
    CHANNEL_INFO = """📢 *Підписуйтесь на наш канал:*
{}
Там ви знайдете:
• Нові роботи
• Закулісся студії
• Акції та знижки"""
    
    CONTACTS_INFO = """📲 *Контакти студії:*
Telegram: @kuznya_music
Або використовуйте кнопку '🎤 Записати трек' для прямого зв'язку"""
    
    MESSAGE_SENT = """✅ Повідомлення відправлено адміністратору!
Очікуйте відповіді...
_Ви можете відправити додаткові повідомлення або завершити діалог_"""
    
    DIALOG_ENDED = "✅ Діалог завершено. Повертаємося до головного меню."
    ADMIN_REPLY = "💬 *Відповідь від адміністратора:*\n\n{}"
    USE_MENU_BUTTONS = "🤔 Використовуйте кнопки меню для навігації"
    
    # Error messages
    ERROR_SEND_FAILED = "❌ Помилка при відправці повідомлення. Спробуйте пізніше."
    ERROR_MESSAGE_TOO_LONG = f"❌ Повідомлення занадто довге. Максимум {BotConfig.MAX_MESSAGE_LENGTH} символів."
    ERROR_RATE_LIMITED = "❌ Забагато повідомлень. Зачекайте хвилинку."
    ERROR_INVALID_INPUT = "❌ Некоректне повідомлення. Спробуйте ще раз."

# User states
class UserStates:
    IDLE = 'idle'
    WAITING_FOR_MESSAGE = 'waiting_for_message'
    ADMIN_REPLYING = 'admin_replying'

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Initialize bot
config = BotConfig()
bot = telebot.TeleBot(config.TOKEN)

# Database setup
def init_database():
    with sqlite3.connect(config.DATABASE_PATH) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS user_states (
                user_id INTEGER PRIMARY KEY,
                state TEXT DEFAULT 'idle',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS user_sessions (
                user_id INTEGER PRIMARY KEY,
                admin_message_id INTEGER,
                user_message_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS rate_limits (
                user_id INTEGER PRIMARY KEY,
                message_count INTEGER DEFAULT 0,
                last_reset TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''')
        conn.commit()

@contextmanager
def get_db_connection():
    conn = sqlite3.connect(config.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

# DatabaseManager, validate_message, sanitize_input, keyboards, helper functions, handlers
# копіюємо їх без змін з твого коду

# Flask app
app = Flask('')

bot_start_time = time.time()

@app.route('/')
def health_check():
    uptime_seconds = int(time.time() - bot_start_time)
    uptime_hours = uptime_seconds // 3600
    uptime_minutes = (uptime_seconds % 3600) // 60
    return f"<h1>🎵 Kuznya Music Studio Bot</h1><p>✅ Активний</p><p>Uptime: {uptime_hours}год {uptime_minutes}хв</p>"

# Webhook endpoint
@app.route(f'/{config.TOKEN}', methods=['POST'])
def receive_update():
    json_str = request.get_data().decode("UTF-8")
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "ok", 200

@app.route('/keepalive')
def keep_alive():
    return jsonify({"message": "Bot is alive!", "uptime": int(time.time() - bot_start_time)})

def run_flask():
    app.run(host='0.0.0.0', port=config.WEBHOOK_PORT, debug=False, threaded=True)

# Main execution
if __name__ == "__main__":
    init_database()
    logger.info("Database initialized successfully")

    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logger.info(f"Flask server started on port {config.WEBHOOK_PORT}")

    WEBHOOK_URL = f"https://services.freevps.xyz/{config.TOKEN}"
    bot.remove_webhook()
    time.sleep(1)
    bot.set_webhook(url=WEBHOOK_URL)
    logger.info(f"Webhook set to {WEBHOOK_URL}")

    logger.info("🎵 Music Studio Bot started successfully! Вебхук активований")
