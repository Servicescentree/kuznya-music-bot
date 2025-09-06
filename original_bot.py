"""
Kuznya Music Studio Telegram Bot
Improved version with proper error handling, logging, security, and Uptime Robot integration
"""

import os
import time
import html
import logging
import sqlite3
from threading import Thread
from typing import Optional, Dict, Any
from dataclasses import dataclass
from contextlib import contextmanager

import telebot
from telebot import types
from flask import Flask, jsonify
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration
@dataclass
class BotConfig:
    # 
    TOKEN: str = '8368212048:AAFPu81rvI7ISpmtixdgD1cOybAQ6T_rMjI'
    ADMIN_ID: int = 7276479457
    CHANNEL_URL: str = 'https://t.me/kuznya_music'
    EXAMPLES_URL: str = 'https://t.me/kuznya_music/41'
    DATABASE_PATH: str = 'bot_data.db'
    WEBHOOK_PORT: int = int(os.getenv('PORT', 8080))  # Тільки PORT з Replit
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
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Validate configuration
config = BotConfig()
if not config.TOKEN or not config.ADMIN_ID:
    logger.error("Missing required environment variables: BOT_TOKEN or ADMIN_ID")
    exit(1)

# Initialize bot
bot = telebot.TeleBot(config.TOKEN)

