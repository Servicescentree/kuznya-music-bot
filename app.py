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

import requests  # <-- для self-ping

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

# === TEXTS ===
class Messages:
    WELCOME = """Привіт, {}! 👋
Ласкаво просимо до музичної студії Kuznya Music!

Оберіть дію з меню:"""
    EXAMPLES_INFO = """🎵 *Наші роботи:*\n\nПослухати приклади можна тут:\n{}"""
    CHANNEL_INFO = """📢 *Підписуйтесь на наш канал:*\n\n{}"""
    CONTACTS_INFO = """📲 *Контакти студії:*\nTelegram: @kuznya_music"""
    ABOUT_INFO = """ℹ️ *Про студію*\n\nKuznya Music - сучасна музична студія для запису, зведення, майстерингу, аранжування та творчих експериментів."""
    DIALOG_STARTED = "✅ Діалог розпочато! Пишіть повідомлення адміністратору."
    DIALOG_ENDED_USER = "✅ Діалог завершено. Дякуємо за спілкування!"
    DIALOG_ENDED_ADMIN = "✅ Діалог завершено адміністратором. Ви можете почати новий діалог!"
    ADMIN_PANEL = "👨‍💼 <b>Адмін-панель</b>\n\nОберіть дію:"
    ERROR_SEND_FAILED = "❌ Помилка при відправці повідомлення. Спробуйте пізніше."
    USE_MENU_BUTTONS = "🤔 Використовуйте кнопки меню для навігації"
    BROADCAST_PROMPT = "📢 Введіть текст для розсилки всім користувачам або натисніть '❌ Скасувати'"
    BROADCAST_DONE = "📊 Розсилка завершена!"
    BROADCAST_CANCELLED = "❌ Розсилка скасована."

# === ENHANCED DIALOG MANAGER ===
class EnhancedDialogManager:
    def __init__(self):
        self.active_dialogs = {}
        self.admin_current_dialog = {}
        self.message_history = {}
        self.users = {}
        self.user_states = {}
        self.stats = {
            'total_messages': 0,
            'total_dialogs': 0,
            'bot_start_time': time.time()
        }
        self.admin_broadcast_mode = False
        self.broadcast_text = ""

    def save_user(self, user_id, username, full_name):
        now = time.time()
        if user_id in self.users:
            self.users[user_id].update({
                'username': username,
                'full_name': full_name,
                'last_activity': now,
                'total_messages': self.users[user_id].get('total_messages', 0) + 1
            })
        else:
            self.users[user_id] = {
                'username': username,
                'full_name': full_name,
                'first_seen': now,
                'last_activity': now,
                'total_messages': 1
            }

    def get_user_info(self, user_id):
        return self.users.get(user_id, {})

    def get_all_users(self):
        return [
            (user_id, info['username'], info['full_name'], info['total_messages'], info['last_activity'], self.is_user_in_dialog(user_id))
            for user_id, info in self.users.items()
        ]

    def set_user_state(self, user_id, state):
        self.user_states[user_id] = state

    def get_user_state(self, user_id):
        return self.user_states.get(user_id, 'idle')

    def clear_user_state(self, user_id):
        self.user_states.pop(user_id, None)

    def start_dialog(self, user_id, admin_id):
        if user_id in self.active_dialogs:
            return False
        dialog_id = f"{user_id}_{admin_id}_{int(time.time())}"
        self.active_dialogs[user_id] = {
            'admin_id': admin_id,
            'started_at': time.time(),
            'message_count': 0,
            'dialog_id': dialog_id
        }
        self.message_history[dialog_id] = []
        self.stats['total_dialogs'] += 1
        self.set_user_state(user_id, 'in_dialog')
        return dialog_id

    def end_dialog(self, user_id):
        if user_id in self.active_dialogs:
            admin_id = self.active_dialogs[user_id]['admin_id']
            if self.admin_current_dialog.get(admin_id) == user_id:
                self.admin_current_dialog.pop(admin_id, None)
                self.clear_user_state(admin_id)
            dialog_id = self.active_dialogs[user_id]['dialog_id']
            self.active_dialogs.pop(user_id, None)
            self.clear_user_state(user_id)

    def is_user_in_dialog(self, user_id):
        return user_id in self.active_dialogs

    def get_active_dialogs(self):
        dialogs = []
        for user_id, dialog_info in self.active_dialogs.items():
            user_info = self.get_user_info(user_id)
            dialogs.append({
                'user_id': user_id,
                'admin_id': dialog_info['admin_id'],
                'started_at': dialog_info['started_at'],
                'message_count': dialog_info['message_count'],
                'username': user_info.get('username', ''),
                'full_name': user_info.get('full_name', 'Unknown'),
                'dialog_id': dialog_info['dialog_id']
            })
        return sorted(dialogs, key=lambda x: x['started_at'], reverse=True)

    def set_admin_current_dialog(self, admin_id, user_id):
        self.admin_current_dialog[admin_id] = user_id
        self.set_user_state(admin_id, 'admin_in_dialog')

    def get_admin_current_dialog(self, admin_id):
        return self.admin_current_dialog.get(admin_id)

    def save_message(self, user_id, message_text, is_admin=False):
        self.stats['total_messages'] += 1
        dialog_info = self.active_dialogs.get(user_id)
        if dialog_info:
            dialog_id = dialog_info['dialog_id']
            self.message_history[dialog_id].append({
                'user_id': user_id,
                'message': message_text,
                'timestamp': time.time(),
                'is_admin': is_admin
            })
            self.active_dialogs[user_id]['message_count'] += 1

    def get_statistics(self):
        return {
            'total_users': len(self.users),
            'active_dialogs': len(self.active_dialogs),
            'total_messages': self.stats['total_messages'],
            'total_dialogs': self.stats['total_dialogs'],
            'uptime_seconds': int(time.time() - self.stats['bot_start_time']),
            'users_in_dialog': len([u for u in self.users.keys() if self.is_user_in_dialog(u)])
        }

