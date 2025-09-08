import os
import time
import html
import logging
import sqlite3
from threading import Thread
from typing import Optional, Dict, Any
from dataclasses import dataclass

import telebot
from telebot import types
from flask import Flask, jsonify

import requests  # for self-ping
from datetime import datetime

# --- CONFIG ---
@dataclass
class BotConfig:
    TOKEN: str = os.getenv('BOT_TOKEN', '8368212048:AAF094UtSmRBYB98JUtVwYHzREuVicQFIOs')
    ADMIN_ID: int = int(os.getenv('ADMIN_ID', '7276479457'))
    WEBHOOK_PORT: int = int(os.getenv('PORT', 8080))
    MAX_MESSAGE_LENGTH: int = 4000
    RATE_LIMIT_MESSAGES: int = 5

# --- LOGGING ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]  # Only console logging for Render
)
logger = logging.getLogger(__name__)

config = BotConfig()

# --- DATABASE ---
DB_FILE = "musicstudio.db"

def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        # Users
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
        # Messages
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
        # Dialogs
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

# --- TELEGRAM BOT ---
try:
    bot = telebot.TeleBot(config.TOKEN)
    bot_info = bot.get_me()
    logger.info(f"Bot token is valid! Bot name: {bot_info.first_name} (@{bot_info.username})")
except Exception as token_error:
    logger.error(f"Invalid bot token: {token_error}")
    exit(1)

# --- DATABASE HELPERS ---
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

def get_dialog_messages(dialog_id, limit=30):
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute('''
            SELECT message_text, is_from_admin, created_at
            FROM messages
            WHERE dialog_id = ?
            ORDER BY id ASC
            LIMIT ?
        ''', (dialog_id, limit))
        return c.fetchall()

# --- KEYBOARDS ---
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

# --- STATES (simple in-memory for admin) ---
admin_state = {}
BROADCAST = "broadcast"
ADMIN_DIALOG = "admin_dialog"

# --- MESSAGE HANDLERS ---
@bot.message_handler(commands=['start'])
def handle_start(message):
    user = message.from_user
    save_user(user.id, user.username, user.full_name)
    if user.id == config.ADMIN_ID:
        active_dialogs = get_admin_active_dialogs()
        if active_dialogs:
            bot.send_message(
                user.id,
                f"👨‍💼 <b>Адмін панель</b>\n\n🟢 У вас є {len(active_dialogs)} активних діалогів\nВикористовуйте кнопки для управління:",
                reply_markup=admin_keyboard(),
                parse_mode="HTML"
            )
        else:
            bot.send_message(
                user.id,
                "👨‍💼 <b>Адмін панель</b>\n\nЛаскаво просимо в адмін-панель!\nВикористовуйте кнопки для управління ботом.",
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
                f"👋 <b>Привіт, {user.first_name}!</b>\n\n🤖 Я універсальний бот-консультант!\n\nВи можете:\n▫️ Почати діалог з адміністратором\n▫️ Вести спілкування в реальному часі\n▫️ Отримувати швидку підтримку\n\nВиберіть дію з меню:",
                reply_markup=main_keyboard(),
                parse_mode="HTML"
            )

@bot.message_handler(func=lambda m: m.text == "💬 Почати діалог")
def start_dialog_user(message):
    user = message.from_user
    if user.id == config.ADMIN_ID:
        admin_start_new_dialog(message)
        return
    dialog = get_active_dialog(user.id)
    if dialog:
        bot.send_message(
            user.id,
            "💬 <b>Ви повернулись до поточного діалогу!</b>\n\nПишіть повідомлення - адміністратор їх бачить.",
            reply_markup=dialog_keyboard(),
            parse_mode="HTML"
        )
        return
    dialog_id = start_dialog(user.id, config.ADMIN_ID)
    bot.send_message(
        user.id,
        "✅ <b>Діалог розпочато!</b>\n\n💬 Тепер ви можете вести діалог з адміністратором в реальному часі.\nПишіть повідомлення - адміністратор їх бачить миттєво!",
        reply_markup=dialog_keyboard(),
        parse_mode="HTML"
    )
    admin_text = (
        f"🆕 <b>Новий діалог розпочато!</b>\n\n"
        f"👤 <b>Користувач:</b> {user.full_name}\n"
        f"🆔 <b>ID:</b> <code>{user.id}</code>\n"
        f"📧 <b>Username:</b> @{user.username or 'немає'}\n\n"
        f"Використовуйте \"💬 Активні діалоги\" для входу в діалог."
    )
    try:
        bot.send_message(config.ADMIN_ID, admin_text, parse_mode="HTML")
    except Exception as e:
        logger.warning(f"ADMIN notify fail: {e}")

