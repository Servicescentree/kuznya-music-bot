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
        self.active_dialogs = {}  # user_id -> {admin_id, started_at, message_count, dialog_id}
        self.admin_current_dialog = {}  # admin_id -> user_id
        self.message_history = {}  # dialog_id -> [{'user_id', 'message', 'timestamp', 'is_admin'}]
        self.users = {}  # user_id -> {...}
        self.user_states = {}  # user_id -> state
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

# === HELPERS ===
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

@bot.message_handler(commands=['start'])
def handle_start(message):
    user_info = get_user_info(message.from_user)
    dialog_manager.save_user(user_info['id'], user_info['username'], user_info['full_name'])
    if is_admin(user_info['id']):
        markup = get_admin_main_keyboard(dialog_manager)
        stats = dialog_manager.get_statistics()
        bot.send_message(
            user_info['id'],
            f"{Messages.ADMIN_PANEL}\n\nАктивних діалогів: {stats['active_dialogs']}\nКористувачів: {stats['total_users']}\nПовідомлень: {stats['total_messages']}",
            reply_markup=markup,
            parse_mode="HTML"
        )
    else:
        if dialog_manager.is_user_in_dialog(user_info['id']):
            markup = get_dialog_keyboard()
            bot.send_message(
                user_info['id'],
                "💬 Ви повернулись у діалог з адміністратором.\nПишіть повідомлення!",
                reply_markup=markup
            )
        else:
            markup = get_main_keyboard()
            bot.send_message(
                user_info['id'],
                Messages.WELCOME.format(user_info['first_name']),
                reply_markup=markup
            )

@bot.message_handler(func=lambda m: m.text == "💬 Почати діалог")
def handle_start_dialog(message):
    user_id = message.from_user.id
    user_info = get_user_info(message.from_user)
    dialog_manager.save_user(user_id, user_info['username'], user_info['full_name'])

    if is_admin(user_id):
        # Адмін створює діалог із користувачем
        handle_admin_new_dialog(message)
        return

    if dialog_manager.is_user_in_dialog(user_id):
        markup = get_dialog_keyboard()
        bot.send_message(
            user_id,
            "💬 Ви вже у діалозі. Можете писати адміністратору.",
            reply_markup=markup
        )
        return

    dialog_manager.start_dialog(user_id, config.ADMIN_ID)
    markup = get_dialog_keyboard()
    bot.send_message(
        user_id,
        Messages.DIALOG_STARTED,
        reply_markup=markup
    )
    # Повідомляємо адміна
    bot.send_message(
        config.ADMIN_ID,
        f"🆕 Новий діалог: {user_info['full_name']} (@{user_info['username']}) [{user_id}]"
    )

@bot.message_handler(func=lambda m: m.text == "❌ Завершити діалог")
def handle_end_dialog(message):
    user_id = message.from_user.id
    user_info = get_user_info(message.from_user)
    dialog_manager.save_user(user_id, user_info['username'], user_info['full_name'])

    if is_admin(user_id):
        dialog_user_id = dialog_manager.get_admin_current_dialog(user_id)
        if dialog_user_id:
            dialog_manager.end_dialog(dialog_user_id)
            bot.send_message(
                dialog_user_id,
                Messages.DIALOG_ENDED_ADMIN,
                reply_markup=get_main_keyboard()
            )
        dialog_manager.clear_user_state(user_id)
        bot.send_message(
            user_id,
            "✅ Діалог завершено.",
            reply_markup=get_admin_main_keyboard(dialog_manager)
        )
    else:
        if not dialog_manager.is_user_in_dialog(user_id):
            bot.send_message(
                user_id,
                "❌ Ви не в діалозі.",
                reply_markup=get_main_keyboard()
            )
            return
        dialog_manager.end_dialog(user_id)
        bot.send_message(
            user_id,
            Messages.DIALOG_ENDED_USER,
            reply_markup=get_main_keyboard()
        )
        bot.send_message(
            config.ADMIN_ID,
            f"❌ Діалог завершено користувачем: [{user_id}]"
        )

@bot.message_handler(func=lambda m: dialog_manager.get_user_state(m.from_user.id) == 'in_dialog')
def handle_user_dialog_message(message):
    user_id = message.from_user.id
    user_info = get_user_info(message.from_user)
    dialog_manager.save_user(user_id, user_info['username'], user_info['full_name'])
    if not dialog_manager.is_user_in_dialog(user_id):
        bot.send_message(
            user_id,
            "❌ Діалог не активний. Повертаємось до головного меню.",
            reply_markup=get_main_keyboard()
        )
        return
    dialog_manager.save_message(user_id, message.text, is_admin=False)
    bot.send_message(
        config.ADMIN_ID,
        f"💬 Від {user_info['full_name']}: {message.text}",
    )

