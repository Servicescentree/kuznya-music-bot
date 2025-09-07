"""
Kuznya Music Studio Telegram Bot - Realtime Chat System
Система реальних діалогів для музичної студії
"""

import os
import time
import html
import logging
import sqlite3
from threading import Thread
from typing import Optional, Dict, Any
from dataclasses import dataclass
from datetime import datetime

import telebot
from telebot import types
from flask import Flask, jsonify

# Configuration
@dataclass
class BotConfig:
    TOKEN: str = os.getenv('BOT_TOKEN', '8368212048:AAFPu81rvI7ISpmtixdgD1cOybAQ6T_rMjI')
    ADMIN_ID: int = int(os.getenv('ADMIN_ID', '7276479457'))
    CHANNEL_URL: str = 'https://t.me/kuznya_music'
    EXAMPLES_URL: str = 'https://t.me/kuznya_music/41'
    WEBHOOK_PORT: int = int(os.getenv('PORT', 8080))
    MAX_MESSAGE_LENGTH: int = 4000
    RATE_LIMIT_MESSAGES: int = 10  # збільшено для діалогів

# Text messages
class Messages:
    WELCOME = """Привіт, {}! 🎵
Ласкаво просимо до музичної студії Kuznya Music!

Ваші можливості:
• 💬 Почати діалог з адміністратором
• 🎧 Переглянути наші роботи  
• 📢 Підписатися на канал"""

    DIALOG_STARTED = """✅ Діалог розпочато!

💬 Тепер ви можете спілкуватися з адміністратором в реальному часі.
Опишіть ваші побажання щодо:
• Запису треку
• Зведення 
• Аранжування
• Термінів

Адміністратор бачить ваші повідомлення миттєво!"""

    DIALOG_ENDED = """✅ Діалог завершено

Дякуємо за звернення! Ви можете розпочати новий діалог в будь-який час.

Не забудьте підписатися на наш канал для отримання новин студії!"""

    ADMIN_NEW_DIALOG = """🎵 Новий діалог з клієнтом!

👤 Клієнт: {full_name}
🆔 ID: {user_id}
📧 Username: @{username}
⏰ Час: {time}

Використовуйте "💬 Активні діалоги" для входу в діалог."""

    ADMIN_DIALOG_ENDED = """❌ Діалог завершено клієнтом

👤 {full_name} (@{username})"""

    ADMIN_PANEL = """👨‍💼 Панель адміністратора Kuznya Music

🎵 Активних діалогів: {active_dialogs}
👥 Всього клієнтів: {total_users}
📊 Повідомлень за сьогодні: {today_messages}

Використовуйте меню для управління:"""

    RETURN_TO_DIALOG = """💬 Ви повернулись до діалогу з адміністратором!

Продовжуйте спілкування - адміністратор бачить ваші повідомлення."""

# User states
class UserStates:
    IDLE = 'idle'
    IN_DIALOG = 'in_dialog'

class AdminStates:
    IDLE = 'admin_idle'
    IN_DIALOG = 'admin_in_dialog'
    BROADCASTING = 'broadcasting'

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
    bot_info = bot.get_me()
    logger.info(f"Bot token is valid! Bot name: {bot_info.first_name} (@{bot_info.username})")
except Exception as token_error:
    logger.error(f"Invalid bot token: {token_error}")
    exit(1)