@bot.message_handler(func=lambda m: m.text == "❌ Завершити діалог")
def end_dialog_user(message):
    user_id = message.from_user.id
    if user_id == config.ADMIN_ID:
        if admin_state.get("state") == ADMIN_DIALOG:
            dialog_user_id = admin_state.get("user_id")
            if dialog_user_id:
                end_dialog(dialog_user_id)
                try:
                    bot.send_message(
                        dialog_user_id,
                        "✅ <b>Діалог завершено адміністратором</b>\n\nДякуємо за спілкування! Ви можете розпочати новий діалог в будь-який час.",
                        reply_markup=main_keyboard(),
                        parse_mode="HTML"
                    )
                except:
                    pass
            admin_state.clear()
            bot.send_message(
                config.ADMIN_ID,
                "✅ Діалог завершено",
                reply_markup=admin_keyboard()
            )
        else:
            bot.send_message(
                config.ADMIN_ID,
                "❌ Ви не в діалозі",
                reply_markup=admin_keyboard()
            )
    else:
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
            "✅ <b>Діалог завершено</b>\n\nДякуємо за спілкування! Ви можете розпочати новий діалог в будь-який час.",
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

@bot.message_handler(func=lambda m: m.text == "💬 Активні діалоги" and m.from_user.id == config.ADMIN_ID)
def admin_active_dialogs(message):
    dialogs = get_admin_active_dialogs()
    if not dialogs:
        bot.send_message(
            config.ADMIN_ID,
            "💬 <b>Активні діалоги</b>\n\nНа даний момент немає активних діалогів.\nВикористовуйте \"🆕 Почати новий діалог\" для створення діалогу з користувачем.",
            parse_mode="HTML"
        )
        return
    response = "💬 <b>Ваші активні діалоги:</b>\n\n"
    markup = types.InlineKeyboardMarkup()
    for dialog_id, user_id, username, full_name, started_at, msg_count in dialogs:
        started = datetime.fromisoformat(started_at).strftime("%d.%m %H:%M")
        response += f"👤 <b>{full_name}</b>\n📧 @{username or 'немає'} | 🆔 <code>{user_id}</code>\n📅 Почато: {started} | 💬 Повідомлень: {msg_count}\n\n"
        markup.add(types.InlineKeyboardButton(
            f"💬 {full_name[:20]}{'...' if len(full_name) > 20 else ''}",
            callback_data=f"enter_dialog_{user_id}"
        ))
    bot.send_message(config.ADMIN_ID, response, reply_markup=markup, parse_mode="HTML")

@bot.message_handler(func=lambda m: m.text == "🆕 Почати новий діалог" and m.from_user.id == config.ADMIN_ID)
def admin_start_new_dialog(message):
    users = get_all_users()
    if not users:
        bot.send_message(config.ADMIN_ID, "👥 Користувачів ще немає")
        return
    free_users = [u for u in users if not u[5]]
    response = "🆕 <b>Почати новий діалог з:</b>\n\n"
    markup = types.InlineKeyboardMarkup()
    if not free_users:
        bot.send_message(
            config.ADMIN_ID,
            "🆕 <b>Почати новий діалог</b>\n\n❌ Всі користувачі вже мають активні діалоги.\nВикористовуйте \"💬 Активні діалоги\" для перегляду поточних діалогів.",
            parse_mode="HTML"
        )
        return
    for user_id, username, full_name, total_msg, last_activity, in_dialog in free_users[:15]:
        last_active = datetime.fromisoformat(last_activity).strftime("%d.%m %H:%M")
        response += f"👤 <b>{full_name}</b>\n📧 @{username or 'немає'} | 💬 Повідомлень: {total_msg}\n⏰ Остання активність: {last_active}\n\n"
        markup.add(types.InlineKeyboardButton(
            f"💬 {full_name[:25]}{'...' if len(full_name) > 25 else ''}",
            callback_data=f"start_new_dialog_{user_id}"
        ))
    if len(free_users) > 15:
        response += f"... і ще {len(free_users) - 15} вільних користувачів"
    bot.send_message(config.ADMIN_ID, response, reply_markup=markup, parse_mode="HTML")

