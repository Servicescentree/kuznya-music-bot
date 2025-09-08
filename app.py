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
    SHARE_BOT = "🎉 Запроси друга у музичний бот!\nПросто поділись цим посиланням:\n{}\n\nЗа кожного друга — бонус чи знижка!\nЯкщо запросиш 3 друзів — отримаєш промокод на знижку 25% на запис!"
    BONUS_PROMO = "🎁 Ваш промокод на знижку 25%: {}\nПокажіть цей код адміністратору при записі!"
    NO_PROMO = "У вас ще немає промокоду. Запросіть 3 друзів та отримайте знижку!"
    FRIEND_JOINED = "🎉 Ваш друг {} приєднався за вашим реферальним посиланням! Дякуємо!"
    PROMO_ACHIEVED = "🎉 Вітаємо! Ви запросили 3 друзів і отримали промокод на знижку 25% — {}\nПокажіть цей код адміністратору при записі."

# === ENHANCED DIALOG MANAGER + REFERRALS ===
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
        self.referrals = {}  # referrer_id -> set(new_user_ids)
        self.promo_codes = {}  # user_id -> promo_code
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

    # --- Referral & Promocode ---
    def add_referral(self, referrer_id, new_user_id):
        if referrer_id == new_user_id:
            return None
        self.referrals.setdefault(referrer_id, set()).add(new_user_id)
        # Generate promo code if 3 unique invited
        if len(self.referrals[referrer_id]) == 3 and referrer_id not in self.promo_codes:
            code = self.generate_promo_code()
            self.promo_codes[referrer_id] = code
            return code
        return None

    def generate_promo_code(self, length=8):
        return 'KUZNYA25-' + ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

    def get_promo_code(self, user_id):
        return self.promo_codes.get(user_id)

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
    markup.add(
        types.KeyboardButton("ℹ️ Про студію"),
        types.KeyboardButton("🔗 Поділитись ботом")
    )
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

# === REFERRAL HANDLERS ===

@bot.message_handler(func=lambda m: m.text == "🔗 Поділитись ботом")
def handle_share_bot(message):
    user_id = message.from_user.id
    referral_link = f"https://t.me/{bot.get_me().username}?start=ref{user_id}"
    text = Messages.SHARE_BOT.format(referral_link)
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Поділитись ботом", url=referral_link))
    bot.send_message(
        user_id,
        text,
        reply_markup=markup
    )

@bot.message_handler(commands=['promocode'])
def handle_promocode(message):
    user_id = message.from_user.id
    code = dialog_manager.get_promo_code(user_id)
    if code:
        bot.send_message(
            user_id,
            Messages.BONUS_PROMO.format(code)
        )
    else:
        bot.send_message(
            user_id,
            Messages.NO_PROMO
        )

# === START HANDLER (з рефералами) ===
@bot.message_handler(commands=['start'])
def handle_start(message):
    user_info = get_user_info(message.from_user)
    args = message.text.split(' ', 1)
    # Referral logic
    if len(args) > 1 and args[1].startswith('ref'):
        referrer_id = int(args[1][3:])
        if referrer_id != user_info['id']:
            dialog_manager.save_user(user_info['id'], user_info['username'], user_info['full_name'])
            promo = dialog_manager.add_referral(referrer_id, user_info['id'])
            if promo:
                bot.send_message(
                    referrer_id,
                    Messages.PROMO_ACHIEVED.format(promo)
                )
            bot.send_message(
                referrer_id,
                Messages.FRIEND_JOINED.format(user_info['full_name'])
            )
    # Далі стандартна логіка старту
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

# === MAIN EXECUTION ===
if __name__ == "__main__":
    try:
        logger.info("Starting Kuznya Music Studio Bot...")
        flask_thread = Thread(target=lambda: Flask(__name__).run(
            host='0.0.0.0',
            port=config.WEBHOOK_PORT,
            debug=False,
            threaded=True
        ), daemon=True)
        flask_thread.start()
        logger.info(f"Flask server started on port {config.WEBHOOK_PORT}")
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