# Database setup for chat system
def init_database():
    """Initialize database with tables for realtime chat system."""
    conn = sqlite3.connect('kuznya_music.db')
    cursor = conn.cursor()
    
    # Users table
    cursor.execute('''
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
    
    # Messages table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dialog_id INTEGER,
            user_id INTEGER NOT NULL,
            username TEXT,
            full_name TEXT,
            message_text TEXT,
            message_type TEXT DEFAULT 'text',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_from_admin BOOLEAN DEFAULT 0
        )
    ''')
    
    # Dialogs table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS dialogs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            admin_id INTEGER NOT NULL,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ended_at TIMESTAMP DEFAULT NULL,
            is_active BOOLEAN DEFAULT 1,
            total_messages INTEGER DEFAULT 0
        )
    ''')
    
    conn.commit()
    conn.close()
    logger.info("Database initialized successfully")

# In-memory storage for states
user_states = {}  # user_id: state
admin_current_dialog = {}  # admin_id: user_id
rate_limits = {}  # user_id: {'count': int, 'last_reset': timestamp}

# Database helper functions
class DatabaseManager:
    @staticmethod
    def save_user(user_id: int, username: str, full_name: str):
        """Save or update user in database."""
        conn = sqlite3.connect('kuznya_music.db')
        cursor = conn.cursor()
        
        cursor.execute('SELECT total_messages FROM users WHERE user_id = ?', (user_id,))
        existing = cursor.fetchone()
        
        if existing:
            cursor.execute('''
                UPDATE users 
                SET username = ?, full_name = ?, last_activity = ?, total_messages = total_messages + 1
                WHERE user_id = ?
            ''', (username, full_name, datetime.now(), user_id))
        else:
            cursor.execute('''
                INSERT INTO users 
                (user_id, username, full_name, last_activity, total_messages, in_dialog, dialog_with)
                VALUES (?, ?, ?, ?, 1, 0, NULL)
            ''', (user_id, username, full_name, datetime.now()))
        
        conn.commit()
        conn.close()
    
    @staticmethod
    def start_dialog(user_id: int, admin_id: int) -> int:
        """Start new dialog between user and admin."""
        conn = sqlite3.connect('kuznya_music.db')
        cursor = conn.cursor()
        
        # Check for existing active dialog
        cursor.execute('SELECT id FROM dialogs WHERE user_id = ? AND is_active = 1', (user_id,))
        existing = cursor.fetchone()
        
        if existing:
            conn.close()
            return existing[0]
        
        # Create new dialog
        cursor.execute('''
            INSERT INTO dialogs (user_id, admin_id) VALUES (?, ?)
        ''', (user_id, admin_id))
        
        dialog_id = cursor.lastrowid
        
        # Update user status
        cursor.execute('''
            UPDATE users SET in_dialog = 1, dialog_with = ? WHERE user_id = ?
        ''', (admin_id, user_id))
        
        conn.commit()
        conn.close()
        
        return dialog_id
    
    @staticmethod
    def end_dialog(user_id: int):
        """End active dialog for user."""
        conn = sqlite3.connect('kuznya_music.db')
        cursor = conn.cursor()
        
        # End dialog
        cursor.execute('''
            UPDATE dialogs 
            SET is_active = 0, ended_at = ?, 
                total_messages = (SELECT COUNT(*) FROM messages WHERE dialog_id = dialogs.id)
            WHERE user_id = ? AND is_active = 1
        ''', (datetime.now(), user_id))
        
        # Update user status
        cursor.execute('''
            UPDATE users SET in_dialog = 0, dialog_with = NULL WHERE user_id = ?
        ''', (user_id,))
        
        conn.commit()
        conn.close()
    
    @staticmethod
    def get_active_dialog(user_id: int) -> Optional[tuple]:
        """Get active dialog for user."""
        conn = sqlite3.connect('kuznya_music.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id, admin_id FROM dialogs 
            WHERE user_id = ? AND is_active = 1
        ''', (user_id,))
        
        result = cursor.fetchone()
        conn.close()
        
        return result
    
    @staticmethod
    def save_message(user_id: int, username: str, full_name: str, message_text: str, 
                    dialog_id: int, is_from_admin: bool = False, message_type: str = 'text') -> int:
        """Save message to database."""
        conn = sqlite3.connect('kuznya_music.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO messages (dialog_id, user_id, username, full_name, message_text, message_type, is_from_admin)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (dialog_id, user_id, username, full_name, message_text, message_type, is_from_admin))
        
        message_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return message_id
    
    @staticmethod
    def get_admin_active_dialogs(admin_id: int) -> list:
        """Get all active dialogs for admin."""
        conn = sqlite3.connect('kuznya_music.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT d.id, d.user_id, u.username, u.full_name, d.started_at,
                   COUNT(m.id) as msg_count
            FROM dialogs d
            JOIN users u ON d.user_id = u.user_id
            LEFT JOIN messages m ON d.id = m.dialog_id
            WHERE d.is_active = 1 AND d.admin_id = ?
            GROUP BY d.id, d.user_id, u.username, u.full_name, d.started_at
            ORDER BY d.started_at DESC
        ''', (admin_id,))
        
        dialogs = cursor.fetchall()
        conn.close()
        
        return dialogs
    
    @staticmethod
    def get_statistics(admin_id: int) -> dict:
        """Get bot statistics."""
        conn = sqlite3.connect('kuznya_music.db')
        cursor = conn.cursor()
        
        # Total users (excluding admin)
        cursor.execute('SELECT COUNT(*) FROM users WHERE user_id != ?', (admin_id,))
        total_users = cursor.fetchone()[0]
        
        # Active dialogs
        cursor.execute('SELECT COUNT(*) FROM dialogs WHERE is_active = 1 AND admin_id = ?', (admin_id,))
        active_dialogs = cursor.fetchone()[0]
        
        # Today's messages
        today = datetime.now().strftime('%Y-%m-%d')
        cursor.execute("SELECT COUNT(*) FROM messages WHERE DATE(created_at) = ?", (today,))
        today_messages = cursor.fetchone()[0]
        
        # Total messages
        cursor.execute("SELECT COUNT(*) FROM messages")
        total_messages = cursor.fetchone()[0]
        
        conn.close()
        
        return {
            'total_users': total_users,
            'active_dialogs': active_dialogs,
            'today_messages': today_messages,
            'total_messages': total_messages
        }

# Helper functions
def is_admin(user_id: int) -> bool:
    """Check if user is admin."""
    return user_id == config.ADMIN_ID

def get_user_info(user) -> Dict[str, Any]:
    """Get formatted user information."""
    return {
        'id': user.id,
        'username': user.username or "немає",
        'first_name': user.first_name or "Невідомо",
        'last_name': user.last_name or "",
        'full_name': f"{user.first_name or ''} {user.last_name or ''}".strip()
    }

def check_rate_limit(user_id: int) -> bool:
    """Check if user exceeds rate limit."""
    current_time = int(time.time())
    
    if user_id not in rate_limits:
        rate_limits[user_id] = {'count': 1, 'last_reset': current_time}
        return True
    
    user_limit = rate_limits[user_id]
    
    # Reset counter if more than 1 minute passed
    if current_time - user_limit['last_reset'] > 60:
        rate_limits[user_id] = {'count': 1, 'last_reset': current_time}
        return True
    
    # Check if under limit
    if user_limit['count'] < config.RATE_LIMIT_MESSAGES:
        user_limit['count'] += 1
        return True
    
    return False

# Keyboards
def get_main_keyboard():
    """Main menu keyboard for users."""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton("💬 Почати діалог"),
        types.KeyboardButton("🎧 Наші роботи")
    )
    markup.add(
        types.KeyboardButton("📢 Підписатися"),
        types.KeyboardButton("📲 Контакти")
    )
    return markup

def get_dialog_keyboard():
    """Dialog keyboard for users."""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    markup.add(types.KeyboardButton("❌ Завершити діалог"))
    return markup

def get_admin_keyboard():
    """Admin main keyboard."""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton("💬 Активні діалоги"),
        types.KeyboardButton("📊 Статистика")
    )
    markup.add(
        types.KeyboardButton("👥 Всі користувачі"),
        types.KeyboardButton("📢 Розсилка")
    )
    return markup

def get_admin_dialog_keyboard():
    """Admin dialog keyboard."""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton("❌ Завершити діалог"),
        types.KeyboardButton("🔄 Інший діалог")
    )
    markup.add(types.KeyboardButton("🏠 Головне меню"))
    return markup

# Message handlers
@bot.message_handler(commands=['start'])
def handle_start(message):
    """Handle /start command."""
    try:
        user = message.from_user
        user_info = get_user_info(user)
        DatabaseManager.save_user(user.id, user_info['username'], user_info['full_name'])
        
        if is_admin(user.id):
            # Admin start
            stats = DatabaseManager.get_statistics(config.ADMIN_ID)
            admin_text = Messages.ADMIN_PANEL.format(
                active_dialogs=stats['active_dialogs'],
                total_users=stats['total_users'],
                today_messages=stats['today_messages']
            )
            
            markup = get_admin_keyboard()
            bot.send_message(
                message.chat.id,
                admin_text,
                reply_markup=markup
            )
            
            user_states[user.id] = AdminStates.IDLE
        else:
            # Regular user start
            # Check if user has active dialog
            dialog = DatabaseManager.get_active_dialog(user.id)
            if dialog:
                user_states[user.id] = UserStates.IN_DIALOG
                markup = get_dialog_keyboard()
                bot.send_message(
                    message.chat.id,
                    Messages.RETURN_TO_DIALOG,
                    reply_markup=markup
                )
            else:
                user_states[user.id] = UserStates.IDLE
                markup = get_main_keyboard()
                bot.send_message(
                    message.chat.id,
                    Messages.WELCOME.format(user_info['first_name']),
                    reply_markup=markup
                )
        
        logger.info(f"User {user.id} started bot")
        
    except Exception as e:
        logger.error(f"Error in handle_start: {e}")
        bot.send_message(message.chat.id, "❌ Помилка при запуску. Спробуйте ще раз.")

# User dialog handlers
@bot.message_handler(func=lambda message: message.text == "💬 Почати діалог" and not is_admin(message.from_user.id))
def handle_start_dialog(message):
    """Start dialog with admin."""
    try:
        user = message.from_user
        user_info = get_user_info(user)
        
        # Check if already in dialog
        dialog = DatabaseManager.get_active_dialog(user.id)
        if dialog:
            user_states[user.id] = UserStates.IN_DIALOG
            bot.send_message(
                message.chat.id,
                Messages.RETURN_TO_DIALOG,
                reply_markup=get_dialog_keyboard()
            )
            return
        
        # Create new dialog
        dialog_id = DatabaseManager.start_dialog(user.id, config.ADMIN_ID)
        user_states[user.id] = UserStates.IN_DIALOG
        
        # Send confirmation to user
        bot.send_message(
            message.chat.id,
            Messages.DIALOG_STARTED,
            reply_markup=get_dialog_keyboard()
        )
        
        # Notify admin about new dialog
        admin_text = Messages.ADMIN_NEW_DIALOG.format(
            full_name=user_info['full_name'],
            user_id=user.id,
            username=user_info['username'],
            time=datetime.now().strftime('%H:%M %d.%m.%Y')
        )
        
        try:
            bot.send_message(config.ADMIN_ID, admin_text)
        except Exception as e:
            logger.error(f"Failed to notify admin: {e}")
        
        logger.info(f"Dialog started: User {user.id} with Admin {config.ADMIN_ID}")
        
    except Exception as e:
        logger.error(f"Error starting dialog: {e}")
        bot.send_message(message.chat.id, "❌ Помилка при створенні діалогу.")

@bot.message_handler(func=lambda message: message.text == "❌ Завершити діалог")
def handle_end_dialog(message):
    """End current dialog."""
    try:
        user_id = message.from_user.id
        
        if is_admin(user_id):
            # Admin ending dialog
            if user_id in admin_current_dialog:
                dialog_user_id = admin_current_dialog[user_id]
                DatabaseManager.end_dialog(dialog_user_id)
                
                # Clear admin state
                del admin_current_dialog[user_id]
                user_states[user_id] = AdminStates.IDLE
                
                # Notify user
                try:
                    bot.send_message(
                        dialog_user_id,
                        "✅ Діалог завершено адміністратором\n\nДякуємо за звернення!",
                        reply_markup=get_main_keyboard()
                    )
                    user_states[dialog_user_id] = UserStates.IDLE
                except Exception as e:
                    logger.error(f"Failed to notify user about dialog end: {e}")
                
                bot.send_message(
                    message.chat.id,
                    "✅ Діалог завершено",
                    reply_markup=get_admin_keyboard()
                )
            else:
                bot.send_message(
                    message.chat.id,
                    "❌ Ви не в діалозі",
                    reply_markup=get_admin_keyboard()
                )
        else:
            # User ending dialog
            dialog = DatabaseManager.get_active_dialog(user_id)
            if not dialog:
                bot.send_message(
                    message.chat.id,
                    "❌ Ви не в діалозі",
                    reply_markup=get_main_keyboard()
                )
                return
            
            DatabaseManager.end_dialog(user_id)
            user_states[user_id] = UserStates.IDLE
            
            bot.send_message(
                message.chat.id,
                Messages.DIALOG_ENDED,
                reply_markup=get_main_keyboard()
            )
            
            # Notify admin
            try:
                user_info = get_user_info(message.from_user)
                admin_text = Messages.ADMIN_DIALOG_ENDED.format(
                    full_name=user_info['full_name'],
                    username=user_info['username']
                )
                bot.send_message(config.ADMIN_ID, admin_text)
                
                # Clear admin state if they were in this dialog
                if config.ADMIN_ID in admin_current_dialog and admin_current_dialog[config.ADMIN_ID] == user_id:
                    del admin_current_dialog[config.ADMIN_ID]
                    user_states[config.ADMIN_ID] = AdminStates.IDLE
                    
            except Exception as e:
                logger.error(f"Failed to notify admin: {e}")
        
        logger.info(f"Dialog ended by user {user_id}")
        
    except Exception as e:
        logger.error(f"Error ending dialog: {e}")
        bot.send_message(message.chat.id, "❌ Помилка при завершенні діалогу.")

# Admin handlers
@bot.message_handler(func=lambda message: message.text == "💬 Активні діалоги" and is_admin(message.from_user.id))
def handle_admin_active_dialogs(message):
    """Show active dialogs for admin."""
    try:
        dialogs = DatabaseManager.get_admin_active_dialogs(config.ADMIN_ID)
        
        if not dialogs:
            bot.send_message(
                message.chat.id,
                "💬 Активні діалоги\n\nНа даний момент немає активних діалогів з клієнтами."
            )
            return
        
        response = f"💬 Ваші активні діалоги ({len(dialogs)}):\n\n"
        markup = types.InlineKeyboardMarkup()
        
        for dialog_id, user_id, username, full_name, started_at, msg_count in dialogs:
            started = datetime.fromisoformat(started_at).strftime('%H:%M %d.%m')
            
            response += f"🎵 {full_name}\n"
            response += f"📧 @{username} | 💬 {msg_count} повідомлень\n"
            response += f"📅 Почато: {started}\n\n"
            
            # Button to enter dialog
            markup.add(types.InlineKeyboardButton(
                f"💬 {full_name[:20]}{'...' if len(full_name) > 20 else ''}",
                callback_data=f"enter_dialog_{user_id}"
            ))
        
        bot.send_message(
            message.chat.id,
            response,
            reply_markup=markup
        )
        
    except Exception as e:
        logger.error(f"Error showing active dialogs: {e}")
        bot.send_message(message.chat.id, "❌ Помилка при завантаженні діалогів.")

@bot.callback_query_handler(func=lambda call: call.data.startswith('enter_dialog_'))
def handle_enter_dialog(call):
    """Admin enters dialog with user."""
    try:
        if not is_admin(call.from_user.id):
            bot.answer_callback_query(call.id, "❌ Немає доступу")
            return
        
        user_id = int(call.data.split('_')[2])
        dialog = DatabaseManager.get_active_dialog(user_id)
        
        if not dialog:
            bot.answer_callback_query(call.id, "❌ Діалог не активний")
            return
        
        # Set admin state
        admin_current_dialog[config.ADMIN_ID] = user_id
        user_states[config.ADMIN_ID] = AdminStates.IN_DIALOG
        
        # Get user info
        conn = sqlite3.connect('kuznya_music.db')
        cursor = conn.cursor()
        cursor.execute('SELECT username, full_name FROM users WHERE user_id = ?', (user_id,))
        user_data = cursor.fetchone()
        conn.close()
        
        if user_data:
            username, full_name = user_data
            
            bot.edit_message_text(
                f"💬 Діалог з {full_name}\n\nПишіть повідомлення - клієнт їх бачить миттєво!",
                call.message.chat.id,
                call.message.message_id
            )
            
            bot.send_message(
                call.message.chat.id,
                "Ви увійшли в діалог. Використовуйте кнопки для управління:",
                reply_markup=get_admin_dialog_keyboard()
            )
        
        bot.answer_callback_query(call.id, "✅ Увійшли в діалог")
        
    except Exception as e:
        logger.error(f"Error entering dialog: {e}")
        bot.answer_callback_query(call.id, "❌ Помилка")

# Dialog message handlers
@bot.message_handler(func=lambda message: user_states.get(message.from_user.id) == UserStates.IN_DIALOG)
def handle_user_dialog_message(message):
    """Handle messages from user in dialog."""
    if message.text == "❌ Завершити діалог":
        return  # Handled by specific handler
    
    try:
        user = message.from_user
        user_info = get_user_info(user)
        
        # Check rate limit
        if not check_rate_limit(user.id):
            bot.send_message(message.chat.id, "⏱ Занадто швидко! Зачекайте хвилинку.")
            return
        
        dialog = DatabaseManager.get_active_dialog(user.id)
        if not dialog:
            user_states[user.id] = UserStates.IDLE
            bot.send_message(
                message.chat.id,
                "❌ Діалог не активний. Повертаємось до головного меню.",
                reply_markup=get_main_keyboard()
            )
            return
        
        dialog_id, admin_id = dialog
        message_text = message.text or message.caption or "[Медіа файл]"
        
        # Save message
        DatabaseManager.save_message(
            user.id, user_info['username'], user_info['full_name'],
            message_text, dialog_id, False, message.content_type
        )
        
        # Send to admin
        admin_text = f"💬 {user_info['full_name']}: {message_text}"
        
        try:
            bot.send_message(admin_id, admin_text)
            
            # Forward media if not text
            if message.content_type != 'text':
                bot.forward_message(admin_id, message.chat.id, message.message_id)
                
        except Exception as e:
            logger.error(f"Failed to send message to admin: {e}")
        
        logger.info(f"Message from user {user.id} forwarded to admin")
        
    except Exception as e:
        logger.error(f"Error handling user dialog message: {e}")

@bot.message_handler(func=lambda message: user_states.get(message.from_user.id) == AdminStates.IN_DIALOG and is_admin(message.from_user.id))
def handle_admin_dialog_message(message):
    """Handle messages from admin in dialog."""
    if message.text in ["❌ Завершити діалог", "🔄 Інший діалог", "🏠 Головне меню"]:
        return  # Handled by specific handlers
    
    try:
        admin_id = message.from_user.id
        user_id = admin_current_dialog.get(admin_id)
        
        if not user_id:
            bot.send_message(
                message.chat.id,
                "❌ Помилка: дані діалогу втрачено",
                reply_markup=get_admin_keyboard()
            )
            user_states[admin_id] = AdminStates.IDLE
            return
        
        dialog = DatabaseManager.get_active_dialog(user_id)
        if not dialog:
            bot.send_message(message.chat.id, "❌ Діалог не активний")
            return
        
        dialog_id = dialog[0]
        message_text = message.text or message.caption or "[Медіа файл]"
        
        # Save admin message
        DatabaseManager.save_message(
            user_id, "admin", "Адміністратор",
            message_text, dialog_id, True, message.content_type
        )
        
        # Send to user
        user_text = f"👨‍💼 Адмін: {message_text}"
        
        try:
            bot.send_message(user_id, user_text)
            
            # Forward media if not text
            if message.content_type != 'text':
                bot.forward_message(user_id, message.chat.id, message.message_id)
                
        except Exception as e:
            bot.send_message(message.chat.id, f"❌ Не вдалося надіслати користувачу: {e}")
            logger.error(f"Failed to send to user: {e}")
        
        logger.info(f"Admin message sent to user {user_id}")
        
    except Exception as e:
        logger.error(f"Error handling admin dialog message: {e}")

# Other admin handlers
@bot.message_handler(func=lambda message: message.text == "🔄 Інший діалог" and is_admin(message.from_user.id))
def handle_switch_dialog(message):
    """Switch to another dialog."""
    user_states[message.from_user.id] = AdminStates.IDLE
    if config.ADMIN_ID in admin_current_dialog:
        del admin_current_dialog[config.ADMIN_ID]
    handle_admin_active_dialogs(message)

@bot.message_handler(func=lambda message: message.text == "🏠 Головне меню" and is_admin(message.from_user.id))
def handle_admin_main_menu(message):
    """Return to admin main menu."""
    user_states[message.from_user.id] = AdminStates.IDLE
    if config.ADMIN_ID in admin_current_dialog:
        del admin_current_dialog[config.ADMIN_ID]
    
    bot.send_message(
        message.chat.id,
        "🏠 Головне меню адміністратора",
        reply_markup=get_admin_keyboard()
    )

@bot.message_handler(func=lambda message: message.text == "📊 Статистика" and is_admin(message.from_user.id))
def handle_statistics(message):
    """Show bot statistics."""
    try:
        stats = DatabaseManager.get_statistics(config.ADMIN_ID)
        
        response = f"""📊 Статистика Kuznya Music Bot

👥 Всього клієнтів: {stats['total_users']}
💬 Активних діалогів: {stats['active_dialogs']}
📨 Повідомлень за сьогодні: {stats['today_messages']}
📝 Всього повідомлень: {stats['total_messages']}

📅 Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}
🎵 Студія: Kuznya Music"""
        
        bot.send_message(message.chat.id, response)
        
    except Exception as e:
        logger.error(f"Error showing statistics: {e}")
        bot.send_message(message.chat.id, "❌ Помилка при завантаженні статистики.")

@bot.message_handler(func=lambda message: message.text == "👥 Всі користувачі" and is_admin(message.from_user.id))
def handle_all_users(message):
    """Show all users."""
    try:
        conn = sqlite3.connect('kuznya_music.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT user_id, username, full_name, total_messages, last_activity, in_dialog
            FROM users
            WHERE user_id != ?
            ORDER BY in_dialog DESC, last_activity DESC
            LIMIT 20
        ''', (config.ADMIN_ID,))
        
        users = cursor.fetchall()
        conn.close()
        
        if not users:
            bot.send_message(message.chat.id, "👥 Користувачів ще немає")
            return
        
        response = f"👥 Клієнти студії ({len(users)}):\n\n"
        
        for user_id, username, full_name, total_msg, last_activity, in_dialog in users:
            status = "🟢 В діалозі" if in_dialog else "⚪ Вільний"
            last_active = datetime.fromisoformat(last_activity).strftime('%d.%m %H:%M')
            
            response += f"🎵 {full_name} {status}\n"
            response += f"📧 @{username} | 💬 {total_msg} повідомлень\n"
            response += f"⏰ {last_active}\n\n"
        
        bot.send_message(message.chat.id, response)
        
    except Exception as e:
        logger.error(f"Error showing users: {e}")
        bot.send_message(message.chat.id, "❌ Помилка при завантаженні користувачів.")

# User menu handlers  
@bot.message_handler(func=lambda message: message.text == "🎧 Наші роботи")
def handle_show_examples(message):
    """Show examples of work."""
    try:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(
            "🎧 Послухати приклади",
            url=config.EXAMPLES_URL
        ))
        
        bot.send_message(
            message.chat.id,
            "🎵 Наші роботи:\n\nПриклади: Аранжування 🎹 | Зведення 🎧 | Мастеринг 🔊\n\nПослухайте і оцініть якість нашої роботи!",
            reply_markup=markup
        )
        
    except Exception as e:
        logger.error(f"Error in handle_show_examples: {e}")
        bot.send_message(message.chat.id, "❌ Помилка завантаження.")