@bot.message_handler(func=lambda m: m.text == "🔄 Перейти до іншого діалогу" and m.from_user.id == config.ADMIN_ID)
def admin_switch_dialog(message):
    admin_state.clear()
    admin_active_dialogs(message)

@bot.message_handler(func=lambda m: m.text == "🏠 Головне меню" and m.from_user.id == config.ADMIN_ID)
def admin_return_to_menu(message):
    admin_state.clear()
    bot.send_message(
        config.ADMIN_ID,
        "🏠 Повернення до головного меню",
        reply_markup=admin_keyboard()
    )

@bot.message_handler(func=lambda m: m.text == "📢 Розсилка всім" and m.from_user.id == config.ADMIN_ID)
def broadcast_message(message):
    admin_state.clear()
    admin_state["state"] = BROADCAST
    bot.send_message(
        config.ADMIN_ID,
        "📢 <b>Розсилка повідомлення</b>\n\nНапишіть текст для розсилки всім користувачам:",
        reply_markup=cancel_keyboard(),
        parse_mode="HTML"
    )

@bot.message_handler(func=lambda m: admin_state.get("state") == BROADCAST and m.from_user.id == config.ADMIN_ID)
def process_broadcast(message):
    if message.text == "❌ Скасувати":
        admin_state.clear()
        bot.send_message(
            config.ADMIN_ID, "❌ Розсилка скасована", reply_markup=admin_keyboard()
        )
        return
    broadcast_text = message.text
    users = get_all_users()
    if not users:
        bot.send_message(
            config.ADMIN_ID,
            "❌ Немає користувачів для розсилки",
            reply_markup=admin_keyboard()
        )
        admin_state.clear()
        return
    bot.send_message(config.ADMIN_ID, "📡 Починаю розсилку... Зачекайте.")
    success_count = 0
    blocked_count = 0
    for user_id, username, full_name, _, _, _ in users:
        if user_id == config.ADMIN_ID:
            continue
        try:
            bot.send_message(
                user_id,
                f"📢 <b>Повідомлення адміністратора:</b>\n\n{broadcast_text}",
                parse_mode="HTML"
            )
            success_count += 1
        except Exception as e:
            blocked_count += 1
    bot.send_message(
        config.ADMIN_ID,
        f"📊 <b>Розсилка завершена!</b>\n\n✅ Надіслано: {success_count}\n❌ Заблоковано/помилки: {blocked_count}\n📋 Всього користувачів: {len(users)}\n💬 Текст розсилки: <i>{broadcast_text}</i>",
        reply_markup=admin_keyboard(),
        parse_mode="HTML"
    )
    admin_state.clear()

@bot.message_handler(func=lambda m: m.text == "ℹ️ Про бота")
def about_bot(message):
    bot.send_message(
        message.chat.id,
        "ℹ️ <b>Про бота</b>\n\n🤖 Я універсальний бот-консультант з підтримкою діалогів!\n\nМої можливості:\n▫️ Гнучкі діалоги в реальному часі з адміністратором\n▫️ Можливість повертатися до діалогів\n▫️ Збереження всіх спілкувань\n▫️ Швидка відповідь на питання\n\n💻 Версія: 3.0 (з покращеними діалогами)\n📅 Оновлено: 2025",
        parse_mode="HTML"
    )

@bot.message_handler(func=lambda m: m.text == "📞 Контакти")
def contacts(message):
    bot.send_message(
        message.chat.id,
        "📞 <b>Контакти</b>\n\n🤖 Для зв'язку використовуйте цього бота\n💬 Розпочніть діалог і спілкуйтесь в реальному часі\n\n⏰ Адміністратор зазвичай онлайн і відповідає швидко",
        parse_mode="HTML"
    )