@bot.message_handler(func=lambda m: m.text == "🎧 Наші роботи")
def handle_examples(message):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(
        "До прикладів 🎧",
        url=config.EXAMPLES_URL
    ))
    bot.send_message(
        message.chat.id,
        Messages.EXAMPLES_INFO.format(config.EXAMPLES_URL),
        reply_markup=markup
    )

@bot.message_handler(func=lambda m: m.text == "📢 Підписатися")
def handle_channel(message):
    bot.send_message(
        message.chat.id,
        Messages.CHANNEL_INFO.format(config.CHANNEL_URL)
    )

@bot.message_handler(func=lambda m: m.text == "📲 Контакти")
def handle_contacts(message):
    bot.send_message(
        message.chat.id,
        Messages.CONTACTS_INFO
    )

@bot.message_handler(func=lambda m: m.text == "ℹ️ Про студію")
def handle_about(message):
    bot.send_message(
        message.chat.id,
        Messages.ABOUT_INFO
    )

# === ADMIN PANEL HANDLERS ===

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text and m.text.startswith("💬 Активні діалоги"))
def handle_admin_active_dialogs(message):
    user_id = message.from_user.id
    dialogs = dialog_manager.get_active_dialogs()
    if not dialogs:
        bot.send_message(
            user_id,
            "Немає активних діалогів.",
            reply_markup=get_admin_main_keyboard(dialog_manager)
        )
        return
    text = "💬 Активні діалоги:\n\n"
    markup = types.InlineKeyboardMarkup()
    for dialog in dialogs:
        text += f"👤 {dialog['full_name']} (@{dialog['username']}) [{dialog['user_id']}]\n"
        text += f"📅 Почато: {time.strftime('%d.%m.%Y %H:%M', time.localtime(dialog['started_at']))} | 💬 Повідомлень: {dialog['message_count']}\n\n"
        markup.add(types.InlineKeyboardButton(
            text=f"💬 {dialog['full_name'][:20]}",
            callback_data=f"admin_enter_dialog_{dialog['user_id']}"
        ))
    bot.send_message(
        user_id,
        text,
        reply_markup=markup
    )

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text == "🆕 Новий діалог")
def handle_admin_new_dialog(message):
    user_id = message.from_user.id
    users = dialog_manager.get_all_users()
    free_users = [u for u in users if not u[5]]
    if not free_users:
        bot.send_message(
            user_id,
            "Всі користувачі вже у діалогах.",
            reply_markup=get_admin_main_keyboard(dialog_manager)
        )
        return
    text = "🆕 Виберіть користувача для нового діалогу:\n\n"
    markup = types.InlineKeyboardMarkup()
    for user in free_users[:15]:
        user_id_, username, full_name, total_msg, last_activity, _ = user
        text += f"👤 {full_name} (@{username}) | Повідомлень: {total_msg}\n"
        markup.add(types.InlineKeyboardButton(
            text=f"{full_name[:25]}",
            callback_data=f"admin_start_dialog_{user_id_}"
        ))
    bot.send_message(
        user_id,
        text,
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_enter_dialog_"))
def handle_admin_enter_dialog_call(call):
    admin_id = call.from_user.id
    user_id = int(call.data.split("_")[-1])
    if not dialog_manager.is_user_in_dialog(user_id):
        bot.answer_callback_query(call.id, "Діалог не активний")
        return
    dialog_manager.set_admin_current_dialog(admin_id, user_id)
    user_info = dialog_manager.get_user_info(user_id)
    bot.send_message(
        admin_id,
        f"💬 Діалог з {user_info.get('full_name', '')}\nПишіть повідомлення:",
        reply_markup=get_admin_dialog_keyboard()
    )
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_start_dialog_"))
def handle_admin_start_dialog_call(call):
    admin_id = call.from_user.id
    user_id = int(call.data.split("_")[-1])
    dialog_manager.start_dialog(user_id, admin_id)
    dialog_manager.set_admin_current_dialog(admin_id, user_id)
    user_info = dialog_manager.get_user_info(user_id)
    bot.send_message(
        admin_id,
        f"✅ Новий діалог з {user_info.get('full_name', '')} розпочато!\nПишіть повідомлення:",
        reply_markup=get_admin_dialog_keyboard()
    )
    bot.send_message(
        user_id,
        "💬 Адміністратор розпочав з вами діалог!\nПишіть повідомлення:",
        reply_markup=get_dialog_keyboard()
    )
    bot.answer_callback_query(call.id)

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and dialog_manager.get_user_state(m.from_user.id) == 'admin_in_dialog')
def handle_admin_dialog_message(message):
    admin_id = message.from_user.id
    dialog_user_id = dialog_manager.get_admin_current_dialog(admin_id)
    if not dialog_user_id:
        bot.send_message(
            admin_id,
            "Виберіть діалог для переписки.",
            reply_markup=get_admin_main_keyboard(dialog_manager)
        )
        return
    dialog_manager.save_message(dialog_user_id, message.text, is_admin=True)
    bot.send_message(
        dialog_user_id,
        f"👨‍💼 Адмін: {message.text}"
    )

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text == "📊 Статистика")
def handle_admin_statistics(message):
    user_id = message.from_user.id
    stats = dialog_manager.get_statistics()
    bot.send_message(
        user_id,
        f"📊 Статистика\n\n"
        f"Користувачів: {stats['total_users']}\n"
        f"Активних діалогів: {stats['active_dialogs']}\n"
        f"Всього повідомлень: {stats['total_messages']}\n"
        f"Всього діалогів: {stats['total_dialogs']}\n"
        f"Користувачів у діалозі: {stats['users_in_dialog']}\n"
        f"Uptime: {stats['uptime_seconds']//3600} год {((stats['uptime_seconds']//60)%60)} хв"
    )

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text.startswith("👥 Користувачі"))
def handle_admin_users_list(message):
    user_id = message.from_user.id
    users = dialog_manager.get_all_users()
    text = "👥 Список користувачів:\n\n"
    for user_id_, username, full_name, total_msg, last_activity, in_dialog in users[:20]:
        status = "🟢 В діалозі" if in_dialog else "⚪ Вільний"
        text += f"{full_name} (@{username}) | {status} | Повідомлень: {total_msg}\n"
    bot.send_message(
        user_id,
        text
    )