@bot.message_handler(func=lambda message: message.text == "📢 Підписатися")
def handle_show_channel(message):
    """Show channel information."""
    try:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(
            "📢 Підписатися на канал",
            url=config.CHANNEL_URL
        ))
        
        bot.send_message(
            message.chat.id,
            f"📢 Підписуйтесь на наш канал!\n\n{config.CHANNEL_URL}\n\nТам ви знайдете:\n• Нові роботи студії\n• Закулісся запису\n• Акції та знижки\n• Корисні поради",
            reply_markup=markup
        )
        
    except Exception as e:
        logger.error(f"Error in handle_show_channel: {e}")
        bot.send_message(message.chat.id, "❌ Помилка завантаження.")

@bot.message_handler(func=lambda message: message.text == "📲 Контакти")
def handle_show_contacts(message):
    """Show contact information."""
    try:
        bot.send_message(
            message.chat.id,
            "📲 Контакти Kuznya Music Studio\n\n🤖 Для зв'язку використовуйте цього бота\n💬 Натисніть 'Почати діалог' для спілкування з адміністратором\n\n📍 Telegram: @kuznya_music\n⏰ Адміністратор зазвичай онлайн і відповідає швидко"
        )
        
    except Exception as e:
        logger.error(f"Error in handle_show_contacts: {e}")
        bot.send_message(message.chat.id, "❌ Помилка завантаження.")

