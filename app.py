import os
import time
import html
import logging
from threading import Thread
from typing import Optional, Dict, Any
from dataclasses import dataclass

import telebot
from telebot import types
from flask import Flask, jsonify

import requests  # for self-ping

# Configuration
@dataclass
class BotConfig:
    TOKEN: str = os.getenv('BOT_TOKEN', '8368212048:AAF094UtSmRBYB98JUtVwYHzREuVicQFIOs')
    ADMIN_ID: int = int(os.getenv('ADMIN_ID', '7276479457'))
    CHANNEL_URL: str = 'https://t.me/kuznya_music'
    EXAMPLES_URL: str = 'https://t.me/kuznya_music/41'
    WEBHOOK_PORT: int = int(os.getenv('PORT', 8080))
    MAX_MESSAGE_LENGTH: int = 4000
    RATE_LIMIT_MESSAGES: int = 5  # messages per minute

# Text messages
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
    
    # Error messages
    ERROR_SEND_FAILED = "❌ Помилка при відправці повідомлення. Спробуйте пізніше."
    ERROR_MESSAGE_TOO_LONG = f"❌ Повідомлення занадто довге. Максимум {BotConfig.MAX_MESSAGE_LENGTH} символів."
    ERROR_RATE_LIMITED = "❌ Забагато повідомлень. Зачекайте хвилинку."
    ERROR_INVALID_INPUT = "❌ Некоректне повідомлення. Спробуйте ще раз."

# User states
class UserStates:
    IDLE = 'idle'
    WAITING_FOR_MESSAGE = 'waiting_for_message'
    ADMIN_REPLYING = 'admin_replying'

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# Initialize configuration
config = BotConfig()

# Validate configuration
if not config.TOKEN or not config.ADMIN_ID:
    logger.error("Missing required environment variables: BOT_TOKEN or ADMIN_ID")
    exit(1)

# Initialize bot
try:
    bot = telebot.TeleBot(config.TOKEN)
    logger.info("Testing bot token...")
    bot_info = bot.get_me()
    logger.info(f"Bot token is valid! Bot name: {bot_info.first_name} (@{bot_info.username})")
except Exception as token_error:
    logger.error(f"Invalid bot token: {token_error}")
    logger.error(f"Token used: {config.TOKEN}")
    exit(1)

# In-memory storage for Render
user_states = {}  # user_id: state
rate_limits = {}  # user_id: {'count': int, 'last_reset': timestamp}
admin_replies = {}  # admin_id: target_user_id

# In-memory logic
class MemoryManager:
    @staticmethod
    def get_user_state(user_id: int) -> str:
        return user_states.get(user_id, UserStates.IDLE)
    
    @staticmethod
    def set_user_state(user_id: int, state: str):
        user_states[user_id] = state
        logger.info(f"Set user {user_id} state to {state}")
    
    @staticmethod
    def clear_user_state(user_id: int):
        user_states.pop(user_id, None)
        logger.info(f"Cleared state for user {user_id}")
    
    @staticmethod
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

def validate_message(message) -> tuple[bool, str]:
    if not message or not message.text:
        return False, Messages.ERROR_INVALID_INPUT
    if len(message.text) > config.MAX_MESSAGE_LENGTH:
        return False, Messages.ERROR_MESSAGE_TOO_LONG
    if not MemoryManager.check_rate_limit(message.from_user.id):
        return False, Messages.ERROR_RATE_LIMITED
    return True, ""

def sanitize_input(text: str) -> str:
    return html.escape(text.strip())

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

def is_admin(user_id: int) -> bool:
    return user_id == config.ADMIN_ID

def get_user_info(user) -> Dict[str, Any]:
    return {
        'id': user.id,
        'username': user.username or "Без username",
        'first_name': user.first_name or "Невідомо",
        'last_name': user.last_name or "",
        'full_name': f"{user.first_name or ''} {user.last_name or ''}".strip()
    }

# Message handlers
@bot.message_handler(commands=['start'])
def handle_start(message):
    try:
        user_info = get_user_info(message.from_user)
        logger.info(f"New user started bot: {user_info['id']} (@{user_info['username']})")
        MemoryManager.set_user_state(message.from_user.id, UserStates.IDLE)
        markup = get_main_keyboard()
        bot.send_message(
            message.chat.id,
            Messages.WELCOME.format(user_info['first_name']),
            reply_markup=markup
        )
    except Exception as e:
        logger.error(f"Error in handle_start: {e}")
        bot.send_message(message.chat.id, Messages.ERROR_SEND_FAILED)

