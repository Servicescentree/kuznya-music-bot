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

import requests
import redis

# -------- REDIS SETUP --------
REDIS_URL = os.getenv("UPSTASH_REDIS_REST_URL")
if not REDIS_URL or not REDIS_URL.startswith("redis"):
    raise ValueError(f"UPSTASH_REDIS_REST_URL is not set or invalid! Got: {REDIS_URL}")
r = redis.from_url(REDIS_URL, decode_responses=True)

# -------- CONFIG --------
@dataclass
class BotConfig:
    TOKEN: str = os.environ.get('BOT_TOKEN', '')
    ADMIN_ID: int = int(os.environ.get('ADMIN_ID', '0'))
    CHANNEL_URL: str = 'https://t.me/kuznya_music'
    EXAMPLES_URL: str = 'https://t.me/kuznya_music/41'
    WEBHOOK_PORT: int = int(os.environ.get('PORT', 8080))
    MAX_MESSAGE_LENGTH: int = 4000
    RATE_LIMIT_MESSAGES: int = 5
    WEBHOOK_URL: str = os.environ.get('WEBHOOK_URL', '')

config = BotConfig()
if not config.TOKEN or not config.ADMIN_ID or not config.WEBHOOK_URL:
    raise ValueError("BOT_TOKEN, ADMIN_ID, or WEBHOOK_URL missing in environment variables!")

# -------- TEXTS --------
class Messages:
    WELCOME = (
        "Привіт, <b>{}</b>! 👋\n"
        "Ласкаво просимо до музичної студії Kuznya Music!\n"
        "Оберіть дію з меню:"
    )
    RECORDING_PROMPT = (
        "🎤 <b>Запис треку</b>\n\n"
        "Опишіть ваші побажання:\n"
        "• Запис, Зведення\n"
        "• Аранжування\n"
        "• Референси (приклади)\n"
        "• Терміни (коли хочете записатись)\n\n"
        "<i>Ваше повідомлення буде передано адміністратору</i>"
    )
    EXAMPLES_INFO = (
        "🎵 <b>Наші роботи:</b>\n\n"
        "Послухати приклади можна тут:\n"
        "<a href=\"{}\">{}</a>\n\n"
        "Тут ви знайдете найкращі зразки нашої творчості!"
    )
    CHANNEL_INFO = (
        "📢 <b>Підписуйтесь на наш канал:</b>\n\n"
        "<a href=\"{}\">{}</a>\n\n"
        "Там ви знайдете:\n"
        "• Нові роботи\n"
        "• Закулісся студії\n"
        "• Акції та знижки"
    )
    CONTACTS_INFO = (
        "📲 <b>Контакти студії:</b>\n\n"
        "Telegram: @kuznya_music\n"
        "Або використовуйте кнопку '🎤 Записати трек' для прямого зв'язку"
    )
    MESSAGE_SENT = (
        "✅ Повідомлення відправлено адміністратору!\n"
        "Очікуйте відповіді...\n\n"
        "<i>Ви можете відправити додаткові повідомлення або завершити діалог</i>"
    )
    DIALOG_ENDED = "✅ Діалог завершено. Повертаємося до головного меню."
    ADMIN_REPLY = "💬 <b>Відповідь від адміністратора:</b>\n\n{}"
    USE_MENU_BUTTONS = "🤔 Використовуйте кнопки меню для навігації"
    ERROR_SEND_FAILED = "❌ Помилка при відправці повідомлення. Спробуйте пізніше."
    ERROR_MESSAGE_TOO_LONG = f"❌ Повідомлення занадто довге. Максимум {config.MAX_MESSAGE_LENGTH} символів."
    ERROR_RATE_LIMITED = "❌ Забагато повідомлень. Зачекайте хвилинку."
    ERROR_INVALID_INPUT = "❌ Некоректне повідомлення. Спробуйте ще раз."
    ADMIN_PANEL_WELCOME = (
        "👑 Вітаємо в адмін-панелі Kuznya Music!\n"
        "Оберіть дію з меню:"
    )
    ADMIN_MENU_NAV = "👑 Ви в адмін-панелі. Скористайтеся кнопками меню:"