# Broadcast handler
@bot.message_handler(func=lambda message: message.text == "📢 Розсилка" and is_admin(message.from_user.id))
def handle_broadcast(message):
    """Start broadcast message."""
    user_states[message.from_user.id] = AdminStates.BROADCASTING
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("❌ Скасувати"))
    
    bot.send_message(
        message.chat.id,
        "📢 Розсилка повідомлення\n\nНапишіть текст для розсилки всім клієнтам студії:",
        reply_markup=markup
    )

@bot.message_handler(func=lambda message: user_states.get(message.from_user.id) == AdminStates.BROADCASTING and is_admin(message.from_user.id))
def handle_broadcast_message(message):
    """Process broadcast message."""
    if message.text == "❌ Скасувати":
        user_states[message.from_user.id] = AdminStates.IDLE
        bot.send_message(
            message.chat.id,
            "❌ Розсилка скасована",
            reply_markup=get_admin_keyboard()
        )
        return
    
    try:
        # Get all users
        conn = sqlite3.connect('kuznya_music.db')
        cursor = conn.cursor()
        cursor.execute('SELECT user_id, full_name FROM users WHERE user_id != ?', (config.ADMIN_ID,))
        users = cursor.fetchall()
        conn.close()
        
        if not users:
            bot.send_message(
                message.chat.id,
                "❌ Немає користувачів для розсилки",
                reply_markup=get_admin_keyboard()
            )
            user_states[message.from_user.id] = AdminStates.IDLE
            return
        
        bot.send_message(message.chat.id, "📡 Розпочинаю розсилку...")
        
        success_count = 0
        failed_count = 0
        
        broadcast_text = f"📢 Повідомлення від Kuznya Music Studio:\n\n{message.text}"
        
        for user_id, full_name in users:
            try:
                bot.send_message(user_id, broadcast_text)
                success_count += 1
            except Exception as e:
                failed_count += 1
                logger.error(f"Broadcast failed for user {user_id}: {e}")
        
        result_text = f"""📊 Розсилка завершена!

✅ Надіслано: {success_count}
❌ Помилки: {failed_count}
📋 Всього користувачів: {len(users)}

💬 Текст: {message.text}"""
        
        bot.send_message(
            message.chat.id,
            result_text,
            reply_markup=get_admin_keyboard()
        )
        
        user_states[message.from_user.id] = AdminStates.IDLE
        
    except Exception as e:
        logger.error(f"Broadcast error: {e}")
        bot.send_message(message.chat.id, "❌ Помилка розсилки")
        user_states[message.from_user.id] = AdminStates.IDLE