@bot.message_handler(func=lambda message: message.text == "🎤 Записати трек")
def handle_start_recording(message):
    try:
        user_id = message.from_user.id
        MemoryManager.set_user_state(user_id, UserStates.WAITING_FOR_MESSAGE)
        markup = get_chat_keyboard()
        bot.send_message(
            message.chat.id,
            Messages.RECORDING_PROMPT,
            parse_mode='Markdown',
            reply_markup=markup
        )
        logger.info(f"User {user_id} entered recording mode")
    except Exception as e:
        logger.error(f"Error in handle_start_recording: {e}")
        bot.send_message(message.chat.id, Messages.ERROR_SEND_FAILED)

@bot.message_handler(func=lambda message: message.text == "🎧 Приклади робіт")
def handle_show_examples(message):
    try:
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
        logger.info(f"Examples message sent successfully to {message.from_user.id}")
    except Exception as e:
        logger.error(f"Error in handle_show_examples: {e}")
        bot.send_message(message.chat.id, Messages.ERROR_SEND_FAILED)

@bot.message_handler(func=lambda message: message.text == "📢 Підписатися")
def handle_show_channel(message):
    try:
        logger.info(f"User {message.from_user.id} requested channel info")
        bot.send_message(
            message.chat.id,
            Messages.CHANNEL_INFO.format(config.CHANNEL_URL),
            disable_web_page_preview=False
        )
        logger.info(f"Channel message sent successfully to {message.from_user.id}")
    except Exception as e:
        logger.error(f"Error in handle_show_channel: {e}")
        bot.send_message(message.chat.id, Messages.ERROR_SEND_FAILED)

@bot.message_handler(func=lambda message: message.text == "📲 Контакти")
def handle_show_contacts(message):
    try:
        bot.send_message(
            message.chat.id,
            Messages.CONTACTS_INFO
        )
    except Exception as e:
        logger.error(f"Error in handle_show_contacts: {e}")
        bot.send_message(message.chat.id, Messages.ERROR_SEND_FAILED)

@bot.message_handler(func=lambda message: message.text == "❌ Завершити діалог")
def handle_end_dialog(message):
    try:
        user_id = message.from_user.id
        MemoryManager.clear_user_state(user_id)
        markup = get_main_keyboard()
        bot.send_message(
            message.chat.id,
            Messages.DIALOG_ENDED,
            reply_markup=markup
        )
        logger.info(f"User {user_id} ended dialog")
    except Exception as e:
        logger.error(f"Error in handle_end_dialog: {e}")
        bot.send_message(message.chat.id, Messages.ERROR_SEND_FAILED)

# --- ЮЗЕР ПИШЕ (ДІАЛОГ) ---
@bot.message_handler(func=lambda message: MemoryManager.get_user_state(message.from_user.id) == UserStates.WAITING_FOR_MESSAGE)
def handle_user_message(message):
    try:
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
        logger.info(f"Message forwarded from user {user_info['id']} to admin")
    except telebot.apihelper.ApiException as e:
        logger.error(f"Telegram API error in handle_user_message: {e}")
        bot.send_message(message.chat.id, Messages.ERROR_SEND_FAILED)
    except Exception as e:
        logger.error(f"Error in handle_user_message: {e}")
        bot.send_message(message.chat.id, Messages.ERROR_SEND_FAILED)

# --- АДМІН ВІДПОВІДАЄ (reply або кнопка) ---
@bot.callback_query_handler(func=lambda call: call.data.startswith('reply_'))
def handle_admin_reply_callback(call):
    try:
        if not is_admin(call.from_user.id):
            bot.answer_callback_query(call.id, "❌ Немає доступу")
            return
        user_id = int(call.data.split('_')[1])
        admin_replies[config.ADMIN_ID] = user_id
        MemoryManager.set_user_state(config.ADMIN_ID, f"{UserStates.ADMIN_REPLYING}_{user_id}")
        bot.answer_callback_query(call.id, "Напишіть відповідь наступним повідомленням")
        bot.send_message(
            config.ADMIN_ID,
            f"✍️ Напишіть відповідь клієнту (ID: {user_id}):\n\n"
            "_Наступне повідомлення буде відправлено клієнту_"
        )
        logger.info(f"Admin started replying to user {user_id}")
    except Exception as e:
        logger.error(f"Error in handle_admin_reply_callback: {e}")
        bot.answer_callback_query(call.id, "❌ Помилка")