# -------- STATES --------
class UserStates:
    IDLE = 'idle'
    WAITING_FOR_MESSAGE = 'waiting_for_message'
    ADMIN_REPLYING = 'admin_replying'

BROADCAST_STATE = 'waiting_for_broadcast_message'

# -------- LOGGING --------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot_errors.log", encoding="utf-8")
    ]
)
logger = logging.getLogger(__name__)

# -------- ERROR HANDLING DECORATOR --------
def safe_handler(func):
    def wrapper(message, *args, **kwargs):
        try:
            return func(message, *args, **kwargs)
        except Exception as e:
            logger.error(f"Handler error in {func.__name__}: {e}", exc_info=True)
            try:
                bot.send_message(message.chat.id, "❌ Виникла технічна помилка, спробуйте ще раз або пізніше.", parse_mode="HTML")
            except Exception:
                pass
    return wrapper

def safe_send(chat_id, text, **kwargs):
    try:
        bot.send_message(chat_id, text, **kwargs)
    except Exception as e:
        logger.error(f"Telegram send_message error: {e}", exc_info=True)

# -------- BOT SETUP --------
bot = telebot.TeleBot(config.TOKEN)
try:
    bot_info = bot.get_me()
    logger.info(f"Bot token is valid! Bot name: {bot_info.first_name} (@{bot_info.username})")
except Exception as token_error:
    logger.error(f"Invalid bot token: {token_error}")
    exit(1)
logger.info("Bot started (main entrypoint).")

# -------- UTILS --------
def is_admin(user_id: int) -> bool:
    return int(user_id) == int(config.ADMIN_ID)

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
    try:
        pipe = r.pipeline()
        pipe.incr(key)
        pipe.expire(key, 60)
        count, _ = pipe.execute()
        return count <= config.RATE_LIMIT_MESSAGES
    except Exception as e:
        logger.error(f"Redis error in check_rate_limit: {e}", exc_info=True)
        return True

def set_user_state(user_id: int, state: str):
    try:
        r.set(f"user:{user_id}:state", state)
    except Exception as e:
        logger.error(f"Redis error in set_user_state: {e}", exc_info=True)

def get_user_state(user_id: int) -> str:
    try:
        return r.get(f"user:{user_id}:state") or UserStates.IDLE
    except Exception as e:
        logger.error(f"Redis error in get_user_state: {e}", exc_info=True)
        return UserStates.IDLE

def get_all_user_ids():
    ids = []
    try:
        for key in r.scan_iter("user:*:state"):
            uid = key.split(":")[1]
            if uid not in ids:
                ids.append(int(uid))
    except Exception as e:
        logger.error(f"Redis error in get_all_user_ids: {e}", exc_info=True)
    return ids

def add_user(user_id: int, user=None):
    try:
        set_user_state(user_id, UserStates.IDLE)
        if user:
            info = f"{user.first_name or ''} {user.last_name or ''} @{user.username or ''}".strip()
            r.set(f"user:{user_id}:info", info)
    except Exception as e:
        logger.error(f"Redis error in add_user: {e}", exc_info=True)

def set_admin_reply_target(admin_id: int, user_id: int):
    try:
        r.set(f"admin:{admin_id}:reply", user_id)
    except Exception as e:
        logger.error(f"Redis error in set_admin_reply_target: {e}", exc_info=True)

def get_admin_reply_target(admin_id: int) -> int:
    try:
        uid = r.get(f"admin:{admin_id}:reply")
        return int(uid) if uid else None
    except Exception as e:
        logger.error(f"Redis error in get_admin_reply_target: {e}", exc_info=True)
        return None

def clear_admin_reply_target(admin_id: int):
    try:
        r.delete(f"admin:{admin_id}:reply")
    except Exception as e:
        logger.error(f"Redis error in clear_admin_reply_target: {e}", exc_info=True)

