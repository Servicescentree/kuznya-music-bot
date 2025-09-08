import os
import time
import html
import logging
from threading import Thread
from dataclasses import dataclass
from typing import Dict, Any

import telebot
from telebot import types
from flask import Flask, jsonify, request

import requests  # for self-ping
import redis     # upstash redis

# -------- REDIS SETUP --------
REDIS_URL = os.getenv("UPSTASH_REDIS_REST_URL")
if not REDIS_URL or not REDIS_URL.startswith("redis"):
    raise ValueError(f"UPSTASH_REDIS_REST_URL is not set or invalid! Got: {REDIS_URL}")
r = redis.from_url(REDIS_URL, decode_responses=True)

# -------- CONFIG --------
@dataclass
class BotConfig:
    TOKEN: str = os.getenv('BOT_TOKEN', '')
    ADMIN_ID: int = int(os.getenv('ADMIN_ID', '0'))
    CHANNEL_URL: str = 'https://t.me/kuznya_music'
    EXAMPLES_URL: str = 'https://t.me/kuznya_music/41'
    WEBHOOK_PORT: int = int(os.getenv('PORT', 8080))
    MAX_MESSAGE_LENGTH: int = 4000
    RATE_LIMIT_MESSAGES: int = 5  # messages per minute
    WEBHOOK_URL: str = os.getenv('WEBHOOK_URL', '')  # e.g. https://your-app.onrender.com

# -------- TEXTS --------
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

Послухати приклади можна тут:
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
    ERROR_SEND_FAILED = "❌ Помилка при відправці повідомлення. Спробуйте пізніше."
    ERROR_MESSAGE_TOO_LONG = f"❌ Повідомлення занадто довге. Максимум {BotConfig.MAX_MESSAGE_LENGTH} символів."
    ERROR_RATE_LIMITED = "❌ Забагато повідомлень. Зачекайте хвилинку."
    ERROR_INVALID_INPUT = "❌ Некоректне повідомлення. Спробуйте ще раз."

# -------- STATES --------
class UserStates:
    IDLE = 'idle'
    WAITING_FOR_MESSAGE = 'waiting_for_message'
    ADMIN_REPLYING = 'admin_replying'

# -------- LOGGING --------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# -------- SETUP --------
config = BotConfig()
if not config.TOKEN or not config.TOKEN.startswith(""):
    raise ValueError("BOT_TOKEN is not set!")
if not config.ADMIN_ID:
    raise ValueError("ADMIN_ID is not set!")
if not config.WEBHOOK_URL:
    raise ValueError("WEBHOOK_URL is not set!")

bot = telebot.TeleBot(config.TOKEN)
try:
    bot_info = bot.get_me()
    logger.info(f"Bot token is valid! Bot name: {bot_info.first_name} (@{bot_info.username})")
except Exception as token_error:
    logger.error(f"Invalid bot token: {token_error}")
    exit(1)

# -------- UTILS --------
def is_admin(user_id: int) -> bool:
    return int(user_id) == int(config.ADMIN_ID)

def get_user_info(user) -> Dict[str, Any]:
    return {
        'id': user.id,
        'username': user.username or "Без username",
        'first_name': user.first_name or "Невідомо",
        'last_name': user.last_name or "",
        'full_name': f"{user.first_name or ''} {user.last_name or ''}".strip()
    }

def get_main_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton("🎤 Записати трек"),
        types.KeyboardButton("🎧 Приклади робіт")
    )
    markup.add(
        types.KeyboardButton("📢 Підписатися"),
        types.KeyboardButton("📲 Контакти")
    )
    return markup

def get_chat_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    markup.add(types.KeyboardButton("❌ Завершити діалог"))
    return markup

def get_admin_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton("📬 Активні діалоги"),
        types.KeyboardButton("👥 Користувачі")
    )
    markup.add(
        types.KeyboardButton("📊 Статистика"),
        types.KeyboardButton("📢 Розсилка")
    )
    return markup

def validate_message(message) -> tuple[bool, str]:
    if not message or not message.text:
        return False, Messages.ERROR_INVALID_INPUT
    if len(message.text) > config.MAX_MESSAGE_LENGTH:
        return False, Messages.ERROR_MESSAGE_TOO_LONG
    if not check_rate_limit(message.from_user.id):
        return False, Messages.ERROR_RATE_LIMITED
    return True, ""