@bot.message_handler(func=lambda message: is_admin(message.from_user.id))
def handle_admin_reply_or_panel(message):
    admin_id = message.from_user.id

    # 1. Якщо reply на forward-повідомлення (адмін просто відповідає у Telegram)
    if message.reply_to_message and message.reply_to_message.forward_from:
        user_id = message.reply_to_message.forward_from.id
        sanitized_reply = sanitize_input(message.text)
        try:
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
            logger.info(f"Admin replied to user {user_id} via reply-forward")
        except Exception as e:
            logger.error(f"Failed to send admin reply via reply-forward: {e}")
            bot.send_message(admin_id, f"❌ Помилка при відправці: {e}")
        return

    # 2. Якщо адмін у callback-режимі (натиснув "Відповісти")
    if MemoryManager.get_user_state(admin_id).startswith(UserStates.ADMIN_REPLYING):
        target_user_id = admin_replies.get(admin_id)
        if not target_user_id:
            bot.send_message(admin_id, "❌ Помилка: не знайдено користувача для відповіді")
            return
        sanitized_reply = sanitize_input(message.text)
        try:
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
            logger.info(f"Admin replied to user {target_user_id} via button")
        except Exception as e:
            logger.error(f"Failed to send admin reply via button: {e}")
            bot.send_message(admin_id, f"❌ Помилка при відправці: {e}")
        finally:
            MemoryManager.set_user_state(admin_id, UserStates.IDLE)
            admin_replies.pop(admin_id, None)
        return

    # 3. Якщо просто пише щось інше — показуємо меню
    if message.text and message.text.startswith("/"):
        # тут можеш викликати свої команди, як у тебе було
        return

    markup = get_main_keyboard()
    bot.send_message(
        admin_id,
        Messages.USE_MENU_BUTTONS,
        reply_markup=markup
    )

# --- Додаткові адмін-команди ---
@bot.message_handler(commands=['admin'], func=lambda message: is_admin(message.from_user.id))
def handle_admin_panel(message):
    try:
        active_users = len([uid for uid, state in user_states.items() if state == UserStates.WAITING_FOR_MESSAGE])
        total_users = len(user_states)
        admin_text = f"""👨‍💼 *Панель адміністратора*

📊 Активних діалогів: {active_users}
👥 Всього користувачів: {total_users}
🤖 Бот працює нормально

💡 *Команди:*
/stats - детальна статистика"""
        bot.send_message(
            config.ADMIN_ID,
            admin_text,
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Error in handle_admin_panel: {e}")
        bot.send_message(config.ADMIN_ID, "❌ Помилка при завантаженні панелі")

@bot.message_handler(commands=['stats'], func=lambda message: is_admin(message.from_user.id))
def handle_stats(message):
    try:
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
            config.ADMIN_ID,
            stats_text,
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Error in handle_stats: {e}")
        bot.send_message(config.ADMIN_ID, "❌ Помилка при завантаженні статистики")

@bot.message_handler(func=lambda message: True)
def handle_other_messages(message):
    try:
        if MemoryManager.get_user_state(message.from_user.id) == UserStates.IDLE:
            markup = get_main_keyboard()
            bot.send_message(
                message.chat.id,
                Messages.USE_MENU_BUTTONS,
                reply_markup=markup
            )
    except Exception as e:
        logger.error(f"Error in handle_other_messages: {e}")

# Flask app for health check and Uptime Robot integration
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
            "version": "2.1-render"
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
        time.sleep(300)  # 5 хвилин

if __name__ == "__main__":
    try:
        logger.info("Starting Kuznya Music Studio Bot...")
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
        while True:
            try:
                bot.polling(none_stop=True, interval=1, timeout=30)
            except telebot.apihelper.ApiTelegramException as api_error:
                if "409" in str(api_error) or "Conflict" in str(api_error):
                    logger.warning("Conflict detected - another bot instance running. Retrying in 10 seconds...")
                    time.sleep(10)
                    try:
                        bot.stop_polling()
                        bot.remove_webhook()
                    except:
                        pass
                    time.sleep(5)
                    continue
                else:
                    raise api_error
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
