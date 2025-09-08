import os
import time
import html
import logging
import random
import string
from threading import Thread
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

config = BotConfig()

# === TEXTS ===
class Messages:
    WELCOME = """Привіт, <b>{}</b>! 👋
Ласкаво просимо до музичної студії Kuznya Music!
Оберіть дію з меню:"""
    EXAMPLES_INFO = """🎵 <b>Наші роботи:</b>\n\nПослухати приклади можна тут:\n<a href="{}">{}</a>"""
    CHANNEL_INFO = """📢 <b>Підписуйтесь на наш канал:</b>\n<a href="{}">{}</a>"""
    CONTACTS_INFO = """📲 <b>Контакти студії:</b>\nTelegram: <a href="https://t.me/kuznya_music">@kuznya_music</a>"""
    ABOUT_INFO = """ℹ️ <b>Про студію</b>\n\nKuznya Music — сучасна музична студія для запису, зведення, майстерингу, аранжування та творчих експериментів."""
    DIALOG_STARTED = "<b>✅ Діалог розпочато!</b> Пишіть повідомлення адміністратору."
    DIALOG_ENDED_USER = "<b>✅ Діалог завершено.</b> Дякуємо за спілкування!"
    DIALOG_ENDED_ADMIN = "<b>✅ Діалог завершено адміністратором.</b> Ви можете почати новий діалог!"
    ADMIN_PANEL = "👨‍💼 <b>Адмін-панель</b>\n\nОберіть дію:"
    ERROR_SEND_FAILED = "<b>❌ Помилка при відправці повідомлення.</b> Спробуйте пізніше."
    USE_MENU_BUTTONS = "<b>🤔 Використовуйте кнопки меню для навігації</b>"
    BROADCAST_PROMPT = "<b>📢 Введіть текст для розсилки всім користувачам або натисніть '❌ Скасувати'</b>"
    BROADCAST_DONE = "<b>📊 Розсилка завершена!</b>"
    BROADCAST_CANCELLED = "<b>❌ Розсилка скасована.</b>"
    SHARE_BOT = """🎉 Запроси друга у музичний бот!\nПросто поділись цим посиланням:\n<a href="{}">{}</a>\n\nЗа кожного друга — бонус чи знижка! Якщо запросиш 3 друзів — отримаєш промокод на знижку 25% на запис!"""
    BONUS_PROMO = "<b>🎁 Ваш промокод на знижку 25%:</b> <code>{}</code>\nПокажіть цей код адміністратору при записі!"
    NO_PROMO = "У вас ще немає промокоду. Запросіть 3 друзів та отримайте знижку!"
    FRIEND_JOINED = "🎉 Ваш друг <b>{}</b> приєднався за вашим реферальним посиланням! Дякуємо!"
    PROMO_ACHIEVED = "🎉 Вітаємо! Ви запросили 3 друзів і отримали промокод на знижку 25% — <code>{}</code>\nПокажіть цей код адміністратору при записі."

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

dialog_manager = EnhancedDialogManager()

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
        types.KeyboardButton("👥 Користувачі")
    )
    markup.add(types.KeyboardButton("📊 Статистика"))
    markup.add(types.KeyboardButton("📢 Розсилка"))
    return markup

def get_cancel_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    markup.add(types.KeyboardButton("❌ Скасувати"))
    return markup

def get_admin_dialog_keyboard(user_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton("❌ Завершити діалог"),
        types.KeyboardButton("🔄 Інший діалог")
    )
    markup.add(types.KeyboardButton("🏠 Головне меню"))
    return markup

# === LOGGING ===
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

bot = telebot.TeleBot(config.TOKEN, parse_mode="HTML")

def is_admin(user_id): return user_id == config.ADMIN_ID

def get_user_info(user):
    return {
        'id': user.id,
        'username': user.username or "",
        'first_name': user.first_name or "",
        'last_name': user.last_name or "",
        'full_name': f"{user.first_name or ''} {user.last_name or ''}".strip()
    }

