import os
import time
import logging
import sqlite3
from threading import Thread
from dataclasses import dataclass

import telebot
from telebot import types
from flask import Flask, jsonify

import requests
from datetime import datetime

# --- CONFIG ---
@dataclass
class BotConfig:
    TOKEN: str = os.getenv('BOT_TOKEN', '8368212048:AAF094UtSmRBYB98JUtVwYHzREuVicQFIOs')
    ADMIN_ID: int = int(os.getenv('ADMIN_ID', '7276479457'))
    WEBHOOK_PORT: int = int(os.getenv('PORT', 8080))
    MAX_MESSAGE_LENGTH: int = 4000

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

config = BotConfig()
DB_FILE = "musicstudio.db"

def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                first_interaction TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                total_messages INTEGER DEFAULT 0,
                in_dialog BOOLEAN DEFAULT 0,
                dialog_with INTEGER DEFAULT NULL
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT,
                full_name TEXT,
                message_text TEXT,
                message_type TEXT DEFAULT 'text',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_from_admin BOOLEAN DEFAULT 0,
                dialog_id INTEGER
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS dialogs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                admin_id INTEGER NOT NULL,
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ended_at TIMESTAMP DEFAULT NULL,
                is_active BOOLEAN DEFAULT 1
            )
        ''')
        conn.commit()
logger.info("DB: Initializing database...")
init_db()

try:
    bot = telebot.TeleBot(config.TOKEN)
    bot_info = bot.get_me()
    logger.info(f"Bot token is valid! Bot name: {bot_info.first_name} (@{bot_info.username})")
except Exception as token_error:
    logger.error(f"Invalid bot token: {token_error}")
    exit(1)

def save_user(user_id, username, full_name):
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute('SELECT user_id FROM users WHERE user_id = ?', (user_id,))
        if c.fetchone():
            c.execute('''
                UPDATE users SET username=?, full_name=?, last_activity=?, total_messages=total_messages+1
                WHERE user_id=?
            ''', (username, full_name, datetime.now(), user_id))
        else:
            c.execute('''
                INSERT INTO users (user_id, username, full_name, last_activity, total_messages, in_dialog)
                VALUES (?, ?, ?, ?, 1, 0)
            ''', (user_id, username, full_name, datetime.now()))
        conn.commit()

def save_message(user_id, username, full_name, message_text, message_type='text', is_from_admin=False, dialog_id=None):
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute('''
            INSERT INTO messages (user_id, username, full_name, message_text, message_type, is_from_admin, dialog_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, username, full_name, message_text, message_type, int(is_from_admin), dialog_id))
        conn.commit()

def start_dialog(user_id, admin_id):
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute('SELECT id FROM dialogs WHERE user_id=? AND is_active=1', (user_id,))
        row = c.fetchone()
        if row:
            return row[0]
        c.execute('INSERT INTO dialogs (user_id, admin_id) VALUES (?, ?)', (user_id, admin_id))
        dialog_id = c.lastrowid
        c.execute('UPDATE users SET in_dialog=1, dialog_with=? WHERE user_id=?', (admin_id, user_id))
        conn.commit()
        return dialog_id

def end_dialog(user_id):
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute('UPDATE dialogs SET is_active=0, ended_at=? WHERE user_id=? AND is_active=1', (datetime.now(), user_id))
        c.execute('UPDATE users SET in_dialog=0, dialog_with=NULL WHERE user_id=?', (user_id,))
        conn.commit()

def get_active_dialog(user_id):
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute('SELECT id, admin_id FROM dialogs WHERE user_id=? AND is_active=1', (user_id,))
        return c.fetchone()

def get_user_info(user_id):
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute('SELECT username, full_name, in_dialog, dialog_with FROM users WHERE user_id=?', (user_id,))
        return c.fetchone()

def get_all_users():
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute('SELECT user_id, username, full_name, total_messages, last_activity, in_dialog FROM users WHERE user_id != ? ORDER BY in_dialog DESC, last_activity DESC', (config.ADMIN_ID,))
        return c.fetchall()

def get_admin_active_dialogs():
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute('''
            SELECT d.id, d.user_id, u.username, u.full_name, d.started_at,
              (SELECT COUNT(*) FROM messages m WHERE m.dialog_id = d.id) as msg_count
            FROM dialogs d
            JOIN users u ON d.user_id = u.user_id
            WHERE d.is_active=1 AND d.admin_id=?
            ORDER BY d.started_at DESC
        ''', (config.ADMIN_ID,))
        return c.fetchall()