@bot.message_handler(func=lambda m: m.text == "👥 Список користувачів" and m.from_user.id == config.ADMIN_ID)
def users_list(message):
    users = get_all_users()
    if not users:
        bot.send_message(config.ADMIN_ID, "👥 Користувачів ще немає")
        return
    response = "👥 <b>Список всіх користувачів:</b>\n\n"
    for user_id, username, full_name, total_msg, last_activity, in_dialog in users[:20]:
        last_active = datetime.fromisoformat(last_activity).strftime("%d.%m %H:%M")
        status = "🟢 В діалозі" if in_dialog else "⚪ Вільний"
        response += f"👤 <b>{full_name}</b> {status}\n🆔 ID: <code>{user_id}</code>\n📧 @{username or 'немає'}\n📨 Повідомлень: {total_msg}\n⏰ Остання активність: {last_active}\n\n"
    if len(users) > 20:
        response += f"... і ще {len(users) - 20} користувачів"
    bot.send_message(config.ADMIN_ID, response, parse_mode="HTML")

@bot.message_handler(func=lambda m: m.text == "📊 Статистика" and m.from_user.id == config.ADMIN_ID)
def statistics(message):
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM users WHERE user_id != ?", (config.ADMIN_ID,))
        total_users = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM messages")
        total_messages = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM dialogs")
        total_dialogs = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM dialogs WHERE is_active = 1")
        active_dialogs = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM users WHERE in_dialog = 1")
        users_in_dialog = c.fetchone()[0]
    bot.send_message(
        config.ADMIN_ID,
        f"📊 <b>Статистика бота</b>\n\n👥 Всього користувачів: {total_users}\n📨 Всього повідомлень: {total_messages}\n💬 Всього діалогів: {total_dialogs}\n🟢 Активних діалогів: {active_dialogs}\n👤 Користувачів в діалозі: {users_in_dialog}",
        parse_mode="HTML"
    )

# --- CALLBACK HANDLERS ---
@bot.callback_query_handler(func=lambda call: call.data.startswith("start_new_dialog_"))
def start_new_dialog_callback(call):
    if call.from_user.id != config.ADMIN_ID:
        return
    user_id = int(call.data.split("_")[3])
    user_info = get_user_info(user_id)
    if not user_info:
        bot.answer_callback_query(call.id, "Користувача не знайдено")
        return
    username, full_name, in_dialog, dialog_with = user_info
    if in_dialog:
        bot.answer_callback_query(call.id, "Користувач вже в діалозі")
        return
    dialog_id = start_dialog(user_id, config.ADMIN_ID)
    admin_state.clear()
    admin_state["state"] = ADMIN_DIALOG
    admin_state["user_id"] = user_id
    admin_state["dialog_id"] = dialog_id
    bot.edit_message_text(
        f"✅ <b>Новий діалог розпочато з {full_name}!</b>\n\n💬 Пишіть повідомлення - користувач їх бачить миттєво!",
        call.message.chat.id, call.message.message_id, parse_mode="HTML"
    )
    bot.send_message(
        config.ADMIN_ID,
        "Використовуйте кнопки для керування діалогом:",
        reply_markup=admin_dialog_keyboard()
    )
    try:
        bot.send_message(
            user_id,
            "💬 <b>Адміністратор розпочав з вами діалог!</b>\n\nПишіть повідомлення - адміністратор їх бачить в реальному часі.",
            reply_markup=dialog_keyboard(),
            parse_mode="HTML"
        )
    except:
        pass
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("enter_dialog_"))
def admin_enter_dialog(call):
    if call.from_user.id != config.ADMIN_ID:
        return
    user_id = int(call.data.split("_")[2])
    dialog = get_active_dialog(user_id)
    if not dialog:
        bot.answer_callback_query(call.id, "Діалог не активний")
        return
    admin_state.clear()
    admin_state["state"] = ADMIN_DIALOG
    admin_state["user_id"] = user_id
    admin_state["dialog_id"] = dialog[0]
    user_info = get_user_info(user_id)
    username, full_name, _, _ = user_info
    bot.edit_message_text(
        f"💬 <b>Діалог з {full_name}</b>\n\nПишіть повідомлення - користувач їх бачить миттєво!",
        call.message.chat.id, call.message.message_id, parse_mode="HTML"
    )
    bot.send_message(
        config.ADMIN_ID,
        "Використовуйте кнопки для керування діалогом:",
        reply_markup=admin_dialog_keyboard()
    )
    bot.answer_callback_query(call.id)

