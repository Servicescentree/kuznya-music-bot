import os
import time
import html
import logging
from threading import Thread
from dataclasses import dataclass
from typing import Dict, Any

import telebot
from telebot import types
from flask import Flask, jsonify

import requests  # for self-ping

# -------- ЛОГУВАННЯ --------
logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)s][%(asctime)s] %(message)s',
    datefmt='%H:%M:%S',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)
logging.getLogger('TeleBot').setLevel(logging.WARNING)

# -------- CONFIG --------
@dataclass
class BotConfig:
    TOKEN: str = os.getenv('BOT_TOKEN', '8368212048:AAF094UtSmRBYB98JUtVwYHzREuVicQFIOs')
    ADMIN_ID: int = int(os.getenv('ADMIN_ID', '7276479457'))
    CHANNEL_URL: str = 'https://t.me/kuznya_music'
    EXAMPLES_URL: str = 'https://t.me/kuznya_music/41'
    WEBHOOK_PORT: int = int(os.getenv('PORT', 8080))
    MAX_MESSAGE_LENGTH: int = 4000
    RATE_LIMIT_MESSAGES: int = 5  # повідомлень на хвилину

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
    ERROR_RATE_LIMITED = "❌ Забагато повідомлень. Зачекайте хвилину."
    ERROR_INVALID_INPUT = "❌ Некоректне повідомлення. Спробуйте ще раз."

# -------- STATES --------
class UserStates:
    IDLE = 'idle'
    WAITING_FOR_MESSAGE = 'waiting_for_message'
    ADMIN_REPLYING = 'admin_replying'

# -------- SETUP --------
config = BotConfig()
bot = telebot.TeleBot(config.TOKEN)
try:
    bot_info = bot.get_me()
    logger.info(f"Бот підключено як: {bot_info.first_name} (@{bot_info.username})")
except Exception as token_error:
    logger.error(f"❌ Некоректний токен бота: {token_error}")
    exit(1)

user_states = {}       # user_id: state
rate_limits = {}       # user_id: {'count': int, 'last_reset': timestamp}
admin_replies = {}     # admin_id: target_user_id

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
    current_time = int(time.time())
    if user_id not in rate_limits:
        rate_limits[user_id] = {'count': 1, 'last_reset': current_time}
        return True
    user_limit = rate_limits[user_id]
    if current_time - user_limit['last_reset'] > 60:
        rate_limits[user_id] = {'count': 1, 'last_reset': current_time}
        return True
    if user_limit['count'] < config.RATE_LIMIT_MESSAGES:
        user_limit['count'] += 1
        return True
    return False

def sanitize_input(text: str) -> str:
    return html.escape(text.strip())

# -------- HANDLERS --------

@bot.message_handler(commands=['start'])
def handle_start(message):
    user_info = get_user_info(message.from_user)
    if is_admin(message.from_user.id):
        markup = get_admin_keyboard()
        logger.info(f"Адмін {user_info['id']} відкрив адмін-панель.")
        bot.send_message(
            message.chat.id,
            "👨‍💼 Ви у панелі адміністратора. Оберіть дію:",
            reply_markup=markup
        )
    else:
        markup = get_main_keyboard()
        user_states[message.from_user.id] = UserStates.IDLE
        logger.info(f"Користувач {user_info['id']} стартував бота.")
        bot.send_message(
            message.chat.id,
            Messages.WELCOME.format(user_info['first_name']),
            reply_markup=markup
        )