def main_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton("💬 Почати діалог"),
        types.KeyboardButton("ℹ️ Про бота"),
        types.KeyboardButton("📞 Контакти")
    )
    return markup

def dialog_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("❌ Завершити діалог"))
    return markup

def admin_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(
        types.KeyboardButton("💬 Активні діалоги"),
        types.KeyboardButton("🆕 Почати новий діалог"),
        types.KeyboardButton("👥 Список користувачів"),
        types.KeyboardButton("📊 Статистика"),
        types.KeyboardButton("📢 Розсилка всім")
    )
    return markup

def admin_dialog_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(
        types.KeyboardButton("❌ Завершити діалог"),
        types.KeyboardButton("🔄 Перейти до іншого діалогу"),
        types.KeyboardButton("🏠 Головне меню")
    )
    return markup

def cancel_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("❌ Скасувати"))
    return markup

admin_state = {}
BROADCAST = "broadcast"
ADMIN_DIALOG = "admin_dialog"

@bot.message_handler(commands=['start'])
def handle_start(message):
    user = message.from_user
    save_user(user.id, user.username, user.full_name)
    if user.id == config.ADMIN_ID:
        bot.send_message(
            user.id,
            "👨‍💼 <b>Адмін панель</b>\n\nВикористовуйте кнопки для управління ботом.",
            reply_markup=admin_keyboard(),
            parse_mode="HTML"
        )
        admin_state.clear()
    else:
        dialog = get_active_dialog(user.id)
        if dialog:
            bot.send_message(
                user.id,
                "💬 <b>Ви повернулись до діалогу з адміністратором!</b>\n\nПишіть повідомлення - адміністратор їх бачить в реальному часі!",
                reply_markup=dialog_keyboard(),
                parse_mode="HTML"
            )
        else:
            bot.send_message(
                user.id,
                f"👋 <b>Привіт, {user.first_name}!</b>\n\n🤖 Я бот-консультант!\n\nВиберіть дію з меню:",
                reply_markup=main_keyboard(),
                parse_mode="HTML"
            )

@bot.message_handler(func=lambda m: m.text == "💬 Почати діалог")
def start_dialog_user(message):
    user = message.from_user
    dialog = get_active_dialog(user.id)
    if dialog:
        bot.send_message(
            user.id,
            "💬 <b>Ви повернулись до поточного діалогу!</b>",
            reply_markup=dialog_keyboard(),
            parse_mode="HTML"
        )
        return
    dialog_id = start_dialog(user.id, config.ADMIN_ID)
    bot.send_message(
        user.id,
        "✅ <b>Діалог розпочато!</b>\nПишіть повідомлення адміністратору.",
        reply_markup=dialog_keyboard(),
        parse_mode="HTML"
    )
    admin_text = (
        f"🆕 <b>Новий діалог розпочато!</b>\n\n"
        f"👤 <b>Користувач:</b> {user.full_name}\n"
        f"🆔 <b>ID:</b> <code>{user.id}</code>\n"
        f"📧 <b>Username:</b> @{user.username or 'немає'}"
    )
    try:
        bot.send_message(config.ADMIN_ID, admin_text, parse_mode="HTML")
    except Exception as e:
        logger.warning(f"ADMIN notify fail: {e}")

@bot.message_handler(func=lambda m: m.text == "❌ Завершити діалог")
def end_dialog_user(message):
    user_id = message.from_user.id
    dialog = get_active_dialog(user_id)
    if not dialog:
        bot.send_message(
            user_id,
            "❌ Ви не в діалозі",
            reply_markup=main_keyboard()
        )
        return
    end_dialog(user_id)
    bot.send_message(
        user_id,
        "✅ <b>Діалог завершено</b>\nДякуємо за спілкування!",
        reply_markup=main_keyboard(),
        parse_mode="HTML"
    )
    try:
        user_info = get_user_info(user_id)
        if user_info:
            username, full_name, _, _ = user_info
            bot.send_message(
                config.ADMIN_ID,
                f"❌ <b>Діалог завершено користувачем</b>\n\n👤 {full_name} (@{username or 'немає'})",
                parse_mode="HTML"
            )
    except:
        pass

# --- ЮЗЕР ПИШЕ (ДІАЛОГ) ---
@bot.message_handler(func=lambda m: get_active_dialog(m.from_user.id) is not None and m.from_user.id != config.ADMIN_ID)
def handle_user_dialog_message(message):
    user = message.from_user
    dialog = get_active_dialog(user.id)
    if not dialog:
        bot.send_message(
            user.id,
            "❌ Діалог не активний. Повертаємось до головного меню.",
            reply_markup=main_keyboard()
        )
        return
    dialog_id, admin_id = dialog
    message_text = message.text or "[Медіа файл]"
    save_message(user.id, user.username, user.full_name, message_text, "text", False, dialog_id)
    # Forward адміну, щоб reply працював
    bot.forward_message(admin_id, user.id, message.message_id)
    bot.send_message(
        user.id,
        "✅ Повідомлення відправлено!",
        reply_to_message_id=message.message_id
    )