# === BROADCAST ===

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text == "📢 Розсилка")
def handle_admin_broadcast(message):
    dialog_manager.admin_broadcast_mode = True
    bot.send_message(
        message.chat.id,
        Messages.BROADCAST_PROMPT,
        reply_markup=get_cancel_keyboard()
    )

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and dialog_manager.admin_broadcast_mode)
def handle_broadcast_text(message):
    if message.text == "❌ Скасувати":
        dialog_manager.admin_broadcast_mode = False
        bot.send_message(
            message.chat.id,
            Messages.BROADCAST_CANCELLED,
            reply_markup=get_admin_main_keyboard(dialog_manager)
        )
        return
    broadcast_text = message.text
    users = dialog_manager.get_all_users()
    success_count = 0
    blocked_count = 0
    for user_id, username, full_name, _, _, _ in users:
        if user_id == config.ADMIN_ID:
            continue
        try:
            bot.send_message(
                user_id,
                f"📢 Повідомлення адміністратора:\n\n{broadcast_text}"
            )
            success_count += 1
        except Exception as e:
            blocked_count += 1
            logger.warning(f"Не вдалося надіслати {user_id}: {e}")
    dialog_manager.admin_broadcast_mode = False
    bot.send_message(
        message.chat.id,
        f"{Messages.BROADCAST_DONE}\n\n"
        f"✅ Надіслано: {success_count}\n"
        f"❌ Помилки: {blocked_count}\n"
        f"📋 Всього користувачів: {len(users)}",
        reply_markup=get_admin_main_keyboard(dialog_manager)
    )

# === CATCH ALL ===
@bot.message_handler(func=lambda m: True)
def handle_other_messages(message):
    user_id = message.from_user.id
    state = dialog_manager.get_user_state(user_id)
    if is_admin(user_id):
        bot.send_message(
            user_id,
            Messages.USE_MENU_BUTTONS,
            reply_markup=get_admin_main_keyboard(dialog_manager)
        )
    else:
        bot.send_message(
            user_id,
            Messages.USE_MENU_BUTTONS,
            reply_markup=get_main_keyboard()
        )

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

@app.route('/health')
def health():
    try:
        bot_info = bot.get_me()
        return jsonify({
            "status": "healthy",
            "timestamp": time.time(),
            "uptime_seconds": int(time.time() - bot_start_time),
            "bot_username": bot_info.username,
            "total_users": len(dialog_manager.users),
            "version": "3.0-enhanced"
        }), 200
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return jsonify({
            "status": "error",
            "error": str(e),
            "timestamp": time.time()
        }), 500

@app.route('/status')
def status():
    stats = dialog_manager.get_statistics()
    return jsonify({
        "bot_status": "running",
        "uptime_seconds": stats['uptime_seconds'],
        "total_users": stats['total_users'],
        "active_chats": stats['active_dialogs'],
        "admin_id": config.ADMIN_ID,
        "timestamp": time.time()
    })

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

# === MAIN EXECUTION ===
if __name__ == "__main__":
    try:
        logger.info("Starting Kuznya Music Studio Bot...")
        flask_thread = Thread(target=run_flask, daemon=True)
        flask_thread.start()
        logger.info(f"Flask server started on port {config.WEBHOOK_PORT}")

        logger.info("Health check endpoints available:")
        logger.info(f"  - Main: http://localhost:{config.WEBHOOK_PORT}/")
        logger.info(f"  - Health: http://localhost:{config.WEBHOOK_PORT}/health")
        logger.info(f"  - Status: http://localhost:{config.WEBHOOK_PORT}/status")

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