def incr_stat(key):
    try:
        r.incr(f"stat:{key}")
    except Exception as e:
        logger.error(f"Redis error in incr_stat: {e}", exc_info=True)

def get_stat(key):
    try:
        return int(r.get(f"stat:{key}") or 0)
    except Exception as e:
        logger.error(f"Redis error in get_stat: {e}", exc_info=True)
        return 0

def set_admin_state(user_id, state):
    try:
        r.set(f"admin:{user_id}:state", state)
    except Exception as e:
        logger.error(f"Redis error in set_admin_state: {e}", exc_info=True)

def get_admin_state(user_id):
    try:
        return r.get(f"admin:{user_id}:state") or ""
    except Exception as e:
        logger.error(f"Redis error in get_admin_state: {e}", exc_info=True)
        return ""

def clear_admin_state(user_id):
    try:
        r.delete(f"admin:{user_id}:state")
    except Exception as e:
        logger.error(f"Redis error in clear_admin_state: {e}", exc_info=True)

def format_admin_request(user, user_id, message_text, dt):
    tg_username = f"@{user.username}" if user.username else ""
    name = f"{user.first_name or ''} {user.last_name or ''}".strip()
    profile_link = f'<a href="tg://user?id={user_id}">{html.escape(name)}</a>'
    username_link = f" (<a href=\"https://t.me/{user.username}\">{tg_username}</a>)" if user.username else ""
    time_str = dt.strftime("%H:%M %d.%m.%Y")
    return (
        "💬 <b>Нове повідомлення від клієнта</b>\n\n"
        f"👤 <b>Клієнт:</b> {profile_link}{username_link}\n"
        f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
        f"⏰ <b>Час:</b> <code>{time_str}</code>\n\n"
        "📝 <b>Повідомлення:</b>\n"
        f"{html.escape(message_text)}"
    )

# -------- HANDLERS --------

@bot.message_handler(commands=["start"])
@safe_handler
def handle_start(message):
    add_user(message.from_user.id, message.from_user)
    if is_admin(message.from_user.id):
        safe_send(
            message.chat.id,
            Messages.ADMIN_PANEL_WELCOME,
            parse_mode="HTML",
            reply_markup=get_admin_keyboard()
        )
    else:
        safe_send(
            message.chat.id,
            Messages.WELCOME.format(html.escape(message.from_user.first_name or "")),
            parse_mode="HTML",
            reply_markup=get_main_keyboard()
        )

@bot.message_handler(func=lambda m: m.text == "🎧 Приклади робіт")
@safe_handler
def handle_examples(message):
    safe_send(
        message.chat.id, 
        Messages.EXAMPLES_INFO.format(
            html.escape(config.EXAMPLES_URL), 
            html.escape(config.EXAMPLES_URL)
        ),
        parse_mode="HTML"
    )

@bot.message_handler(func=lambda m: m.text == "📢 Підписатися")
@safe_handler
def handle_channel(message):
    safe_send(
        message.chat.id, 
        Messages.CHANNEL_INFO.format(
            html.escape(config.CHANNEL_URL), 
            html.escape(config.CHANNEL_URL)
        ),
        parse_mode="HTML"
    )

@bot.message_handler(func=lambda m: m.text == "📲 Контакти")
@safe_handler
def handle_contacts(message):
    safe_send(message.chat.id, Messages.CONTACTS_INFO, parse_mode="HTML")

@bot.message_handler(func=lambda m: m.text == "🎤 Записати трек")
@safe_handler
def handle_record(message):
    set_user_state(message.from_user.id, UserStates.WAITING_FOR_MESSAGE)
    safe_send(message.chat.id, Messages.RECORDING_PROMPT, parse_mode="HTML")