# --- Адмінські кнопки ---
@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text == "📢 Розсилка")
def handle_admin_broadcast(message):
    bot.send_message(message.chat.id, "✍️ Відправте текст розсилки. Всі користувачі отримають це повідомлення.")

    def broadcast_handler(msg):
        txt = msg.text
        count = 0
        for uid in user_states:
            if uid != config.ADMIN_ID:
                try:
                    bot.send_message(uid, f"📢 [Розсилка]\n\n{txt}")
                    count += 1
                except Exception as e:
                    logger.warning(f"Не вдалося відправити розсилку користувачу {uid}: {e}")
        bot.send_message(config.ADMIN_ID, f"✅ Розсилку відправлено {count} користувачам.")

    bot.register_next_step_handler(message, broadcast_handler)

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text == "📊 Статистика")
def handle_show_stats(message):
    active_users = len([uid for uid, state in user_states.items() if state == UserStates.WAITING_FOR_MESSAGE])
    total_users = len(user_states)
    active_hour = len([uid for uid, data in rate_limits.items() if time.time() - data['last_reset'] < 3600])
    stats_text = f"""📊 *Детальна статистика*

👥 Всього користувачів: {total_users}
💬 Активних чатів: {active_users}
⏰ Активних за годину: {active_hour}
📅 Дата: {time.strftime('%d.%m.%Y %H:%M')}

🔧 Технічна інформація:
• Зберігання: In-Memory (Render-optimized)
• Логування: активне
• Рейт-лімітинг: {config.RATE_LIMIT_MESSAGES} повідомлень/хвилину"""
    bot.send_message(
        message.chat.id,
        stats_text,
        parse_mode='Markdown'
    )

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text == "📬 Активні діалоги")
def handle_admin_active_dialogs(message):
    users = [uid for uid, state in user_states.items() if state == UserStates.WAITING_FOR_MESSAGE]
    txt = "📬 Активні діалоги:\n\n"
    for uid in users:
        txt += f"• ID: <code>{uid}</code>\n"
    if not users:
        txt += "Немає активних діалогів."
    bot.send_message(message.chat.id, txt, parse_mode="HTML")

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text == "👥 Користувачі")
def handle_admin_users(message):
    users = [uid for uid in user_states if uid != config.ADMIN_ID]
    txt = "👥 Список користувачів:\n\n"
    for uid in users:
        txt += f"• ID: <code>{uid}</code>\n"
    if not users:
        txt += "Немає користувачів."
    bot.send_message(message.chat.id, txt, parse_mode="HTML")

# --- Користувацькі кнопки ---
@bot.message_handler(func=lambda message: not is_admin(message.from_user.id) and message.text == "🎤 Записати трек")
def handle_start_recording(message):
    user_id = message.from_user.id
    user_states[user_id] = UserStates.WAITING_FOR_MESSAGE
    markup = get_chat_keyboard()
    bot.send_message(
        message.chat.id,
        Messages.RECORDING_PROMPT,
        parse_mode='Markdown',
        reply_markup=markup
    )

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

@bot.message_handler(func=lambda message: not is_admin(message.from_user.id) and message.text == "📢 Підписатися")
def handle_show_channel(message):
    bot.send_message(
        message.chat.id,
        Messages.CHANNEL_INFO.format(config.CHANNEL_URL),
        disable_web_page_preview=False
    )

@bot.message_handler(func=lambda message: not is_admin(message.from_user.id) and message.text == "📲 Контакти")
def handle_show_contacts(message):
    bot.send_message(
        message.chat.id,
        Messages.CONTACTS_INFO
    )

@bot.message_handler(func=lambda message: not is_admin(message.from_user.id) and message.text == "❌ Завершити діалог")
def handle_end_dialog(message):
    user_id = message.from_user.id
    if user_id in user_states:
        user_states[user_id] = UserStates.IDLE
    markup = get_main_keyboard()
    bot.send_message(
        message.chat.id,
        Messages.DIALOG_ENDED,
        reply_markup=markup
    )

@bot.message_handler(func=lambda message: user_states.get(message.from_user.id) == UserStates.WAITING_FOR_MESSAGE)
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
    bot.send_message(
        config.ADMIN_ID,
        admin_text,
        parse_mode='Markdown',
        reply_markup=markup
    )
    bot.forward_message(config.ADMIN_ID, message.chat.id, message.message_id)
    bot.send_message(message.chat.id, Messages.MESSAGE_SENT)