def sanitize_input(text): return html.escape(str(text).strip())

# === USER HANDLERS ===

@bot.message_handler(func=lambda m: m.text == "💬 Почати діалог")
def handle_dialog_start(message):
    user_id = message.from_user.id
    if dialog_manager.is_user_in_dialog(user_id):
        bot.send_message(user_id, "Ви вже у діалозі!", reply_markup=get_dialog_keyboard())
        return
    dialog_manager.start_dialog(user_id, config.ADMIN_ID)
    bot.send_message(user_id, Messages.DIALOG_STARTED, reply_markup=get_dialog_keyboard())
    bot.send_message(config.ADMIN_ID, f"🔔 Новий діалог з користувачем <b>{sanitize_input(message.from_user.full_name)}</b> (id: {user_id})", reply_markup=get_admin_dialog_keyboard(user_id))

@bot.message_handler(func=lambda m: m.text == "🎧 Наші роботи")
def handle_examples(message):
    url = html.escape(config.EXAMPLES_URL)
    bot.send_message(message.from_user.id, Messages.EXAMPLES_INFO.format(url, url), parse_mode="HTML")

@bot.message_handler(func=lambda m: m.text == "📢 Підписатися")
def handle_channel(message):
    url = html.escape(config.CHANNEL_URL)
    bot.send_message(message.from_user.id, Messages.CHANNEL_INFO.format(url, url), parse_mode="HTML")

@bot.message_handler(func=lambda m: m.text == "📲 Контакти")
def handle_contacts(message):
    bot.send_message(message.from_user.id, Messages.CONTACTS_INFO, parse_mode="HTML")

@bot.message_handler(func=lambda m: m.text == "ℹ️ Про студію")
def handle_about(message):
    bot.send_message(message.from_user.id, Messages.ABOUT_INFO, parse_mode="HTML")

@bot.message_handler(func=lambda m: m.text == "❌ Завершити діалог")
def handle_dialog_end(message):
    user_id = message.from_user.id
    if dialog_manager.is_user_in_dialog(user_id):
        dialog_manager.end_dialog(user_id)
        bot.send_message(user_id, Messages.DIALOG_ENDED_USER, reply_markup=get_main_keyboard())
        bot.send_message(config.ADMIN_ID, f"❌ Діалог з {user_id} завершено.", reply_markup=get_admin_main_keyboard(dialog_manager))
    else:
        bot.send_message(user_id, "У вас немає активного діалогу.", reply_markup=get_main_keyboard())

@bot.message_handler(func=lambda m: m.text == "🔗 Поділитись ботом")
def handle_share_bot(message):
    user_id = message.from_user.id
    bot_username = bot.get_me().username
    referral_link = f"https://t.me/{bot_username}?start=ref{user_id}"
    safe_link = html.escape(referral_link)
    text = Messages.SHARE_BOT.format(safe_link, safe_link)
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
            Messages.BONUS_PROMO.format(html.escape(code)),
            parse_mode="HTML"
        )
    else:
        bot.send_message(
            user_id,
            Messages.NO_PROMO,
            parse_mode="HTML"
        )