# --- АДМІН ВІДПОВІДАЄ ЧЕРЕЗ REPLY ---
@bot.message_handler(func=lambda m: m.from_user.id == config.ADMIN_ID)
def handle_admin_message(message):
    # Якщо reply на forward від бота
    if message.reply_to_message and message.reply_to_message.forward_from:
        user_id = message.reply_to_message.forward_from.id
        dialog = get_active_dialog(user_id)
        if dialog:
            dialog_id = dialog[0]
        else:
            dialog_id = start_dialog(user_id, config.ADMIN_ID)
        save_message(user_id, "admin", "Адміністратор", message.text, "text", True, dialog_id)
        user_text = f"👨‍💼 <b>Адмін:</b> {message.text}"
        try:
            bot.send_message(user_id, user_text, parse_mode="HTML")
            bot.send_message(
                config.ADMIN_ID,
                "✅ Повідомлення відправлено!",
                reply_to_message_id=message.message_id
            )
        except Exception as e:
            bot.send_message(config.ADMIN_ID, f"❌ Не вдалося надіслати користувачу: {e}")
        return
    # Якщо ні — показує підказку
    bot.send_message(
        config.ADMIN_ID,
        "❓ Щоб відповісти користувачу — відповідайте на forward-повідомлення від юзера.",
        reply_markup=admin_keyboard()
    )

app = Flask(__name__)
bot_start_time = time.time()

@app.route('/')
def health_check():
    uptime_seconds = int(time.time() - bot_start_time)
    uptime_hours = uptime_seconds // 3600
    uptime_minutes = (uptime_seconds % 3600) // 60
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM users")
        users = c.fetchone()[0]
    return f"""
    <h1>🎵 Kuznya Music Studio Bot</h1>
    <p><strong>Статус:</strong> ✅ Активний</p>
    <p><strong>Uptime:</strong> {uptime_hours}год {uptime_minutes}хв</p>
    <p><strong>Час запуску:</strong> {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(bot_start_time))}</p>
    <p><strong>Поточний час:</strong> {time.strftime('%Y-%m-%d %H:%M:%S')}</p>
    <p><strong>Користувачів:</strong> {users}</p>
    """

@app.route('/health')
def health():
    try:
        bot_info = bot.get_me()
        with sqlite3.connect(DB_FILE) as conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM users")
            users = c.fetchone()[0]
        return jsonify({
            "status": "healthy",
            "timestamp": time.time(),
            "uptime_seconds": int(time.time() - bot_start_time),
            "bot_username": bot_info.username,
            "total_users": users,
            "version": "3.0-telebot"
        }), 200
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return jsonify({
            "status": "error",
            "error": str(e),
            "timestamp": time.time()
        }), 500

@app.route('/ping')
def ping():
    return "pong", 200

@app.route('/status')
def status():
    try:
        with sqlite3.connect(DB_FILE) as conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM users")
            users = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM dialogs WHERE is_active=1")
            active = c.fetchone()[0]
        return jsonify({
            "bot_status": "running",
            "uptime_seconds": int(time.time() - bot_start_time),
            "total_users": users,
            "active_chats": active,
            "admin_id": config.ADMIN_ID,
            "timestamp": time.time()
        })
    except Exception as e:
        logger.error(f"Status check failed: {e}")
        return jsonify({
            "bot_status": "error",
            "error": str(e),
            "timestamp": time.time()
        }), 500

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

def self_ping():
    port = config.WEBHOOK_PORT
    url = f"http://localhost:{port}/keepalive"
    while True:
        try:
            r = requests.get(url, timeout=10)
            print(f"[SELF-PING] Pinged {url} ({r.status_code})")
        except Exception as e:
            print(f"[SELF-PING] Error pinging {url}: {e}")
        time.sleep(300)

if __name__ == "__main__":
    try:
        logger.info("Starting Music Studio Bot...")
        flask_thread = Thread(target=run_flask, daemon=True)
        flask_thread.start()
        selfping_thread = Thread(target=self_ping, daemon=True)
        selfping_thread.start()
        time.sleep(5)
        logger.info("🎵 Music Studio Bot started successfully!")
        logger.info(f"Admin ID: {config.ADMIN_ID}")
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