# Handle all other messages
@bot.message_handler(func=lambda message: True)
def handle_other_messages(message):
    """Handle all unprocessed messages."""
    try:
        user_id = message.from_user.id
        current_state = user_states.get(user_id, UserStates.IDLE)
        
        if is_admin(user_id):
            if current_state not in [AdminStates.IN_DIALOG, AdminStates.BROADCASTING]:
                bot.send_message(
                    message.chat.id,
                    "❓ Невідома команда. Використовуйте кнопки меню.",
                    reply_markup=get_admin_keyboard()
                )
        else:
            if current_state != UserStates.IN_DIALOG:
                bot.send_message(
                    message.chat.id,
                    "❓ Використовуйте кнопки меню або напишіть /start для початку роботи",
                    reply_markup=get_main_keyboard()
                )
    
    except Exception as e:
        logger.error(f"Error in handle_other_messages: {e}")

# Flask app for health monitoring
app = Flask(__name__)
bot_start_time = time.time()

@app.route('/')
def health_check():
    """Health check page."""
    uptime_seconds = int(time.time() - bot_start_time)
    uptime_hours = uptime_seconds // 3600
    uptime_minutes = (uptime_seconds % 3600) // 60
    
    try:
        stats = DatabaseManager.get_statistics(config.ADMIN_ID)
    except:
        stats = {'total_users': 0, 'active_dialogs': 0, 'today_messages': 0}
    
    return f"""
    <h1>🎵 Kuznya Music Studio Bot</h1>
    <p><strong>Статус:</strong> ✅ Активний</p>
    <p><strong>Система:</strong> Реальні діалоги</p>
    <p><strong>Uptime:</strong> {uptime_hours}год {uptime_minutes}хв</p>
    <p><strong>Клієнтів:</strong> {stats['total_users']}</p>
    <p><strong>Активних діалогів:</strong> {stats['active_dialogs']}</p>
    <p><strong>Повідомлень сьогодні:</strong> {stats['today_messages']}</p>
    """