# --- ДІАЛОГОВІ ПОВІДОМЛЕННЯ ---
@bot.message_handler(func=lambda m: get_active_dialog(m.from_user.id) is not None and m.text not in [
    "❌ Завершити діалог", "🔄 Перейти до іншого діалогу", "🏠 Головне меню"])
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
    admin_text = f"💬 <b>Діалог з {user.full_name}</b>\n\n👤 {message_text}"
    try:
        bot.send_message(admin_id, admin_text, parse_mode="HTML")
    except Exception as e:
        logger.warning(f"ADMIN dialog send error: {e}")
    # Додаємо підтвердження для юзера:
    bot.send_message(
        user.id,
        "✅ Повідомлення відправлено!",
        reply_to_message_id=message.message_id
    )

@bot.message_handler(func=lambda m: m.from_user.id == config.ADMIN_ID and admin_state.get("state") == ADMIN_DIALOG and m.text not in [
    "❌ Завершити діалог", "🔄 Перейти до іншого діалогу", "🏠 Головне меню"])
def handle_admin_dialog_message(message):
    data = admin_state
    user_id = data.get("user_id")
    dialog_id = data.get("dialog_id")
    if not user_id or not dialog_id:
        bot.send_message(config.ADMIN_ID, "Помилка: дані діалогу втрачено", reply_markup=admin_keyboard())
        admin_state.clear()
        return
    message_text = message.text or "[Медіа файл]"
    save_message(user_id, "admin", "Адміністратор", message_text, "text", True, dialog_id)
    user_text = f"👨‍💼 <b>Адмін:</b> {message_text}"
    try:
        bot.send_message(user_id, user_text, parse_mode="HTML")
    except Exception as e:
        bot.send_message(config.ADMIN_ID, f"❌ Не вдалося надіслати користувачу: {e}")
    # Додаємо підтвердження для адміна:
    bot.send_message(
        config.ADMIN_ID,
        "✅ Повідомлення відправлено!",
        reply_to_message_id=message.message_id
    )

# --- UNKNOWN HANDLER ---
@bot.message_handler(func=lambda m: True)
def handle_all_messages(message):
    user_id = message.from_user.id
    save_user(user_id, message.from_user.username, message.from_user.full_name)
    if user_id != config.ADMIN_ID:
        dialog = get_active_dialog(user_id)
        if dialog:
            handle_user_dialog_message(message)
            return
    elif user_id == config.ADMIN_ID and admin_state.get("state") == ADMIN_DIALOG:
        handle_admin_dialog_message(message)
        return
    if user_id == config.ADMIN_ID:
        bot.send_message(
            user_id,
            "❓ Невідома команда. Використовуйте кнопки меню.",
            reply_markup=admin_keyboard()
        )
    else:
        bot.send_message(
            user_id,
            "❓ Не зрозумів вас. Використовуйте кнопки меню або напишіть /start",
            reply_markup=main_keyboard()
        )

# --- FLASK SERVER FOR RENDER/UPTIME/SELF-PING ---
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

# --- SELF-PING ---
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

# --- MAIN ---
if __name__ == "__main__":
    try:
        logger.info("Starting Music Studio Bot...")
        flask_thread = Thread(target=run_flask, daemon=True)
        flask_thread.start()
        logger.info(f"Flask server started on port {config.WEBHOOK_PORT}")
        selfping_thread = Thread(target=self_ping, daemon=True)
        selfping_thread.start()
        logger.info("Self-ping thread started (every 5 minutes).")
        logger.info("Health check endpoints available:")
        logger.info(f"  - Main: http://localhost:{config.WEBHOOK_PORT}/")
        logger.info(f"  - Health: http://localhost:{config.WEBHOOK_PORT}/health")
        logger.info(f"  - Ping: http://localhost:{config.WEBHOOK_PORT}/ping")
        logger.info(f"  - Status: http://localhost:{config.WEBHOOK_PORT}/status")
        try:
            bot.remove_webhook()
            bot.stop_polling()
        except Exception as clear_error:
            logger.warning(f"Error clearing previous instances: {clear_error}")
        time.sleep(5)
        logger.info("🎵 Music Studio Bot started successfully!")
        logger.info(f"Admin ID: {config.ADMIN_ID}")
        logger.info("Bot is polling for messages...")
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
