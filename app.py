import telebot
from telebot import types
import redis
import html
import os

# --- CONFIGURATION ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
UPSTASH_REDIS_REST_URL = os.getenv("UPSTASH_REDIS_REST_URL")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
USER_STATES_PREFIX = "user_state:"
ADMIN_REPLY_TARGET_PREFIX = "admin_reply_target:"
REDIS_URL = UPSTASH_REDIS_REST_URL or "redis://localhost:6379"

# --- DATA LAYER ---
r = redis.Redis.from_url(REDIS_URL, decode_responses=True)

class UserStates:
    IDLE = "idle"
    REPLY_TO_USER = "reply_to_user"

# --- BOT INIT ---
bot = telebot.TeleBot(BOT_TOKEN)

# --- UTILS ---
def is_admin(user_id):
    return user_id == ADMIN_ID

def get_user_state(user_id):
    return r.get(USER_STATES_PREFIX + str(user_id)) or UserStates.IDLE

def set_user_state(user_id, state):
    r.set(USER_STATES_PREFIX + str(user_id), state)

def get_admin_reply_target(admin_id):
    return r.get(ADMIN_REPLY_TARGET_PREFIX + str(admin_id))

def set_admin_reply_target(admin_id, user_id):
    r.set(ADMIN_REPLY_TARGET_PREFIX + str(admin_id), user_id)

def clear_admin_reply_target(admin_id):
    r.delete(ADMIN_REPLY_TARGET_PREFIX + str(admin_id))

def safe_send(user_id, text, **kwargs):
    try:
        bot.send_message(user_id, text, **kwargs)
    except Exception as e:
        print(f"Failed to send message to {user_id}: {e}")

def get_user_info(user):
    info = ""
    if user.first_name:
        info += user.first_name
    if user.last_name:
        info += " " + user.last_name
    if user.username:
        info += f" @{user.username}"
    if not info.strip():
        info = f"ID <code>{user.id}</code>"
    return info.strip()

# --- KEYBOARDS ---
def get_admin_reply_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("❌ Завершити відповідь")
    return markup

# --- HANDLERS ---

# START: автоматичний старт діалогу
@bot.message_handler(commands=['start'])
@bot.message_handler(func=lambda m: True)
def handle_user_message(message):
    user_id = message.from_user.id
    text = message.text
    info = get_user_info(message.from_user)
    r.set(f"user:{user_id}:info", info)
    # Зберігаємо повідомлення користувача для адміна
    if not is_admin(user_id):
        admin_markup = types.InlineKeyboardMarkup()
        admin_markup.add(types.InlineKeyboardButton("↩️ Відповісти", callback_data=f"user_reply_{user_id}"))
        safe_send(
            ADMIN_ID,
            f"👤 Нове повідомлення від:\n{html.escape(info)}\n\n{html.escape(text)}",
            parse_mode='HTML',
            reply_markup=admin_markup
        )
        safe_send(
            user_id,
            "✅ Ваше повідомлення отримано! Очікуйте відповідь адміністратора.",
            parse_mode='HTML'
        )

# Адмін натискає "Відповісти" під повідомленням користувача
@bot.callback_query_handler(func=lambda call: call.data.startswith("user_reply_"))
def admin_start_reply(call):
    admin_id = call.from_user.id
    if not is_admin(admin_id):
        return
    user_id = int(call.data.split("_")[-1])
    set_admin_reply_target(admin_id, user_id)
    set_user_state(admin_id, UserStates.REPLY_TO_USER)
    info = r.get(f"user:{user_id}:info") or f"ID <code>{user_id}</code>"
    safe_send(
        admin_id,
        f"✏️ Введіть відповідь для:\n{html.escape(info)}",
        parse_mode="HTML",
        reply_markup=get_admin_reply_keyboard()
    )

# Адмін відповідає користувачу
@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and get_user_state(m.from_user.id) == UserStates.REPLY_TO_USER)
def admin_reply_to_user(message):
    if message.text == "❌ Завершити відповідь":
        set_user_state(message.from_user.id, UserStates.IDLE)
        clear_admin_reply_target(message.from_user.id)
        safe_send(
            message.from_user.id,
            "❌ Відповідь скасована.",
            parse_mode="HTML"
        )
        return
    admin_id = message.from_user.id
    user_id = get_admin_reply_target(admin_id)
    info = r.get(f"user:{user_id}:info") or f"ID <code>{user_id}</code>"
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("↩️ Відповісти", callback_data=f"user_reply_{admin_id}"))
    reply_text = (
        f"💬 <b>Відповідь від адміністратора:</b>\n\n"
        f"<b>Кому:</b> {html.escape(info)}\n"
        f"{html.escape(message.text or '')}"
    )
    safe_send(
        user_id,
        reply_text,
        parse_mode='HTML',
        reply_markup=markup
    )
    # --- ОНОВЛЕНЕ ПІДТВЕРДЖЕННЯ ДЛЯ АДМІНА ---
    safe_send(
        admin_id,
        f"✅ Відповідь відправлена!\n\n<b>Кому:</b> {html.escape(info)}",
        parse_mode="HTML",
        reply_markup=get_admin_reply_keyboard()
    )
    set_user_state(admin_id, UserStates.IDLE)
    clear_admin_reply_target(admin_id)

# --- ADMIN MENU USERS ---
@bot.message_handler(commands=['users'])
def admin_users_list(message):
    if not is_admin(message.from_user.id):
        return
    keys = r.keys("user:*:info")
    users = []
    for key in keys:
        user_id = key.split(":")[1]
        info = r.get(key) or f"ID <code>{user_id}</code>"
        users.append(f"{info} (<code>{user_id}</code>)")
    msg = "👥 Користувачі:\n" + "\n".join(users) if users else "Немає користувачів."
    safe_send(
        message.from_user.id,
        msg,
        parse_mode="HTML"
    )

# --- BROADCAST: розсилка з статистикою ---
@bot.message_handler(commands=['broadcast'])
def admin_broadcast_start(message):
    if not is_admin(message.from_user.id):
        return
    safe_send(
        message.from_user.id,
        "✉️ Надішліть текст для розсилки всім користувачам:",
        parse_mode="HTML"
    )
    set_user_state(message.from_user.id, "broadcast")

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and get_user_state(m.from_user.id) == "broadcast")
def admin_broadcast_send(message):
    admin_id = message.from_user.id
    text = message.text
    keys = r.keys("user:*:info")
    delivered, errors = 0, 0
    for key in keys:
        user_id = int(key.split(":")[1])
        try:
            safe_send(user_id, f"📢 <b>Оголошення:</b>\n\n{text}", parse_mode="HTML")
            delivered += 1
        except Exception:
            errors += 1
    stats = (
        f"✅ Розсилка завершена!\n\n"
        f"Доставлено: <b>{delivered}</b>\n"
        f"Помилки: <b>{errors}</b>\n"
        f"Всього користувачів: <b>{len(keys)}</b>"
    )
    safe_send(admin_id, stats, parse_mode="HTML")
    set_user_state(admin_id, UserStates.IDLE)

# --- MAIN LOOP ---
if __name__ == "__main__":
    try:
        bot.polling(none_stop=True)
    except Exception as e:
        print(f"Bot stopped: {e}")