@bot.message_handler(func=lambda m: get_user_state(m.from_user.id) == UserStates.WAITING_FOR_MESSAGE)
@safe_handler
def handle_user_request(message):
    valid, err = validate_message(message)
    if not valid:
        safe_send(message.chat.id, err, parse_mode="HTML")
        return
    incr_stat("user_requests")
    user = message.from_user
    user_id = user.id
    dt = time.localtime()
    msg = format_admin_request(user, user_id, message.text, time.localtime())
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("✍️ Відповісти", callback_data=f"admin_reply_{user_id}"))
    safe_send(config.ADMIN_ID, msg, parse_mode="HTML", reply_markup=markup)
    safe_send(message.chat.id, Messages.MESSAGE_SENT, parse_mode="HTML")
    set_user_state(message.from_user.id, UserStates.IDLE)

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text == "👥 Користувачі")
@safe_handler
def admin_show_users(message):
    user_ids = get_all_user_ids()
    if not user_ids:
        safe_send(message.chat.id, "Немає користувачів.", parse_mode="HTML")
        return
    markup = types.InlineKeyboardMarkup()
    for uid in user_ids:
        try:
            info = r.get(f"user:{uid}:info") or str(uid)
        except Exception as e:
            logger.error(f"Redis error in admin_show_users/info: {e}", exc_info=True)
            info = str(uid)
        markup.add(types.InlineKeyboardButton(
            text=f"{info} (id:{uid})", callback_data=f"admin_reply_{uid}"
        ))
    safe_send(message.chat.id, "Оберіть користувача для відповіді:", reply_markup=markup, parse_mode="HTML")

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text == "📬 Активні діалоги")
@safe_handler
def admin_show_active_dialogs(message):
    user_ids = [uid for uid in get_all_user_ids() if get_user_state(uid) == UserStates.WAITING_FOR_MESSAGE]
    if not user_ids:
        safe_send(message.chat.id, "Немає активних діалогів.", parse_mode="HTML")
        return
    markup = types.InlineKeyboardMarkup()
    for uid in user_ids:
        try:
            info = r.get(f"user:{uid}:info") or str(uid)
        except Exception as e:
            logger.error(f"Redis error in admin_show_active_dialogs/info: {e}", exc_info=True)
            info = str(uid)
        markup.add(types.InlineKeyboardButton(
            text=f"{info} (id:{uid})", callback_data=f"admin_reply_{uid}"
        ))
    safe_send(message.chat.id, "Оберіть діалог для відповіді:", reply_markup=markup, parse_mode="HTML")