def check_rate_limit(user_id: int) -> bool:
    key = f"rate:{user_id}"
    pipe = r.pipeline()
    pipe.incr(key)
    pipe.expire(key, 60)
    count, _ = pipe.execute()
    return count <= config.RATE_LIMIT_MESSAGES

def sanitize_input(text: str) -> str:
    return html.escape(text.strip())

def set_user_state(user_id: int, state: str):
    r.set(f"user:{user_id}:state", state)

def get_user_state(user_id: int) -> str:
    return r.get(f"user:{user_id}:state") or UserStates.IDLE

def get_all_user_ids():
    ids = []
    for key in r.scan_iter("user:*:state"):
        uid = key.split(":")[1]
        if uid not in ids:
            ids.append(int(uid))
    return ids

def add_user(user_id: int):
    set_user_state(user_id, UserStates.IDLE)

def set_admin_reply_target(admin_id: int, user_id: int):
    r.set(f"admin:{admin_id}:reply", user_id)

def get_admin_reply_target(admin_id: int) -> int:
    uid = r.get(f"admin:{admin_id}:reply")
    return int(uid) if uid else None

def clear_admin_reply_target(admin_id: int):
    r.delete(f"admin:{admin_id}:reply")

# -------- HANDLERS --------

@bot.message_handler(commands=['start'])
def handle_start(message):
    user_info = get_user_info(message.from_user)
    if is_admin(message.from_user.id):
        markup = get_admin_keyboard()
        bot.send_message(
            message.chat.id,
            "👨‍💼 Ви у панелі адміністратора. Оберіть дію:",
            reply_markup=markup
        )
        return
    else:
        markup = get_main_keyboard()
        add_user(message.from_user.id)
        bot.send_message(
            message.chat.id,
            Messages.WELCOME.format(user_info['first_name']),
            reply_markup=markup
        )
        return

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text == "📢 Розсилка")
def handle_admin_broadcast(message):
    bot.send_message(message.chat.id, "✍️ Відправте текст розсилки. Всі користувачі отримають це повідомлення.")

    def broadcast_handler(msg):
        txt = msg.text
        count = 0
        for uid in get_all_user_ids():
            if uid != config.ADMIN_ID:
                try:
                    bot.send_message(uid, f"📢 [Розсилка]\n\n{txt}")
                    count += 1
                except Exception:
                    pass
        bot.send_message(config.ADMIN_ID, f"✅ Розсилку відправлено {count} користувачам.")

    bot.register_next_step_handler(message, broadcast_handler)
    return

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text == "📊 Статистика")
def handle_show_stats(message):
    all_users = get_all_user_ids()
    active_users = [uid for uid in all_users if get_user_state(uid) == UserStates.WAITING_FOR_MESSAGE]
    total_users = len(all_users)
    recent_users = 0
    now = time.time()
    for uid in all_users:
        key = f"rate:{uid}"
        if r.ttl(key) > 0:
            recent_users += 1
    stats_text = f"""📊 *Детальна статистика*

👥 Всього користувачів: {total_users}
💬 Активних чатів: {len(active_users)}
⏰ Активних за годину: {recent_users}
📅 Дата: {time.strftime('%d.%m.%Y %H:%M')}

🔧 Технічна інформація:
• Зберігання: Upstash Redis
• Логування: активне
• Рейт-лімітинг: {config.RATE_LIMIT_MESSAGES} повідомлень/хвилину"""
    bot.send_message(
        message.chat.id,
        stats_text,
        parse_mode='Markdown'
    )
    return

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text == "📬 Активні діалоги")
def handle_admin_active_dialogs(message):
    users = [uid for uid in get_all_user_ids() if get_user_state(uid) == UserStates.WAITING_FOR_MESSAGE]
    txt = "📬 Активні діалоги:\n\n"
    for uid in users:
        txt += f"• ID: <code>{uid}</code>\n"
    if not users:
        txt += "Немає активних діалогів."
    bot.send_message(message.chat.id, txt, parse_mode="HTML")
    return

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text == "👥 Користувачі")
def handle_admin_users(message):
    users = [uid for uid in get_all_user_ids() if uid != config.ADMIN_ID]
    txt = "👥 Список користувачів:\n\n"
    for uid in users:
        txt += f"• ID: <code>{uid}</code>\n"
    if not users:
        txt += "Немає користувачів."
    bot.send_message(message.chat.id, txt, parse_mode="HTML")
    return