# === ADMIN HANDLERS ===

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text == "🏠 Головне меню")
def handle_admin_home(message):
    stats = dialog_manager.get_statistics()
    bot.send_message(
        config.ADMIN_ID,
        f"{Messages.ADMIN_PANEL}\n\nАктивних діалогів: {stats['active_dialogs']}\nКористувачів: {stats['total_users']}\nПовідомлень: {stats['total_messages']}",
        reply_markup=get_admin_main_keyboard(dialog_manager),
        parse_mode="HTML"
    )

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text.startswith("💬 Активні діалоги"))
def admin_active_dialogs(message):
    dialogs = dialog_manager.get_active_dialogs()
    if not dialogs:
        bot.send_message(config.ADMIN_ID, "Немає активних діалогів.", reply_markup=get_admin_main_keyboard(dialog_manager))
        return
    msg = "<b>Активні діалоги:</b>\n"
    for d in dialogs:
        msg += f"- {sanitize_input(d['full_name'])} (id: {d['user_id']})\n"
    bot.send_message(config.ADMIN_ID, msg, reply_markup=get_admin_main_keyboard(dialog_manager), parse_mode="HTML")

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text == "👥 Користувачі")
def admin_users(message):
    users = dialog_manager.get_all_users()
    msg = "<b>Користувачі бота:</b>\n"
    for u in users:
        msg += f"- {sanitize_input(u[2])} (id: {u[0]})\n"
    bot.send_message(config.ADMIN_ID, msg, reply_markup=get_admin_main_keyboard(dialog_manager), parse_mode="HTML")

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text == "📊 Статистика")
def admin_stats(message):
    stats = dialog_manager.get_statistics()
    msg = f"<b>Статистика бота:</b>\nКористувачів: {stats['total_users']}\nДіалогів: {stats['total_dialogs']}\nПовідомлень: {stats['total_messages']}\nАптайм: {stats['uptime_seconds']//3600} год"
    bot.send_message(config.ADMIN_ID, msg, reply_markup=get_admin_main_keyboard(dialog_manager), parse_mode="HTML")

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text == "📢 Розсилка")
def admin_broadcast(message):
    dialog_manager.admin_broadcast_mode = True
    bot.send_message(config.ADMIN_ID, Messages.BROADCAST_PROMPT, reply_markup=get_cancel_keyboard(), parse_mode="HTML")

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and dialog_manager.admin_broadcast_mode and m.text == "❌ Скасувати")
def admin_broadcast_cancel(message):
    dialog_manager.admin_broadcast_mode = False
    bot.send_message(config.ADMIN_ID, Messages.BROADCAST_CANCELLED, reply_markup=get_admin_main_keyboard(dialog_manager))

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and dialog_manager.admin_broadcast_mode)
def admin_broadcast_send(message):
    text = sanitize_input(message.text)
    for user_id in dialog_manager.users:
        if user_id != config.ADMIN_ID:
            try:
                bot.send_message(user_id, f"📢 <b>Оголошення від студії Kuznya Music:</b>\n\n{text}", parse_mode="HTML")
            except Exception: pass
    dialog_manager.admin_broadcast_mode = False
    bot.send_message(config.ADMIN_ID, Messages.BROADCAST_DONE, reply_markup=get_admin_main_keyboard(dialog_manager))

# === START HANDLER (з рефералами) ===
@bot.message_handler(commands=['start'])
def handle_start(message):
    user_info = get_user_info(message.from_user)
    args = message.text.split(' ', 1)
    if len(args) > 1 and args[1].startswith('ref'):
        referrer_id = int(args[1][3:])
        if referrer_id != user_info['id']:
            dialog_manager.save_user(user_info['id'], user_info['username'], user_info['full_name'])
            promo = dialog_manager.add_referral(referrer_id, user_info['id'])
            user_name = html.escape(user_info['full_name'])
            if promo:
                bot.send_message(
                    referrer_id,
                    Messages.PROMO_ACHIEVED.format(html.escape(promo)),
                    parse_mode="HTML"
                )
            bot.send_message(
                referrer_id,
                Messages.FRIEND_JOINED.format(user_name),
                parse_mode="HTML"
            )
    dialog_manager.save_user(user_info['id'], user_info['username'], user_info['full_name'])
    user_first_name_html = html.escape(user_info['first_name'])
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
                Messages.WELCOME.format(user_first_name_html),
                reply_markup=markup,
                parse_mode="HTML"
            )