@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_reply_"))
def admin_select_user_for_reply(call):
    admin_id = call.from_user.id
    try:
        user_id = int(call.data.replace("admin_reply_", ""))
        set_admin_reply_target(admin_id, user_id)
        safe_send(admin_id, f"Ви обрали користувача id: {user_id}. Введіть відповідь для нього.", parse_mode="HTML")
    except Exception as e:
        logger.error(f"Callback error in admin_select_user_for_reply: {e}", exc_info=True)
        safe_send(admin_id, "❌ Трапилась помилка при виборі користувача.", parse_mode="HTML")

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and get_admin_reply_target(m.from_user.id))
@safe_handler
def admin_reply_to_selected_user(message):
    admin_id = message.from_user.id
    user_id = get_admin_reply_target(admin_id)
    try:
        incr_stat("admin_replies")
        logger.info(f"Admin {admin_id} replies to user {user_id}: {message.text[:60]}")
        safe_send(
            user_id, 
            Messages.ADMIN_REPLY.format(html.escape(message.text or "")), 
            parse_mode='HTML'
        )
        safe_send(admin_id, "✅ Відповідь відправлено користувачу.", parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error sending reply from admin to user: {e}", exc_info=True)
        safe_send(admin_id, f"❌ Не вдалося відправити відповідь: {e}", parse_mode="HTML")
    clear_admin_reply_target(admin_id)

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text == "📊 Статистика")
@safe_handler
def admin_stats(message):
    total_users = len(get_all_user_ids())
    user_requests = get_stat("user_requests")
    admin_replies = get_stat("admin_replies")
    active_chats = len([uid for uid in get_all_user_ids() if get_user_state(uid) == UserStates.WAITING_FOR_MESSAGE])
    uptime_seconds = int(time.time() - bot_start_time)
    uptime_hours = uptime_seconds // 3600
    uptime_minutes = (uptime_seconds % 3600) // 60
    start_time_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(bot_start_time))

    msg = (
        f"📊 <b>Статистика бота</b>\n\n"
        f"👥 Унікальних користувачів: <b>{total_users}</b>\n"
        f"📨 Заявок від юзерів: <b>{user_requests}</b>\n"
        f"💬 Відповідей адміна: <b>{admin_replies}</b>\n"
        f"🟢 Активних чатів: <b>{active_chats}</b>\n"
        f"⏱ Аптайм: <b>{uptime_hours} год {uptime_minutes} хв</b>\n"
        f"🚀 Останній рестарт: <b>{start_time_str}</b>"
    )
    safe_send(message.chat.id, msg, parse_mode="HTML")

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text == "📢 Розсилка")
@safe_handler
def admin_broadcast_start(message):
    set_admin_state(message.from_user.id, BROADCAST_STATE)
    safe_send(message.chat.id, "Введіть текст розсилки, який буде надіслано всім користувачам:", parse_mode="HTML")

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and get_admin_state(m.from_user.id) == BROADCAST_STATE)
@safe_handler
def admin_broadcast_process(message):
    clear_admin_state(message.from_user.id)
    text = html.escape(message.text or "")
    users = get_all_user_ids()
    delivered = 0
    errors = 0
    for i, uid in enumerate(users, start=1):
        try:
            bot.send_message(uid, f"📢 <b>Оголошення:</b>\n\n{text}", parse_mode="HTML")
            delivered += 1
        except Exception as e:
            errors += 1
            logger.warning(f"BROADCAST: failed to {uid}: {e}")
        if i % 20 == 0:
            time.sleep(0.5)
        else:
            time.sleep(0.12)
    safe_send(message.chat.id, f"Розсилка завершена!\n\n"
                               f"Успішно доставлено: <b>{delivered}</b>\n"
                               f"Помилок: <b>{errors}</b>", parse_mode="HTML")
    logger.info(f"BROADCAST: sent={delivered}, errors={errors}, total={len(users)}")

@bot.message_handler(func=lambda message: True)
@safe_handler
def handle_other_messages(message):
    if is_admin(message.from_user.id):
        safe_send(
            message.chat.id,
            Messages.ADMIN_MENU_NAV,
            reply_markup=get_admin_keyboard(),
            parse_mode="HTML"
        )
    else:
        safe_send(
            message.chat.id,
            Messages.USE_MENU_BUTTONS,
            reply_markup=get_main_keyboard(),
            parse_mode="HTML"
        )

# -------- FLASK & SELF-PING --------
app = Flask(__name__)
bot_start_time = time.time()

@app.route('/')
def health_check():
    try:
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
    except Exception as e:
        logger.error(f"Health page error: {e}", exc_info=True)
        return "<h1>Internal Error</h1>", 500

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
        logger.error(f"Health check failed: {e}", exc_info=True)
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
        logger.error(f"Status check failed: {e}", exc_info=True)
        return jsonify({
            "bot_status": "error",
            "error": str(e),
            "timestamp": time.time()
        }), 500

@app.route('/keepalive')
def keep_alive():
    try:
        return jsonify({
            "message": "Bot is alive!",
            "timestamp": time.time(),
            "uptime": int(time.time() - bot_start_time)
        })
    except Exception as e:
        logger.error(f"/keepalive error: {e}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500

@app.route(f"/bot{config.TOKEN}", methods=["POST"])
def webhook():
    if request.headers.get("content-type") == "application/json":
        try:
            json_string = request.get_data().decode("utf-8")
            update = telebot.types.Update.de_json(json_string)
            bot.process_new_updates([update])
            return "", 200
        except Exception as e:
            logger.error(f"Webhook processing error: {e}", exc_info=True)
            return "", 500
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
        time.sleep(300)

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
        logger.critical(f"Critical error: {e}", exc_info=True)
        exit(1)