# ---- АДМІН ВІДПОВІДІ ----

@bot.callback_query_handler(func=lambda call: call.data.startswith('reply_'))
def handle_admin_reply_callback(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ Немає доступу")
        return
    user_id = int(call.data.split('_')[1])
    admin_replies[config.ADMIN_ID] = user_id
    user_states[config.ADMIN_ID] = f"{UserStates.ADMIN_REPLYING}_{user_id}"
    bot.answer_callback_query(call.id, "Напишіть відповідь наступним повідомленням")
    bot.send_message(
        config.ADMIN_ID,
        f"✍️ Напишіть відповідь клієнту (ID: {user_id}):\n\n"
        "_Наступне повідомлення буде відправлено клієнту_"
    )

@bot.message_handler(func=lambda message: is_admin(message.from_user.id))
def handle_admin_reply_or_panel(message):
    admin_id = message.from_user.id

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

    state = user_states.get(admin_id, '')
    if state and state.startswith(UserStates.ADMIN_REPLYING):
        target_user_id = admin_replies.get(admin_id)
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
        user_states[admin_id] = UserStates.IDLE
        admin_replies.pop(admin_id, None)
        return

    markup = get_admin_keyboard()
    bot.send_message(
        admin_id,
        Messages.USE_MENU_BUTTONS,
        reply_markup=markup
    )

# --- catch-all останнім! ---
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
    <p><strong>Uptime:</strong> {uptime_hours} год {uptime_minutes} хв</p>
    <p><strong>Час запуску:</strong> {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(bot_start_time))}</p>
    <p><strong>Поточний час:</strong> {time.strftime('%Y-%m-%d %H:%M:%S')}</p>
    <p><strong>Користувачів:</strong> {len(user_states)}</p>
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
            "total_users": len(user_states),
            "version": "3.0-admin-panel"
        }), 200
    except Exception as e:
        logger.error(f"Health check failed: {e}")  # коротко, без traceback
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
        active_users = len([uid for uid, state in user_states.items() if state == UserStates.WAITING_FOR_MESSAGE])
        return jsonify({
            "bot_status": "running",
            "uptime_seconds": int(time.time() - bot_start_time),
            "total_users": len(user_states),
            "active_chats": active_users,
            "admin_id": config.ADMIN_ID,
            "timestamp": time.time()
        })
    except Exception as e:
        logger.error(f"Status check failed: {e}")  # коротко, без traceback
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
            logger.debug(f"[SELF-PING] Pinged {url} ({r.status_code})")
        except Exception as e:
            logger.debug(f"[SELF-PING] Error pinging {url}: {e}")
        time.sleep(300)  # 5 хвилин

if __name__ == "__main__":
    try:
        logger.info("Запуск Kuznya Music Studio Bot...")
        flask_thread = Thread(target=run_flask, daemon=True)
        flask_thread.start()
        selfping_thread = Thread(target=self_ping, daemon=True)
        selfping_thread.start()
        logger.info("🎵 Бот запущено!")
        logger.info(f"ID адміністратора: {config.ADMIN_ID}")
        while True:
            try:
                bot.polling(none_stop=True, interval=1, timeout=30)
            except telebot.apihelper.ApiTelegramException as api_error:
                if "409" in str(api_error) or "Conflict" in str(api_error):
                    logger.warning("Конфлікт: інший екземпляр бота вже працює. Перезапуск через 10 секунд...")
                    time.sleep(10)
                    try:
                        bot.stop_polling()
                        bot.remove_webhook()
                    except:
                        pass
                    time.sleep(5)
                    continue
                else:
                    logger.error(f"Помилка Telegram API: {api_error}")
                    time.sleep(10)
    except KeyboardInterrupt:
        logger.info("Бот зупинено користувачем")
        try:
            bot.stop_polling()
        except:
            pass
    except Exception as e:
        logger.critical(f"Критична помилка: {e}")
        try:
            bot.stop_polling()
        except:
            pass
        exit(1)