@bot.message_handler(func=lambda message: not is_admin(message.from_user.id) and message.text == "🎤 Записати трек")
def handle_start_recording(message):
    user_id = message.from_user.id
    set_user_state(user_id, UserStates.WAITING_FOR_MESSAGE)
    markup = get_chat_keyboard()
    bot.send_message(
        message.chat.id,
        Messages.RECORDING_PROMPT,
        parse_mode='Markdown',
        reply_markup=markup
    )
    return

@bot.message_handler(func=lambda message: not is_admin(message.from_user.id) and message.text == "🎧 Приклади робіт")
def handle_show_examples(message):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(
        "До прикладів 🎧",
        url=config.EXAMPLES_URL
    ))
    bot.send_message(
        message.chat.id,
        "🎵 Наші роботи:\n\nПриклади: Аранжування 🎹 | Зведення 🎧 | Мастерингу 🔊",
        reply_markup=markup
    )
    return

@bot.message_handler(func=lambda message: not is_admin(message.from_user.id) and message.text == "📢 Підписатися")
def handle_show_channel(message):
    bot.send_message(
        message.chat.id,
        Messages.CHANNEL_INFO.format(config.CHANNEL_URL),
        disable_web_page_preview=False
    )
    return

@bot.message_handler(func=lambda message: not is_admin(message.from_user.id) and message.text == "📲 Контакти")
def handle_show_contacts(message):
    bot.send_message(
        message.chat.id,
        Messages.CONTACTS_INFO
    )
    return

@bot.message_handler(func=lambda message: not is_admin(message.from_user.id) and message.text == "❌ Завершити діалог")
def handle_end_dialog(message):
    user_id = message.from_user.id
    set_user_state(user_id, UserStates.IDLE)
    markup = get_main_keyboard()
    bot.send_message(
        message.chat.id,
        Messages.DIALOG_ENDED,
        reply_markup=markup
    )
    return

@bot.message_handler(func=lambda message: get_user_state(message.from_user.id) == UserStates.WAITING_FOR_MESSAGE)
def handle_user_message(message):
    is_valid, error_msg = validate_message(message)
    if not is_valid:
        bot.send_message(message.chat.id, error_msg)
        return
    user_info = get_user_info(message.from_user)
    sanitized_text = sanitize_input(message.text)
    admin_text = f"""💬 *Нове повідомлення від клієнта*

👤 *Клієнт:* {user_info['full_name']} (@{user_info['username']})
🆔 *ID:* `{user_info['id']}`
⏰ *Час:* {time.strftime('%H:%M %d.%m.%Y')}

📝 *Повідомлення:*
{sanitized_text}"""
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(
        "✍️ Відповісти",
        callback_data=f"reply_{user_info['id']}"
    ))
    # Надсилаємо адміну текст з кнопкою
    bot.send_message(
        config.ADMIN_ID,
        admin_text,
        parse_mode='Markdown',
        reply_markup=markup
    )
    # Надсилаємо адміну forward для reply-режиму
    bot.forward_message(config.ADMIN_ID, message.chat.id, message.message_id)
    # Підтвердження юзеру
    bot.send_message(message.chat.id, Messages.MESSAGE_SENT)
    return