# Database setup
def init_database():
    """Initialize SQLite database with required tables."""
    with sqlite3.connect(config.DATABASE_PATH) as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS user_states (
                user_id INTEGER PRIMARY KEY,
                state TEXT DEFAULT 'idle',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.execute('''
            CREATE TABLE IF NOT EXISTS user_sessions (
                user_id INTEGER PRIMARY KEY,
                admin_message_id INTEGER,
                user_message_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.execute('''
            CREATE TABLE IF NOT EXISTS rate_limits (
                user_id INTEGER PRIMARY KEY,
                message_count INTEGER DEFAULT 0,
                last_reset TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()

@contextmanager
def get_db_connection():
    """Get database connection with automatic closing."""
    conn = sqlite3.connect(config.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

# Database operations
class DatabaseManager:
    @staticmethod
    def get_user_state(user_id: int) -> str:
        """Get user's current state."""
        with get_db_connection() as conn:
            result = conn.execute(
                'SELECT state FROM user_states WHERE user_id = ?', 
                (user_id,)
            ).fetchone()
            return result['state'] if result else UserStates.IDLE
    
    @staticmethod
    def set_user_state(user_id: int, state: str):
        """Set user's state."""
        with get_db_connection() as conn:
            conn.execute('''
                INSERT OR REPLACE INTO user_states (user_id, state, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
            ''', (user_id, state))
            conn.commit()
    
    @staticmethod
    def clear_user_state(user_id: int):
        """Clear user's state."""
        with get_db_connection() as conn:
            conn.execute('DELETE FROM user_states WHERE user_id = ?', (user_id,))
            conn.execute('DELETE FROM user_sessions WHERE user_id = ?', (user_id,))
            conn.commit()
    
    @staticmethod
    def check_rate_limit(user_id: int) -> bool:
        """Check if user exceeds rate limit."""
        current_time = int(time.time())
        
        with get_db_connection() as conn:
            result = conn.execute(
                'SELECT message_count, last_reset FROM rate_limits WHERE user_id = ?',
                (user_id,)
            ).fetchone()
            
            if not result:
                # First message from user
                conn.execute(
                    'INSERT INTO rate_limits (user_id, message_count, last_reset) VALUES (?, 1, ?)',
                    (user_id, current_time)
                )
                conn.commit()
                return True
            
            # Reset counter if more than 1 minute passed
            if current_time - result['last_reset'] > 60:
                conn.execute(
                    'UPDATE rate_limits SET message_count = 1, last_reset = ? WHERE user_id = ?',
                    (current_time, user_id)
                )
                conn.commit()
                return True
            
            # Check if under limit
            if result['message_count'] < config.RATE_LIMIT_MESSAGES:
                conn.execute(
                    'UPDATE rate_limits SET message_count = message_count + 1 WHERE user_id = ?',
                    (user_id,)
                )
                conn.commit()
                return True
            
            return False

# Input validation
def validate_message(message) -> tuple[bool, str]:
    """Validate user message."""
    if not message or not message.text:
        return False, Messages.ERROR_INVALID_INPUT
    
    if len(message.text) > config.MAX_MESSAGE_LENGTH:
        return False, Messages.ERROR_MESSAGE_TOO_LONG
    
    if not DatabaseManager.check_rate_limit(message.from_user.id):
        return False, Messages.ERROR_RATE_LIMITED
    
    return True, ""

def sanitize_input(text: str) -> str:
    """Sanitize user input."""
    return html.escape(text.strip())

# Keyboards
def get_main_keyboard():
    """Main menu keyboard."""
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
    """Chat mode keyboard."""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    markup.add(types.KeyboardButton("❌ Завершити діалог"))
    return markup

# Helper functions
def is_admin(user_id: int) -> bool:
    """Check if user is admin."""
    return user_id == config.ADMIN_ID

def get_user_info(user) -> Dict[str, Any]:
    """Get formatted user information."""
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
    """Handle /start command."""
    try:
        user_info = get_user_info(message.from_user)
        logger.info(f"New user started bot: {user_info['id']} (@{user_info['username']})")
        
        # Reset user state
        DatabaseManager.set_user_state(message.from_user.id, UserStates.IDLE)
        
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
    """Start recording chat mode."""
    try:
        user_id = message.from_user.id
        DatabaseManager.set_user_state(user_id, UserStates.WAITING_FOR_MESSAGE)
        
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
    """Show examples of work."""
    try:
        bot.send_message(
            message.chat.id,
            Messages.EXAMPLES_INFO.format(config.EXAMPLES_URL),
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Error in handle_show_examples: {e}")
        bot.send_message(message.chat.id, Messages.ERROR_SEND_FAILED)

@bot.message_handler(func=lambda message: message.text == "📢 Підписатися")
def handle_show_channel(message):
    """Show channel information."""
    try:
        logger.info(f"User {message.from_user.id} requested channel info")
        
        response_text = f"""📢 *Підписуйтесь на наш канал:*

{config.CHANNEL_URL}

Там ви знайдете:
• Нові роботи
• Закулісся студії
• Акції та знижки"""
        
        bot.send_message(
            message.chat.id,
            response_text,
            parse_mode='Markdown',
            disable_web_page_preview=False
        )
        logger.info(f"Channel message sent successfully to {message.from_user.id}")
    except Exception as e:
        logger.error(f"Error in handle_show_channel: {e}")
        bot.send_message(message.chat.id, f"❌ Помилка при відправці повідомлення: {str(e)}")

@bot.message_handler(func=lambda message: message.text == "📲 Контакти")
def handle_show_contacts(message):
    """Show contact information."""
    try:
        bot.send_message(
            message.chat.id,
            Messages.CONTACTS_INFO,
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Error in handle_show_contacts: {e}")
        bot.send_message(message.chat.id, Messages.ERROR_SEND_FAILED)

@bot.message_handler(func=lambda message: message.text == "❌ Завершити діалог")
def handle_end_dialog(message):
    """End current dialog."""
    try:
        user_id = message.from_user.id
        DatabaseManager.clear_user_state(user_id)
        
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

@bot.message_handler(func=lambda message: DatabaseManager.get_user_state(message.from_user.id) == UserStates.WAITING_FOR_MESSAGE)
def handle_user_message(message):
    """Handle messages from users to admin."""
    try:
        # Validate message
        is_valid, error_msg = validate_message(message)
        if not is_valid:
            bot.send_message(message.chat.id, error_msg)
            return
        
        user_info = get_user_info(message.from_user)
        sanitized_text = sanitize_input(message.text)
        
        # Format message for admin
        admin_text = f"""💬 *Нове повідомлення від клієнта*

👤 *Клієнт:* {user_info['full_name']} (@{user_info['username']})
🆔 *ID:* `{user_info['id']}`
⏰ *Час:* {time.strftime('%H:%M %d.%m.%Y')}

📝 *Повідомлення:*
{sanitized_text}"""
        
        # Create reply button
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(
            "✍️ Відповісти",
            callback_data=f"reply_{user_info['id']}"
        ))
        
        # Send to admin
        bot.send_message(
            config.ADMIN_ID,
            admin_text,
            parse_mode='Markdown',
            reply_markup=markup
        )
        
        # Confirm to user
        bot.send_message(message.chat.id, Messages.MESSAGE_SENT)
        
        logger.info(f"Message forwarded from user {user_info['id']} to admin")
        
    except telebot.apihelper.ApiException as e:
        logger.error(f"Telegram API error in handle_user_message: {e}")
        bot.send_message(message.chat.id, Messages.ERROR_SEND_FAILED)
    except Exception as e:
        logger.error(f"Error in handle_user_message: {e}")
        bot.send_message(message.chat.id, Messages.ERROR_SEND_FAILED)

@bot.callback_query_handler(func=lambda call: call.data.startswith('reply_'))
def handle_admin_reply_callback(call):
    """Handle admin reply callback."""
    try:
        if not is_admin(call.from_user.id):
            bot.answer_callback_query(call.id, "❌ Немає доступу")
            return
        
        user_id = int(call.data.split('_')[1])
        DatabaseManager.set_user_state(config.ADMIN_ID, f"{UserStates.ADMIN_REPLYING}_{user_id}")
        
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

@bot.message_handler(func=lambda message: is_admin(message.from_user.id) and DatabaseManager.get_user_state(message.from_user.id).startswith(UserStates.ADMIN_REPLYING))
def handle_admin_reply(message):
    """Handle admin reply to user."""
    try:
        # Get target user ID
        admin_state = DatabaseManager.get_user_state(config.ADMIN_ID)
        target_user_id = int(admin_state.split('_')[2])
        
        sanitized_reply = sanitize_input(message.text)
        
        # Send to user
        bot.send_message(
            target_user_id,
            Messages.ADMIN_REPLY.format(sanitized_reply),
            parse_mode='Markdown'
        )
        
        # Confirm to admin
        bot.send_message(
            config.ADMIN_ID,
            f"✅ Відповідь відправлено клієнту (ID: {target_user_id})"
        )
        
        # Clear admin state
        DatabaseManager.set_user_state(config.ADMIN_ID, UserStates.IDLE)
        
        logger.info(f"Admin replied to user {target_user_id}")
        
    except ValueError:
        bot.send_message(config.ADMIN_ID, "❌ Помилка: некоректний ID користувача")
    except telebot.apihelper.ApiException as e:
        logger.error(f"Failed to send admin reply: {e}")
        bot.send_message(config.ADMIN_ID, f"❌ Помилка при відправці: користувач заблокував бота")
    except Exception as e:
        logger.error(f"Error in handle_admin_reply: {e}")
        bot.send_message(config.ADMIN_ID, f"❌ Помилка при відправці: {e}")
    finally:
        DatabaseManager.set_user_state(config.ADMIN_ID, UserStates.IDLE)

@bot.message_handler(commands=['admin'], func=lambda message: is_admin(message.from_user.id))
def handle_admin_panel(message):
    """Admin panel."""
    try:
        with get_db_connection() as conn:
            active_users = conn.execute(
                'SELECT COUNT(*) as count FROM user_states WHERE state = ?',
                (UserStates.WAITING_FOR_MESSAGE,)
            ).fetchone()['count']
            
            total_users = conn.execute(
                'SELECT COUNT(*) as count FROM user_states'
            ).fetchone()['count']
        
        admin_text = f"""👨‍💼 *Панель адміністратора*

📊 Активних діалогів: {active_users}
👥 Всього користувачів: {total_users}
🤖 Бот працює нормально

💡 *Команди:*
/stats - детальна статистика
/broadcast - розсилка (в розробці)"""
        
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
    """Show detailed statistics."""
    try:
        with get_db_connection() as conn:
            stats = conn.execute('''
                SELECT 
                    (SELECT COUNT(*) FROM user_states) as total_users,
                    (SELECT COUNT(*) FROM user_states WHERE state = ?) as active_chats,
                    (SELECT COUNT(*) FROM rate_limits WHERE last_reset > datetime('now', '-1 hour')) as active_hour
            ''', (UserStates.WAITING_FOR_MESSAGE,)).fetchone()
        
        stats_text = f"""📊 *Детальна статистика*

👥 Всього користувачів: {stats['total_users']}
💬 Активних чатів: {stats['active_chats']}
⏰ Активних за годину: {stats['active_hour']}
📅 Дата: {time.strftime('%d.%m.%Y %H:%M')}

🔧 Технічна інформація:
• База даних: SQLite
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
    """Handle all other messages."""
    try:
        if DatabaseManager.get_user_state(message.from_user.id) == UserStates.IDLE:
            markup = get_main_keyboard()
            bot.send_message(
                message.chat.id,
                Messages.USE_MENU_BUTTONS,
                reply_markup=markup
            )
    except Exception as e:
        logger.error(f"Error in handle_other_messages: {e}")

# Flask app for health check and Uptime Robot integration
app = Flask('')

# Глобальна змінна для відстеження стану бота
bot_start_time = time.time()

@app.route('/')
def health_check():
    """Головна сторінка для перевірки стану бота."""
    uptime_seconds = int(time.time() - bot_start_time)
    uptime_hours = uptime_seconds // 3600
    uptime_minutes = (uptime_seconds % 3600) // 60
    
    return f"""
    <h1>🎵 Kuznya Music Studio Bot</h1>
    <p><strong>Статус:</strong> ✅ Активний</p>
    <p><strong>Uptime:</strong> {uptime_hours}год {uptime_minutes}хв</p>
    <p><strong>Час запуску:</strong> {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(bot_start_time))}</p>
    <p><strong>Поточний час:</strong> {time.strftime('%Y-%m-%d %H:%M:%S')}</p>
    """

@app.route('/health')
def health():
    """JSON health endpoint для Uptime Robot."""
    try:
        # Перевіряємо, чи бот може відповідати
        bot_info = bot.get_me()
        
        # Перевіряємо базу даних
        with get_db_connection() as conn:
            conn.execute('SELECT 1').fetchone()
        
        return jsonify({
            "status": "healthy",
            "timestamp": time.time(),
            "uptime_seconds": int(time.time() - bot_start_time),
            "bot_username": bot_info.username,
            "version": "2.0"
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
    """Простий ping endpoint для швидкої перевірки."""
    return "pong", 200

@app.route('/status')
def status():
    """Детальна інформація про стан бота."""
    try:
        with get_db_connection() as conn:
            total_users = conn.execute('SELECT COUNT(*) as count FROM user_states').fetchone()['count']
            active_users = conn.execute(
                'SELECT COUNT(*) as count FROM user_states WHERE state = ?',
                (UserStates.WAITING_FOR_MESSAGE,)
            ).fetchone()['count']
        
        return jsonify({
            "bot_status": "running",
            "uptime_seconds": int(time.time() - bot_start_time),
            "total_users": total_users,
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

# Функція для keep-alive (додаткова безпека)
@app.route('/keepalive')
def keep_alive():
    """Keep-alive endpoint."""
    return jsonify({
        "message": "Bot is alive!",
        "timestamp": time.time(),
        "uptime": int(time.time() - bot_start_time)
    })

def run_flask():
    """Запуск Flask сервера."""
    app.run(
        host='0.0.0.0', 
        port=config.WEBHOOK_PORT, 
        debug=False,
        threaded=True  # Дозволяє обробляти кілька запитів одночасно
    )

# Main execution
if __name__ == "__main__":
    try:
        # Initialize database
        init_database()
        logger.info("Database initialized successfully")
        
        # Start Flask in separate thread
        flask_thread = Thread(target=run_flask, daemon=True)
        flask_thread.start()
        logger.info(f"Flask server started on port {config.WEBHOOK_PORT}")
        logger.info("Health check endpoints available:")
        logger.info(f"  - Main: http://localhost:{config.WEBHOOK_PORT}/")
        logger.info(f"  - Health: http://localhost:{config.WEBHOOK_PORT}/health")
        logger.info(f"  - Ping: http://localhost:{config.WEBHOOK_PORT}/ping")
        logger.info(f"  - Status: http://localhost:{config.WEBHOOK_PORT}/status")
        
        # Start bot
        logger.info("🎵 Music Studio Bot started successfully!")
        logger.info(f"Admin ID: {config.ADMIN_ID}")
        logger.info("Bot is polling for messages...")
        
        bot.polling(none_stop=True, interval=1, timeout=30)
        
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.critical(f"Critical error: {e}")
        exit(1)