# === KEYBOARDS ===
def get_main_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton("💬 Почати діалог"),
        types.KeyboardButton("🎧 Наші роботи")
    )
    markup.add(
        types.KeyboardButton("📢 Підписатися"),
        types.KeyboardButton("📲 Контакти")
    )
    markup.add(types.KeyboardButton("ℹ️ Про студію"))
    return markup

def get_dialog_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    markup.add(types.KeyboardButton("❌ Завершити діалог"))
    return markup

def get_admin_main_keyboard(dm):
    stats = dm.get_statistics()
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton(f"💬 Активні діалоги ({stats['active_dialogs']})"),
        types.KeyboardButton("🆕 Новий діалог")
    )
    markup.add(
        types.KeyboardButton(f"👥 Користувачі ({stats['total_users']})"),
        types.KeyboardButton("📊 Статистика")
    )
    markup.add(types.KeyboardButton("📢 Розсилка"))
    return markup

def get_admin_dialog_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton("❌ Завершити діалог"),
        types.KeyboardButton("🔄 Інший діалог")
    )
    markup.add(types.KeyboardButton("🏠 Головне меню"))
    return markup

def get_cancel_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    markup.add(types.KeyboardButton("❌ Скасувати"))
    return markup

# === LOGGING ===
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

config = BotConfig()
dialog_manager = EnhancedDialogManager()

# === BOT INIT ===
if not config.TOKEN or not config.ADMIN_ID:
    logger.error("BOT_TOKEN or ADMIN_ID not set")
    exit(1)

bot = telebot.TeleBot(config.TOKEN)

def is_admin(user_id): return user_id == config.ADMIN_ID

def get_user_info(user):
    return {
        'id': user.id,
        'username': user.username or "",
        'first_name': user.first_name or "",
        'last_name': user.last_name or "",
        'full_name': f"{user.first_name or ''} {user.last_name or ''}".strip()
    }

def sanitize_input(text): return html.escape(text.strip())

# === MESSAGE HANDLERS ===
# ... (тут залишаєш усі свої обробники, як раніше)

# === FLASK HEALTH ===
app = Flask(__name__)
bot_start_time = time.time()

@app.route('/')
def health_check():
    uptime_seconds = int(time.time() - bot_start_time)
    uptime_hours = uptime_seconds // 3600
    uptime_minutes = (uptime_seconds % 3600) // 60
    return f"""
    <h1>🎵 Kuznya Music Studio Bot</h1>
    <p><strong>Статус:</strong> ✅ Активний</p>
    <p><strong>Uptime:</strong> {uptime_hours}год {uptime_minutes}хв</p>
    <p><strong>Час запуску:</strong> {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(bot_start_time))}</p>
    <p><strong>Поточний час:</strong> {time.strftime('%Y-%m-%d %H:%M:%S')}</p>
    <p><strong>Користувачів:</strong> {len(dialog_manager.users)}</p>
    """

@app.route('/keepalive')
def keep_alive():
    return jsonify({
        "message": "Bot is alive!",
        "timestamp": time.time(),
        "uptime": int(time.time() - bot_start_time)
    })

def run_flask():
    app.run(
        host='0.0.0.0',
        port=config.WEBHOOK_PORT,
        debug=False,
        threaded=True
    )

# === ПРОСТИЙ SELF-PING БЕЗ ENV ===
def self_ping():
    port = config.WEBHOOK_PORT
    url = f"http://localhost:{port}/keepalive"
    while True:
        try:
            r = requests.get(url, timeout=10)
            print(f"[SELF-PING] Pinged {url} ({r.status_code})")
        except Exception as e:
            print(f"[SELF-PING] Error pinging {url}: {e}")
        time.sleep(300)  # 5 хвилин

# === MAIN EXECUTION ===
if __name__ == "__main__":
    try:
        logger.info("Starting Kuznya Music Studio Bot...")
        flask_thread = Thread(target=run_flask, daemon=True)
        flask_thread.start()
        logger.info(f"Flask server started on port {config.WEBHOOK_PORT}")

        # --- Self-ping запускаємо окремим потоком ---
        selfping_thread = Thread(target=self_ping, daemon=True)
        selfping_thread.start()
        logger.info("Self-ping thread started.")

        time.sleep(2)
        bot.polling(none_stop=True, interval=1, timeout=30)

    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
        try:
            bot.stop_polling()
        except:
            pass
    except Exception as e:
        logger.critical(f"Critical error: {e}")
        try:
            bot.stop_polling()
        except:
            pass
        exit(1)