# === ROUTING ДІАЛОГУ ===
@bot.message_handler(func=lambda m: dialog_manager.is_user_in_dialog(m.from_user.id) and not is_admin(m.from_user.id))
def user_dialog_message(message):
    user_id = message.from_user.id
    dialog_manager.save_message(user_id, message.text, is_admin=False)
    try:
        bot.send_message(config.ADMIN_ID, f"👤 <b>Користувач {sanitize_input(message.from_user.full_name)}:</b>\n{sanitize_input(message.text)}", reply_markup=get_admin_dialog_keyboard(user_id), parse_mode="HTML")
        bot.send_message(user_id, "✅ Повідомлення надіслано адміністратору.")
    except Exception:
        bot.send_message(user_id, Messages.ERROR_SEND_FAILED)

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and dialog_manager.get_admin_current_dialog(config.ADMIN_ID))
def admin_dialog_message(message):
    user_id = dialog_manager.get_admin_current_dialog(config.ADMIN_ID)
    dialog_manager.save_message(user_id, message.text, is_admin=True)
    try:
        bot.send_message(user_id, f"👨‍💼 <b>Адміністратор:</b>\n{sanitize_input(message.text)}")
        bot.send_message(config.ADMIN_ID, "✅ Надіслано користувачу.", reply_markup=get_admin_dialog_keyboard(user_id))
    except Exception:
        bot.send_message(config.ADMIN_ID, Messages.ERROR_SEND_FAILED)

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text and m.text.startswith("🔄 Інший діалог"))
def admin_switch_dialog(message):
    dialogs = dialog_manager.get_active_dialogs()
    for d in dialogs:
        if d['user_id'] != dialog_manager.get_admin_current_dialog(config.ADMIN_ID):
            dialog_manager.set_admin_current_dialog(config.ADMIN_ID, d['user_id'])
            bot.send_message(config.ADMIN_ID, f"🔄 Переключено на діалог з {sanitize_input(d['full_name'])}.", reply_markup=get_admin_dialog_keyboard(d['user_id']))
            return
    bot.send_message(config.ADMIN_ID, "Немає інших активних діалогів.", reply_markup=get_admin_main_keyboard(dialog_manager))

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text and m.text == "❌ Завершити діалог")
def admin_end_dialog(message):
    user_id = dialog_manager.get_admin_current_dialog(config.ADMIN_ID)
    if user_id:
        dialog_manager.end_dialog(user_id)
        bot.send_message(config.ADMIN_ID, "✅ Діалог завершено.", reply_markup=get_admin_main_keyboard(dialog_manager))
        bot.send_message(user_id, Messages.DIALOG_ENDED_ADMIN, reply_markup=get_main_keyboard())
    else:
        bot.send_message(config.ADMIN_ID, "Немає вибраного діалогу.", reply_markup=get_admin_main_keyboard(dialog_manager))

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text and m.text == "🆕 Новий діалог")
def admin_new_dialog(message):
    dialogs = dialog_manager.get_active_dialogs()
    if dialogs:
        user_id = dialogs[0]['user_id']
        dialog_manager.set_admin_current_dialog(config.ADMIN_ID, user_id)
        bot.send_message(config.ADMIN_ID, f"Вибрано діалог з {sanitize_input(dialogs[0]['full_name'])}.", reply_markup=get_admin_dialog_keyboard(user_id))
    else:
        bot.send_message(config.ADMIN_ID, "Немає активних діалогів.", reply_markup=get_admin_main_keyboard(dialog_manager))

# === HEALTHCHECK with Flask ===
health_app = Flask(__name__)

@health_app.route("/ping")
def ping():
    return jsonify({"status": "ok", "time": int(time.time())})

def run_health_server():
    health_app.run(host='0.0.0.0', port=config.WEBHOOK_PORT, debug=False, threaded=True)

# === AUTOPING (KEEPALIVE) ===
def background_ping_bot():
    while True:
        try:
            bot.get_me()
            logging.info("Bot keepalive ping sent to Telegram")
        except Exception as e:
            logging.error(f"Ping error: {e}")
        time.sleep(300)  # кожні 5 хвилин

# === MAIN EXECUTION ===
if __name__ == "__main__":
    Thread(target=run_health_server, daemon=True).start()
    Thread(target=background_ping_bot, daemon=True).start()
    time.sleep(2)
    bot.polling(none_stop=True, interval=2, timeout=30)