@bot.callback_query_handler(func=lambda call: call.data.startswith('reply_'))
def handle_admin_reply_callback(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ Немає доступу")
        return
    user_id = int(call.data.split('_')[1])
    set_admin_reply_target(config.ADMIN_ID, user_id)
    set_user_state(config.ADMIN_ID, f"{UserStates.ADMIN_REPLYING}_{user_id}")
    bot.answer_callback_query(call.id, "Напишіть відповідь наступним повідомленням")
    bot.send_message(
        config.ADMIN_ID,
        f"✍️ Напишіть відповідь клієнту (ID: {user_id}):\n\n"
        "_Наступне повідомлення буде відправлено клієнту_"
    )
    return

@bot.message_handler(func=lambda message: is_admin(message.from_user.id))
def handle_admin_reply_or_panel(message):
    admin_id = message.from_user.id

    # 1. Якщо reply на forward-повідомлення (адмін просто відповідає у Telegram)
    if message.reply_to_message and message.reply_to_message.forward_from:
        user_id = message.reply_to_message.forward_from.id
        sanitized_reply = sanitize_input(message.text)
        bot.send_message(
            user_id,
            Messages.ADMIN_REPLY.format(sanitized_reply),
            parse_mode='Markdown'
        )
        bot.send_message(
            admin_id,
            f"✅ Відповідь відправлено клієнту (ID: {user_id})",
            reply_to_message_id=message.message_id
        )
        return

    # 2. Якщо адмін у callback-режимі (натиснув "Відповісти")
    state = get_user_state(admin_id)
    if state and state.startswith(UserStates.ADMIN_REPLYING):
        target_user_id = get_admin_reply_target(admin_id)
        if not target_user_id:
            bot.send_message(admin_id, "❌ Помилка: не знайдено користувача для відповіді")
            return
        sanitized_reply = sanitize_input(message.text)
        bot.send_message(
            target_user_id,
            Messages.ADMIN_REPLY.format(sanitized_reply),
            parse_mode='Markdown'
        )
        bot.send_message(
            admin_id,
            f"✅ Відповідь відправлено клієнту (ID: {target_user_id})",
            reply_to_message_id=message.message_id
        )
        set_user_state(admin_id, UserStates.IDLE)
        clear_admin_reply_target(admin_id)
        return

    # 3. Якщо інше — показуємо адмінське меню
    markup = get_admin_keyboard()
    bot.send_message(
        admin_id,
        Messages.USE_MENU_BUTTONS,
        reply_markup=markup
    )
    return

# -------- КІНЕЦЬ: CATCH-ALL HANDLER --------
@bot.message_handler(func=lambda message: True)
def handle_other_messages(message):
    if is_admin(message.from_user.id):
        markup = get_admin_keyboard()
        bot.send_message(
            message.chat.id,
            Messages.USE_MENU_BUTTONS,
            reply_markup=markup
        )
    else:
        markup = get_main_keyboard()
        bot.send_message(
            message.chat.id,
            Messages.USE_MENU_BUTTONS,
            reply_markup=markup
        )

# -------- FLASK & SELF-PING --------
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
    <p><strong>Користувачів:</strong> {len(get_all_user_ids())}</p>
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
            "total_users": len(get_all_user_ids()),
            "version": "3.0-admin-panel-redis"
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
        active_users = [uid for uid in get_all_user_ids() if get_user_state(uid) == UserStates.WAITING_FOR_MESSAGE]
        return jsonify({
            "bot_status": "running",
            "uptime_seconds": int(time.time() - bot_start_time),
            "total_users": len(get_all_user_ids()),
            "active_chats": len(active_users),
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

# --- WEBHOOK ENDPOINT ---
@app.route(f"/bot{config.TOKEN}", methods=["POST"])
def webhook():
    if request.headers.get("content-type") == "application/json":
        json_string = request.get_data().decode("utf-8")
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return "", 200
    else:
        return "", 403

def run_flask():
    app.run(
        host='0.0.0.0', 
        port=config.WEBHOOK_PORT, 
        debug=False,
        threaded=True
    )

def self_ping():
    url = f"{config.WEBHOOK_URL}/keepalive"
    while True:
        try:
            r2 = requests.get(url, timeout=10)
            print(f"[SELF-PING] Pinged {url} ({r2.status_code})")
        except Exception as e:
            print(f"[SELF-PING] Error pinging {url}: {e}")
        time.sleep(300)  # 5 хвилин

if __name__ == "__main__":
    try:
        logger.info("Starting Kuznya Music Studio Bot...")
        bot.remove_webhook()
        time.sleep(1)
        set_url = f"{config.WEBHOOK_URL}/bot{config.TOKEN}"
        webhook_result = bot.set_webhook(url=set_url)
        if webhook_result:
            logger.info(f"Webhook set: {set_url}")
        else:
            logger.warning("Webhook not set!")
        flask_thread = Thread(target=run_flask, daemon=True)
        flask_thread.start()
        selfping_thread = Thread(target=self_ping, daemon=True)
        selfping_thread.start()
        logger.info("🎵 Music Studio Bot started successfully!")
        logger.info(f"Admin ID: {config.ADMIN_ID}")
        logger.info("Bot is running via webhook. No polling!")
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.critical(f"Critical error: {e}")
        exit(1)