@app.route('/health')
def health():
    """JSON health endpoint."""
    try:
        bot_info = bot.get_me()
        stats = DatabaseManager.get_statistics(config.ADMIN_ID)
        
        return jsonify({
            "status": "healthy",
            "bot_username": bot_info.username,
            "uptime_seconds": int(time.time() - bot_start_time),
            "total_users": stats['total_users'],
            "active_dialogs": stats['active_dialogs'],
            "today_messages": stats['today_messages'],
            "system": "realtime_dialogs",
            "version": "3.0"
        }), 200
        
    except Exception as e:
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500

def run_flask():
    """Run Flask server."""
    app.run(host='0.0.0.0', port=config.WEBHOOK_PORT, debug=False, threaded=True)

# Main execution
if __name__ == "__main__":
    try:
        # Initialize database
        init_database()
        
        logger.info("🎵 Starting Kuznya Music Studio Bot with Realtime Chat System...")
        logger.info(f"👨‍💼 Admin ID: {config.ADMIN_ID}")
        
        # Start Flask in separate thread
        flask_thread = Thread(target=run_flask, daemon=True)
        flask_thread.start()
        logger.info(f"📡 Health monitoring started on port {config.WEBHOOK_PORT}")
        
        # Clear any previous instances
        try:
            bot.remove_webhook()
            bot.stop_polling()
        except:
            pass
        
        time.sleep(2)
        
        logger.info("🚀 NEW FEATURES:")
        logger.info("💬 Real-time dialogs between clients and admin")
        logger.info("🔄 Admin can switch between multiple dialogs")
        logger.info("📊 Enhanced statistics and user management")
        logger.info("🎵 Optimized for music studio workflow")
        logger.info("✅ Bot started successfully! Press Ctrl+C to stop")
        
        # Start polling
        while True:
            try:
                bot.polling(none_stop=True, interval=1, timeout=30)
            except Exception as api_error:
                if "409" in str(api_error) or "Conflict" in str(api_error):
                    logger.warning("Conflict detected - retrying in 10 seconds...")
                    time.sleep(10)
                    continue
                else:
                    raise api_error
        
    except KeyboardInterrupt:
        logger.info("🛑 Bot stopped by user")
    except Exception as e:
        logger.critical(f"💥 Critical error: {e}")
        exit(1)
