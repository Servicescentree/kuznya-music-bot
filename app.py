"""
Kuznya Music Studio Telegram Bot - Enhanced Version
Added advanced dialog system, improved admin panel, and comprehensive user management
Compatible with Render deployment using in-memory storage
"""

import os
import time
import html
import logging
import requests
from threading import Thread
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass
from datetime import datetime

import telebot
from telebot import types
from flask import Flask, jsonify

# Configuration
@dataclass
class BotConfig:
    TOKEN: str = os.getenv('BOT_TOKEN', '8368212048:AAE-PzjFjHn540-F9HJPEL9p3A-T9enawnY')
    ADMIN_ID: int = int(os.getenv('ADMIN_ID', '7276479457'))
    CHANNEL_URL: str = 'https://t.me/kuznya_music'
    EXAMPLES_URL: str = 'https://t.me/kuznya_music/41'
    WEBHOOK_PORT: int = int(os.getenv('PORT', 8080))
    MAX_MESSAGE_LENGTH: int = 4000
    RATE_LIMIT_MESSAGES: int = 10
    SELF_PING_INTERVAL: int = 600  # 10 minutes

# Enhanced text messages
class Messages:
    # User messages
    WELCOME = """Привіт, {}! 👋
Ласкаво просимо до музичної студії Kuznya Music!

🎵 Тут ви можете:
▫️ Почати діалог з адміністратором
▫️ Переглянути наші роботи
▫️ Отримати швидку консультацію

Оберіть дію з меню:"""

    ABOUT_BOT = """ℹ️ **Про студію Kuznya Music**

🎤 **Наші послуги:**
• Запис вокалу та інструментів
• Зведення і мастерінг треків  
• Аранжування композицій
• Продакшн повного циклу

🎧 **Обладнання:**
• Професійні мікрофони та преампи
• Студійні монітори та акустика
• Сучасні DAW та плагіни

💬 **Зв'язок:**
Використовуйте кнопку "Почати діалог" для прямого спілкування з адміністратором!"""

    START_DIALOG = """💬 **Діалог розпочато!**

Тепер ви можете спілкуватися з адміністратором в реальному часі. 
Пишіть ваші запитання - адміністратор їх бачить миттєво!

_Для завершення діалогу використовуйте кнопку нижче_"""

    RETURN_TO_DIALOG = """💬 **Повертаємось до діалогу**

Ваш діалог з адміністратором все ще активний.
Продовжуйте спілкування!"""

    DIALOG_ENDED_USER = """✅ **Діалог завершено**

Дякуємо за спілкування! 
Ви можете розпочати новий діалог в будь-який час."""

    EXAMPLES_INFO = """🎵 **Наші роботи**

Тут ви можете послухати приклади наших робіт:
• Аранжування 🎹
• Зведення 🎧  
• Мастерінг 🔊

Натисніть кнопку нижче для переходу:"""

    CHANNEL_INFO = """📢 **Підписуйтесь на наш канал!**

{}

Там ви знайдете:
• Нові роботи та релізи
• Закулісся студійного процесу
• Акції та спеціальні пропозиції
• Корисні поради для музикантів"""

    CONTACTS_INFO = """📲 **Контакти студії**

🎵 **Kuznya Music Studio**

📧 **Telegram:** @kuznya_music
💬 **Бот:** Використовуйте кнопку "Почати діалог"

⏰ **Графік роботи:**
Пн-Пт: 10:00-20:00
Сб-Нд: 12:00-18:00

📍 **Адреса:** За адресою зверніться до адміністратора"""

    # Admin messages  
    ADMIN_WELCOME = """👨‍💼 **Адмін-панель Kuznya Music**

Вітаємо в системі управління ботом!

**Поточний стан:**
• Активних діалогів: {}
• Всього користувачів: {}
• Системний час: {}

Використовуйте кнопки для управління:"""

    NEW_DIALOG_NOTIFICATION = """🆕 **Новий діалог розпочато!**

👤 **Користувач:** {}
🆔 **ID:** `{}`
📧 **Username:** @{}
⏰ **Час:** {}

Користувач чекає на відповідь. Використовуйте "Активні діалоги" для входу в діалог."""

    DIALOG_ENDED_ADMIN = """❌ **Діалог завершено користувачем**

👤 **Користувач:** {} (@{})
🆔 **ID:** {}
⏰ **Час:** {}"""

    # Error messages
    ERROR_SEND_FAILED = "❌ Помилка при відправці повідомлення. Спробуйте пізніше."
    ERROR_MESSAGE_TOO_LONG = f"❌ Повідомлення занадто довге. Максимум {BotConfig.MAX_MESSAGE_LENGTH} символів."
    ERROR_RATE_LIMITED = "❌ Забагато повідомлень. Зачекайте хвилинку."
    ERROR_INVALID_INPUT = "❌ Некоректне повідомлення. Спробуйте ще раз."
    ERROR_NO_DIALOG = "❌ Ви не в діалозі. Використовуйте кнопку 'Почати діалог'."
    ERROR_DIALOG_EXISTS = "❌ Ви вже в діалозі. Завершіть поточний діалог для початку нового."

# User states
class UserStates:
    IDLE = 'idle'
    IN_DIALOG = 'in_dialog' 
    ADMIN_IN_DIALOG = 'admin_in_dialog'
    ADMIN_BROADCASTING = 'admin_broadcasting'
    ADMIN_SELECTING_USER = 'admin_selecting_user'

# Setup enhanced logging
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

# Initialize bot with enhanced error handling
try:
    bot = telebot.TeleBot(config.TOKEN)
    bot_info = bot.get_me()
    logger.info(f"✅ Bot initialized: {bot_info.first_name} (@{bot_info.username})")
except Exception as token_error:
    logger.error(f"❌ Invalid bot token: {token_error}")
    exit(1)

# Enhanced in-memory storage system
class EnhancedMemoryManager:
    def __init__(self):
        # User management
        self.users = {}  # user_id: {username, full_name, first_seen, last_activity, total_messages}
        self.user_states = {}  # user_id: state
        
        # Dialog system
        self.active_dialogs = {}  # user_id: {admin_id, started_at, message_count}
        self.admin_current_dialog = {}  # admin_id: user_id (current dialog)
        
        # Message history
        self.message_history = {}  # dialog_id: [{user_id, message, timestamp, is_admin}]
        
        # Rate limiting
        self.rate_limits = {}  # user_id: {count, last_reset}
        
        # Statistics
        self.stats = {
            'total_messages': 0,
            'total_dialogs': 0,
            'bot_start_time': time.time()
        }
    
    # User management methods
    def save_user(self, user_id: int, username: str, full_name: str):
        """Save or update user information."""
        current_time = time.time()
        
        if user_id in self.users:
            # Update existing user
            self.users[user_id].update({
                'username': username,
                'full_name': full_name,
                'last_activity': current_time,
                'total_messages': self.users[user_id].get('total_messages', 0) + 1
            })
        else:
            # Create new user
            self.users[user_id] = {
                'username': username,
                'full_name': full_name,
                'first_seen': current_time,
                'last_activity': current_time,
                'total_messages': 1
            }
        
        logger.info(f"👤 User saved: {full_name} ({user_id})")
    
    def get_user_info(self, user_id: int) -> Dict[str, Any]:
        """Get user information."""
        return self.users.get(user_id, {})
    
    def get_all_users(self) -> List[Tuple]:
        """Get all users as list of tuples."""
        users_list = []
        for user_id, info in self.users.items():
            if user_id != config.ADMIN_ID:  # Exclude admin
                users_list.append((
                    user_id,
                    info.get('username', ''),
                    info.get('full_name', ''),
                    info.get('total_messages', 0),
                    info.get('last_activity', 0),
                    self.is_user_in_dialog(user_id)
                ))
        return sorted(users_list, key=lambda x: x[4], reverse=True)  # Sort by last activity
    
    # State management methods
    def get_user_state(self, user_id: int) -> str:
        """Get user's current state."""
        return self.user_states.get(user_id, UserStates.IDLE)
    
    def set_user_state(self, user_id: int, state: str):
        """Set user's state."""
        self.user_states[user_id] = state
        logger.info(f"📝 User {user_id} state: {state}")
    
    def clear_user_state(self, user_id: int):
        """Clear user's state."""
        self.user_states.pop(user_id, None)
        logger.info(f"🗑️ Cleared state for user {user_id}")
    
    # Dialog management methods
    def start_dialog(self, user_id: int, admin_id: int) -> bool:
        """Start a new dialog."""
        if user_id in self.active_dialogs:
            return False  # Dialog already exists
        
        self.active_dialogs[user_id] = {
            'admin_id': admin_id,
            'started_at': time.time(),
            'message_count': 0
        }
        
        dialog_id = f"{user_id}_{admin_id}_{int(time.time())}"
        self.message_history[dialog_id] = []
        
        self.stats['total_dialogs'] += 1
        self.set_user_state(user_id, UserStates.IN_DIALOG)
        
        logger.info(f"💬 Dialog started: User {user_id} <-> Admin {admin_id}")
        return True
    
    def end_dialog(self, user_id: int):
        """End a dialog."""
        if user_id in self.active_dialogs:
            admin_id = self.active_dialogs[user_id]['admin_id']
            
            # Clear admin's current dialog if it's this user
            if self.admin_current_dialog.get(admin_id) == user_id:
                self.admin_current_dialog.pop(admin_id, None)
                self.clear_user_state(admin_id)
            
            self.active_dialogs.pop(user_id, None)
            self.clear_user_state(user_id)
            
            logger.info(f"❌ Dialog ended: User {user_id}")
    
    def is_user_in_dialog(self, user_id: int) -> bool:
        """Check if user is in dialog."""
        return user_id in self.active_dialogs
    
    def get_active_dialogs(self) -> List[Dict]:
        """Get all active dialogs."""
        dialogs = []
        for user_id, dialog_info in self.active_dialogs.items():
            user_info = self.get_user_info(user_id)
            dialogs.append({
                'user_id': user_id,
                'admin_id': dialog_info['admin_id'],
                'started_at': dialog_info['started_at'],
                'message_count': dialog_info['message_count'],
                'username': user_info.get('username', ''),
                'full_name': user_info.get('full_name', 'Unknown')
            })
        return sorted(dialogs, key=lambda x: x['started_at'], reverse=True)
    
    def get_user_dialog_info(self, user_id: int) -> Optional[Dict]:
        """Get dialog info for specific user."""
        return self.active_dialogs.get(user_id)
    
    def set_admin_current_dialog(self, admin_id: int, user_id: int):
        """Set admin's current dialog focus."""
        self.admin_current_dialog[admin_id] = user_id
        self.set_user_state(admin_id, UserStates.ADMIN_IN_DIALOG)
    
    def get_admin_current_dialog(self, admin_id: int) -> Optional[int]:
        """Get admin's current dialog user."""
        return self.admin_current_dialog.get(admin_id)
    
    # Message methods
    def save_message(self, user_id: int, message_text: str, is_admin: bool = False):
        """Save message to history."""
        self.stats['total_messages'] += 1
        
        # Update dialog message count
        if user_id in self.active_dialogs:
            self.active_dialogs[user_id]['message_count'] += 1
        
        logger.info(f"💬 Message saved: {'Admin' if is_admin else 'User'} {user_id}")
    
    # Rate limiting
    def check_rate_limit(self, user_id: int) -> bool:
        """Check if user exceeds rate limit."""
        current_time = int(time.time())
        
        if user_id not in self.rate_limits:
            self.rate_limits[user_id] = {'count': 1, 'last_reset': current_time}
            return True
        
        user_limit = self.rate_limits[user_id]
        
        if current_time - user_limit['last_reset'] > 60:
            self.rate_limits[user_id] = {'count': 1, 'last_reset': current_time}
            return True
        
        if user_limit['count'] < config.RATE_LIMIT_MESSAGES:
            user_limit['count'] += 1
            return True
        
        return False
    
    # Statistics
    def get_statistics(self) -> Dict[str, Any]:
        """Get comprehensive statistics."""
        return {
            'total_users': len(self.users),
            'active_dialogs': len(self.active_dialogs),
            'total_messages': self.stats['total_messages'],
            'total_dialogs': self.stats['total_dialogs'],
            'uptime_seconds': int(time.time() - self.stats['bot_start_time']),
            'users_in_dialog': len([u for u in self.users.keys() if self.is_user_in_dialog(u)])
        }

# Initialize memory manager
memory = EnhancedMemoryManager()

# Enhanced keyboard functions
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
    markup.add(types.KeyboardButton("ℹ️ Про студію"))
    return markup

def get_dialog_keyboard():
    """Dialog keyboard for users."""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    markup.add(types.KeyboardButton("❌ Завершити діалог"))
    return markup

def get_admin_main_keyboard():
    """Main admin panel keyboard."""
    stats = memory.get_statistics()
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    
    # First row - main functions
    markup.add(
        types.KeyboardButton(f"💬 Активні діалоги ({stats['active_dialogs']})"),
        types.KeyboardButton("🆕 Новий діалог")
    )
    
    # Second row - user management  
    markup.add(
        types.KeyboardButton(f"👥 Користувачі ({stats['total_users']})"),
        types.KeyboardButton("📊 Статистика")
    )
    
    # Third row - broadcasting
    markup.add(types.KeyboardButton("📢 Розсилка"))
    
    return markup

def get_admin_dialog_keyboard():
    """Dialog management keyboard for admin."""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton("❌ Завершити діалог"),
        types.KeyboardButton("🔄 Інший діалог")
    )
    markup.add(types.KeyboardButton("🏠 Головне меню"))
    return markup

def get_cancel_keyboard():
    """Cancel action keyboard."""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    markup.add(types.KeyboardButton("❌ Скасувати"))
    return markup

# Helper functions
def is_admin(user_id: int) -> bool:
    """Check if user is admin."""
    return user_id == config.ADMIN_ID

def get_user_info_from_message(message) -> Dict[str, Any]:
    """Extract user information from message."""
    user = message.from_user
    return {
        'id': user.id,
        'username': user.username or "None",
        'first_name': user.first_name or "Unknown",
        'last_name': user.last_name or "",
        'full_name': f"{user.first_name or ''} {user.last_name or ''}".strip() or "Unknown"
    }

def validate_message(message) -> tuple[bool, str]:
    """Validate user message."""
    if not message or not message.text:
        return False, Messages.ERROR_INVALID_INPUT
    
    if len(message.text) > config.MAX_MESSAGE_LENGTH:
        return False, Messages.ERROR_MESSAGE_TOO_LONG
    
    if not memory.check_rate_limit(message.from_user.id):
        return False, Messages.ERROR_RATE_LIMITED
    
    return True, ""

def format_time_duration(seconds: int) -> str:
    """Format duration in human readable format."""
    if seconds < 60:
        return f"{seconds}с"
    elif seconds < 3600:
        return f"{seconds // 60}хв {seconds % 60}с"
    else:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{hours}год {minutes}хв"

# === MESSAGE HANDLERS ===

@bot.message_handler(commands=['start'])
def handle_start(message):
    """Handle /start command with enhanced logic."""
    try:
        user_info = get_user_info_from_message(message)
        memory.save_user(user_info['id'], user_info['username'], user_info['full_name'])
        
        if is_admin(user_info['id']):
            # Admin start
            stats = memory.get_statistics()
            admin_text = Messages.ADMIN_WELCOME.format(
                stats['active_dialogs'],
                stats['total_users'], 
                time.strftime('%H:%M %d.%m.%Y')
            )
            
            memory.clear_user_state(user_info['id'])
            
            bot.send_message(
                message.chat.id,
                admin_text,
                parse_mode='Markdown',
                reply_markup=get_admin_main_keyboard()
            )
            logger.info(f"👨‍💼 Admin started: {user_info['full_name']}")
        else:
            # Regular user start
            if memory.is_user_in_dialog(user_info['id']):
                # User has active dialog
                memory.set_user_state(user_info['id'], UserStates.IN_DIALOG)
                bot.send_message(
                    message.chat.id,
                    Messages.RETURN_TO_DIALOG,
                    parse_mode='Markdown',
                    reply_markup=get_dialog_keyboard()
                )
            else:
                # New user or returning user without dialog
                memory.clear_user_state(user_info['id'])
                bot.send_message(
                    message.chat.id,
                    Messages.WELCOME.format(user_info['first_name']),
                    reply_markup=get_main_keyboard()
                )
            
            logger.info(f"👤 User started: {user_info['full_name']} ({user_info['id']})")
            
    except Exception as e:
        logger.error(f"Error in handle_start: {e}")
        bot.send_message(message.chat.id, Messages.ERROR_SEND_FAILED)

# User message handlers
@bot.message_handler(func=lambda message: message.text == "💬 Почати діалог" and not is_admin(message.from_user.id))
def handle_start_dialog(message):
    """Start dialog for regular user."""
    try:
        user_info = get_user_info_from_message(message)
        
        if memory.is_user_in_dialog(user_info['id']):
            bot.send_message(
                message.chat.id,
                Messages.ERROR_DIALOG_EXISTS,
                reply_markup=get_dialog_keyboard()
            )
            return
        
        # Start new dialog
        if memory.start_dialog(user_info['id'], config.ADMIN_ID):
            bot.send_message(
                message.chat.id,
                Messages.START_DIALOG,
                parse_mode='Markdown',
                reply_markup=get_dialog_keyboard()
            )
            
            # Notify admin
            admin_notification = Messages.NEW_DIALOG_NOTIFICATION.format(
                user_info['full_name'],
                user_info['id'],
                user_info['username'],
                time.strftime('%H:%M %d.%m.%Y')
            )
            
            try:
                bot.send_message(
                    config.ADMIN_ID,
                    admin_notification,
                    parse_mode='Markdown'
                )
            except Exception as e:
                logger.error(f"Failed to notify admin: {e}")
                
            logger.info(f"💬 Dialog started by user {user_info['id']}")
        else:
            bot.send_message(message.chat.id, Messages.ERROR_SEND_FAILED)
            
    except Exception as e:
        logger.error(f"Error starting dialog: {e}")
        bot.send_message(message.chat.id, Messages.ERROR_SEND_FAILED)

@bot.message_handler(func=lambda message: message.text == "❌ Завершити діалог" and not is_admin(message.from_user.id))
def handle_end_dialog_user(message):
    """End dialog for regular user."""
    try:
        user_info = get_user_info_from_message(message)
        
        if not memory.is_user_in_dialog(user_info['id']):
            bot.send_message(
                message.chat.id,
                Messages.ERROR_NO_DIALOG,
                reply_markup=get_main_keyboard()
            )
            return
        
        memory.end_dialog(user_info['id'])
        
        bot.send_message(
            message.chat.id,
            Messages.DIALOG_ENDED_USER,
            parse_mode='Markdown',
            reply_markup=get_main_keyboard()
        )
        
        # Notify admin
        admin_notification = Messages.DIALOG_ENDED_ADMIN.format(
            user_info['full_name'],
            user_info['username'],
            user_info['id'],
            time.strftime('%H:%M %d.%m.%Y')
        )
        
        try:
            bot.send_message(
                config.ADMIN_ID,
                admin_notification,
                parse_mode='Markdown'
            )
        except:
            pass
        
        logger.info(f"❌ Dialog ended by user {user_info['id']}")
        
    except Exception as e:
        logger.error(f"Error ending dialog: {e}")
        bot.send_message(message.chat.id, Messages.ERROR_SEND_FAILED)

@bot.message_handler(func=lambda message: message.text == "🎧 Наші роботи")
def handle_show_examples(message):
    """Show examples of work."""
    try:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(
            "🎧 Переглянути приклади",
            url=config.EXAMPLES_URL
        ))
        
        bot.send_message(
            message.chat.id,
            Messages.EXAMPLES_INFO,
            parse_mode='Markdown',
            reply_markup=markup
        )
        
    except Exception as e:
        logger.error(f"Error showing examples: {e}")
        bot.send_message(message.chat.id, Messages.ERROR_SEND_FAILED)

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
            Messages.CHANNEL_INFO.format(config.CHANNEL_URL),
            parse_mode='Markdown',
            reply_markup=markup,
            disable_web_page_preview=True
        )
        
    except Exception as e:
        logger.error(f"Error showing channel: {e}")
        bot.send_message(message.chat.id, Messages.ERROR_SEND_FAILED)

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
        logger.error(f"Error showing contacts: {e}")
        bot.send_message(message.chat.id, Messages.ERROR_SEND_FAILED)

@bot.message_handler(func=lambda message: message.text == "ℹ️ Про студію")
def handle_about_bot(message):
    """Show information about the studio."""
    try:
        bot.send_message(
            message.chat.id,
            Messages.ABOUT_BOT,
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"Error showing about: {e}")
        bot.send_message(message.chat.id, Messages.ERROR_SEND_FAILED)

# Handle dialog messages from users
@bot.message_handler(func=lambda message: memory.get_user_state(message.from_user.id) == UserStates.IN_DIALOG and not is_admin(message.from_user.id))
def handle_user_dialog_message(message):
    """Handle messages from users in dialog."""
    try:
        # Skip button texts
        if message.text in ["❌ Завершити діалог"]:
            return
            
        user_info = get_user_info_from_message(message)
        
        if not memory.is_user_in_dialog(user_info['id']):
            memory.clear_user_state(user_info['id'])
            bot.send_message(
                message.chat.id,
                Messages.ERROR_NO_DIALOG,
                reply_markup=get_main_keyboard()
            )
            return
        
        # Validate message
        is_valid, error_msg = validate_message(message)
        if not is_valid:
            bot.send_message(message.chat.id, error_msg)
            return
        
        # Save message
        memory.save_message(user_info['id'], message.text, False)
        
        # Forward to admin
        admin_text = f"💬 **{user_info['full_name']}** (ID: `{user_info['id']}`)\n\n{message.text}"
        
        try:
            bot.send_message(
                config.ADMIN_ID,
                admin_text,
                parse_mode='Markdown'
            )
            
            # Forward media if present
            if message.content_type != 'text':
                bot.forward_message(config.ADMIN_ID, message.chat.id, message.message_id)
                
        except Exception as e:
            logger.error(f"Failed to forward to admin: {e}")
        
        logger.info(f"💬 Message from user {user_info['id']} forwarded to admin")
        
    except Exception as e:
        logger.error(f"Error in user dialog message: {e}")
        bot.send_message(message.chat.id, Messages.ERROR_SEND_FAILED)

# === ADMIN MESSAGE HANDLERS ===

@bot.message_handler(func=lambda message: message.text.startswith("💬 Активні діалоги") and is_admin(message.from_user.id))
def handle_admin_active_dialogs(message):
    """Show active dialogs for admin."""
    try:
        dialogs = memory.get_active_dialogs()
        
        if not dialogs:
            bot.send_message(
                message.chat.id,
                "💬 **Активні діалоги**\n\nНемає активних діалогів.\nВикористовуйте 'Новий діалог' для створення.",
                parse_mode='Markdown'
            )
            return
        
        response = "💬 **Ваші активні діалоги:**\n\n"
        markup = types.InlineKeyboardMarkup()
        
        for dialog in dialogs:
            duration = format_time_duration(int(time.time() - dialog['started_at']))
            response += f"👤 **{dialog['full_name']}**\n"
            response += f"📧 @{dialog['username']} | 🆔 `{dialog['user_id']}`\n"
            response += f"⏰ Тривалість: {duration} | 💬 Повідомлень: {dialog['message_count']}\n\n"
            
            # Add inline button to enter dialog
            markup.add(types.InlineKeyboardButton(
                f"💬 {dialog['full_name'][:25]}",
                callback_data=f"enter_dialog_{dialog['user_id']}"
            ))
        
        bot.send_message(
            message.chat.id,
            response,
            parse_mode='Markdown',
            reply_markup=markup
        )
        
    except Exception as e:
        logger.error(f"Error showing active dialogs: {e}")
        bot.send_message(message.chat.id, Messages.ERROR_SEND_FAILED)

@bot.message_handler(func=lambda message: message.text == "🆕 Новий діалог" and is_admin(message.from_user.id))
def handle_admin_new_dialog(message):
    """Show users available for new dialog."""
    try:
        users = memory.get_all_users()
        
        if not users:
            bot.send_message(
                message.chat.id,
                "👥 Користувачів ще немає"
            )
            return
        
        # Filter users not in dialog
        free_users = [u for u in users if not u[5]]  # u[5] is in_dialog
        
        if not free_users:
            bot.send_message(
                message.chat.id,
                "🆕 **Новий діалог**\n\nВсі користувачі вже мають активні діалоги.\nВикористовуйте 'Активні діалоги' для перегляду.",
                parse_mode='Markdown'
            )
            return
        
        response = "🆕 **Почати новий діалог з:**\n\n"
        markup = types.InlineKeyboardMarkup()
        
        for user_id, username, full_name, total_msg, last_activity, in_dialog in free_users[:15]:
            last_active_time = datetime.fromtimestamp(last_activity).strftime("%d.%m %H:%M")
            
            response += f"👤 **{full_name}**\n"
            response += f"📧 @{username} | 💬 Повідомлень: {total_msg}\n"
            response += f"⏰ Активність: {last_active_time}\n\n"
            
            markup.add(types.InlineKeyboardButton(
                f"💬 {full_name[:25]}",
                callback_data=f"start_dialog_{user_id}"
            ))
        
        if len(free_users) > 15:
            response += f"... і ще {len(free_users) - 15} користувачів"
        
        bot.send_message(
            message.chat.id,
            response,
            parse_mode='Markdown',
            reply_markup=markup
        )
        
    except Exception as e:
        logger.error(f"Error showing new dialog options: {e}")
        bot.send_message(message.chat.id, Messages.ERROR_SEND_FAILED)

@bot.message_handler(func=lambda message: message.text.startswith("👥 Користувачі") and is_admin(message.from_user.id))
def handle_admin_users_list(message):
    """Show all users list for admin."""
    try:
        users = memory.get_all_users()
        
        if not users:
            bot.send_message(message.chat.id, "👥 Користувачів ще немає")
            return
        
        response = "👥 **Список всіх користувачів:**\n\n"
        
        for user_id, username, full_name, total_msg, last_activity, in_dialog in users[:20]:
            last_active_time = datetime.fromtimestamp(last_activity).strftime("%d.%m %H:%M")
            status = "🟢 В діалозі" if in_dialog else "⚪ Вільний"
            
            response += f"👤 **{full_name}** {status}\n"
            response += f"🆔 `{user_id}` | 📧 @{username}\n"
            response += f"📨 {total_msg} повідомлень | ⏰ {last_active_time}\n\n"
        
        if len(users) > 20:
            response += f"... і ще {len(users) - 20} користувачів"
        
        bot.send_message(
            message.chat.id,
            response,
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"Error showing users list: {e}")
        bot.send_message(message.chat.id, Messages.ERROR_SEND_FAILED)

@bot.message_handler(func=lambda message: message.text == "📊 Статистика" and is_admin(message.from_user.id))
def handle_admin_statistics(message):
    """Show detailed statistics for admin."""
    try:
        stats = memory.get_statistics()
        uptime = format_time_duration(stats['uptime_seconds'])
        
        response = f"""📊 **Статистика бота**

**👥 Користувачі:**
• Всього користувачів: {stats['total_users']}
• В діалозі зараз: {stats['users_in_dialog']}

**💬 Діалоги:**
• Активних діалогів: {stats['active_dialogs']}
• Всього діалогів: {stats['total_dialogs']}

**📨 Повідомлення:**
• Всього повідомлень: {stats['total_messages']}

**⏰ Система:**
• Час роботи: {uptime}
• Поточний час: {time.strftime('%H:%M %d.%m.%Y')}

**🔧 Технічні дані:**
• Зберігання: In-Memory (Render)
• Версія: Enhanced v2.0"""
        
        bot.send_message(
            message.chat.id,
            response,
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"Error showing statistics: {e}")
        bot.send_message(message.chat.id, Messages.ERROR_SEND_FAILED)

@bot.message_handler(func=lambda message: message.text == "📢 Розсилка" and is_admin(message.from_user.id))
def handle_admin_broadcast_start(message):
    """Start broadcast mode for admin."""
    try:
        memory.set_user_state(config.ADMIN_ID, UserStates.ADMIN_BROADCASTING)
        
        bot.send_message(
            message.chat.id,
            "📢 **Розсилка повідомлення**\n\nНапишіть текст для розсилки всім користувачам:",
            parse_mode='Markdown',
            reply_markup=get_cancel_keyboard()
        )
        
    except Exception as e:
        logger.error(f"Error starting broadcast: {e}")
        bot.send_message(message.chat.id, Messages.ERROR_SEND_FAILED)

# Admin dialog management handlers
@bot.message_handler(func=lambda message: message.text == "❌ Завершити діалог" and is_admin(message.from_user.id))
def handle_admin_end_dialog(message):
    """Admin ends current dialog."""
    try:
        current_user_id = memory.get_admin_current_dialog(config.ADMIN_ID)
        
        if not current_user_id:
            bot.send_message(
                message.chat.id,
                "❌ Ви не в діалозі",
                reply_markup=get_admin_main_keyboard()
            )
            return
        
        user_info = memory.get_user_info(current_user_id)
        memory.end_dialog(current_user_id)
        
        bot.send_message(
            message.chat.id,
            f"✅ Діалог з {user_info.get('full_name', 'користувачем')} завершено",
            reply_markup=get_admin_main_keyboard()
        )
        
        # Notify user
        try:
            bot.send_message(
                current_user_id,
                "✅ **Діалог завершено адміністратором**\n\nДякуємо за спілкування! Ви можете розпочати новий діалог в будь-який час.",
                parse_mode='Markdown',
                reply_markup=get_main_keyboard()
            )
        except:
            pass
        
        logger.info(f"❌ Admin ended dialog with user {current_user_id}")
        
    except Exception as e:
        logger.error(f"Error ending admin dialog: {e}")
        bot.send_message(message.chat.id, Messages.ERROR_SEND_FAILED)

@bot.message_handler(func=lambda message: message.text == "🔄 Інший діалог" and is_admin(message.from_user.id))
def handle_admin_switch_dialog(message):
    """Admin switches to another dialog."""
    try:
        memory.clear_user_state(config.ADMIN_ID)
        handle_admin_active_dialogs(message)
        
    except Exception as e:
        logger.error(f"Error switching dialog: {e}")
        bot.send_message(message.chat.id, Messages.ERROR_SEND_FAILED)

@bot.message_handler(func=lambda message: message.text == "🏠 Головне меню" and is_admin(message.from_user.id))
def handle_admin_main_menu(message):
    """Return admin to main menu."""
    try:
        memory.clear_user_state(config.ADMIN_ID)
        
        stats = memory.get_statistics()
        admin_text = Messages.ADMIN_WELCOME.format(
            stats['active_dialogs'],
            stats['total_users'], 
            time.strftime('%H:%M %d.%m.%Y')
        )
        
        bot.send_message(
            message.chat.id,
            admin_text,
            parse_mode='Markdown',
            reply_markup=get_admin_main_keyboard()
        )
        
    except Exception as e:
        logger.error(f"Error returning to admin menu: {e}")
        bot.send_message(message.chat.id, Messages.ERROR_SEND_FAILED)

# Handle broadcast messages from admin
@bot.message_handler(func=lambda message: memory.get_user_state(message.from_user.id) == UserStates.ADMIN_BROADCASTING and is_admin(message.from_user.id))
def handle_admin_broadcast_message(message):
    """Process broadcast message from admin."""
    try:
        if message.text == "❌ Скасувати":
            memory.clear_user_state(config.ADMIN_ID)
            bot.send_message(
                message.chat.id,
                "❌ Розсилка скасована",
                reply_markup=get_admin_main_keyboard()
            )
            return
        
        broadcast_text = message.text
        users = memory.get_all_users()
        
        if not users:
            bot.send_message(
                message.chat.id,
                "❌ Немає користувачів для розсилки",
                reply_markup=get_admin_main_keyboard()
            )
            memory.clear_user_state(config.ADMIN_ID)
            return
        
        bot.send_message(message.chat.id, "📡 Починаю розсилку...")
        
        success_count = 0
        blocked_count = 0
        
        for user_id, username, full_name, _, _, _ in users:
            try:
                bot.send_message(
                    user_id,
                    f"📢 **Повідомлення від студії Kuznya Music:**\n\n{broadcast_text}",
                    parse_mode='Markdown'
                )
                success_count += 1
                logger.info(f"✅ Broadcast sent to {full_name} ({user_id})")
            except Exception as e:
                blocked_count += 1
                logger.warning(f"❌ Failed to send to {full_name} ({user_id}): {e}")
        
        # Send results
        result_text = f"""📊 **Розсилка завершена!**

✅ Надіслано: {success_count}
❌ Помилки/блоки: {blocked_count}
📋 Всього користувачів: {len(users)}

💬 **Текст розсилки:**
_{broadcast_text}_"""
        
        bot.send_message(
            message.chat.id,
            result_text,
            parse_mode='Markdown',
            reply_markup=get_admin_main_keyboard()
        )
        
        memory.clear_user_state(config.ADMIN_ID)
        logger.info(f"📢 Broadcast completed: {success_count}/{len(users)} successful")
        
    except Exception as e:
        logger.error(f"Error in broadcast: {e}")
        bot.send_message(message.chat.id, Messages.ERROR_SEND_FAILED)
        memory.clear_user_state(config.ADMIN_ID)

# Handle dialog messages from admin
@bot.message_handler(func=lambda message: memory.get_user_state(message.from_user.id) == UserStates.ADMIN_IN_DIALOG and is_admin(message.from_user.id))
def handle_admin_dialog_message(message):
    """Handle messages from admin in dialog."""
    try:
        # Skip button texts
        if message.text in ["❌ Завершити діалог", "🔄 Інший діалог", "🏠 Головне меню"]:
            return
        
        current_user_id = memory.get_admin_current_dialog(config.ADMIN_ID)
        
        if not current_user_id:
            memory.clear_user_state(config.ADMIN_ID)
            bot.send_message(
                message.chat.id,
                "❌ Помилка: дані діалогу втрачено",
                reply_markup=get_admin_main_keyboard()
            )
            return
        
        if not memory.is_user_in_dialog(current_user_id):
            memory.clear_user_state(config.ADMIN_ID)
            bot.send_message(
                message.chat.id,
                "❌ Діалог не активний",
                reply_markup=get_admin_main_keyboard()
            )
            return
        
        # Save admin message
        memory.save_message(current_user_id, message.text, True)
        
        # Forward to user
        user_text = f"👨‍💼 **Адміністратор:** {message.text}"
        
        try:
            bot.send_message(
                current_user_id,
                user_text,
                parse_mode='Markdown'
            )
            
            # Forward media if present
            if message.content_type != 'text':
                bot.forward_message(current_user_id, message.chat.id, message.message_id)
                
        except Exception as e:
            bot.send_message(
                message.chat.id,
                f"❌ Не вдалося надіслати користувачу: {e}"
            )
            logger.error(f"Failed to send to user {current_user_id}: {e}")
            return
        
        logger.info(f"💬 Admin message sent to user {current_user_id}")
        
    except Exception as e:
        logger.error(f"Error in admin dialog message: {e}")
        bot.send_message(message.chat.id, Messages.ERROR_SEND_FAILED)

# === CALLBACK HANDLERS ===

@bot.callback_query_handler(func=lambda call: call.data.startswith('enter_dialog_'))
def handle_enter_dialog_callback(call):
    """Handle admin entering existing dialog."""
    try:
        if not is_admin(call.from_user.id):
            bot.answer_callback_query(call.id, "❌ Немає доступу")
            return
        
        user_id = int(call.data.split('_')[2])
        
        if not memory.is_user_in_dialog(user_id):
            bot.answer_callback_query(call.id, "❌ Діалог не активний")
            return
        
        user_info = memory.get_user_info(user_id)
        memory.set_admin_current_dialog(config.ADMIN_ID, user_id)
        
        bot.edit_message_text(
            f"💬 **Діалог з {user_info.get('full_name', 'користувачем')}**\n\nПишіть повідомлення - користувач їх бачить миттєво!",
            call.message.chat.id,
            call.message.message_id,
            parse_mode='Markdown'
        )
        
        bot.send_message(
            call.message.chat.id,
            "Використовуйте кнопки для керування діалогом:",
            reply_markup=get_admin_dialog_keyboard()
        )
        
        bot.answer_callback_query(call.id, f"✅ Увійшли в діалог з {user_info.get('full_name', 'користувачем')}")
        logger.info(f"👨‍💼 Admin entered dialog with user {user_id}")
        
    except Exception as e:
        logger.error(f"Error entering dialog: {e}")
        bot.answer_callback_query(call.id, "❌ Помилка")

@bot.callback_query_handler(func=lambda call: call.data.startswith('start_dialog_'))
def handle_start_dialog_callback(call):
    """Handle admin starting new dialog with user."""
    try:
        if not is_admin(call.from_user.id):
            bot.answer_callback_query(call.id, "❌ Немає доступу")
            return
        
        user_id = int(call.data.split('_')[2])
        user_info = memory.get_user_info(user_id)
        
        if not user_info:
            bot.answer_callback_query(call.id, "❌ Користувача не знайдено")
            return
        
        if memory.is_user_in_dialog(user_id):
            bot.answer_callback_query(call.id, "❌ Користувач вже в діалозі")
            return
        
        # Start dialog
        if memory.start_dialog(user_id, config.ADMIN_ID):
            memory.set_admin_current_dialog(config.ADMIN_ID, user_id)
            
            bot.edit_message_text(
                f"✅ **Новий діалог розпочано з {user_info.get('full_name', 'користувачем')}!**\n\nПишіть повідомлення - користувач їх бачить миттєво!",
                call.message.chat.id,
                call.message.message_id,
                parse_mode='Markdown'
            )
            
            bot.send_message(
                call.message.chat.id,
                "Використовуйте кнопки для керування діалогом:",
                reply_markup=get_admin_dialog_keyboard()
            )
            
            # Notify user
            try:
                bot.send_message(
                    user_id,
                    "💬 **Адміністратор розпочав з вами діалог!**\n\nПишіть повідомлення - адміністратор їх бачить в реальному часі.",
                    parse_mode='Markdown',
                    reply_markup=get_dialog_keyboard()
                )
            except:
                pass
            
            bot.answer_callback_query(call.id, f"✅ Діалог розпочато з {user_info.get('full_name', 'користувачем')}")
            logger.info(f"🆕 Admin started new dialog with user {user_id}")
        else:
            bot.answer_callback_query(call.id, "❌ Помилка створення діалогу")
        
    except Exception as e:
        logger.error(f"Error starting dialog: {e}")
        bot.answer_callback_query(call.id, "❌ Помилка")

# === DEFAULT MESSAGE HANDLER ===

@bot.message_handler(func=lambda message: True)
def handle_other_messages(message):
    """Handle all other messages."""
    try:
        user_state = memory.get_user_state(message.from_user.id)
        user_info = get_user_info_from_message(message)
        
        # Save user info
        memory.save_user(user_info['id'], user_info['username'], user_info['full_name'])
        
        if is_admin(user_info['id']):
            # Admin fallback
            if user_state == UserStates.ADMIN_IN_DIALOG:
                handle_admin_dialog_message(message)
            elif user_state == UserStates.ADMIN_BROADCASTING:
                handle_admin_broadcast_message(message)
            else:
                bot.send_message(
                    message.chat.id,
                    "❓ Невідома команда. Використовуйте кнопки меню.",
                    reply_markup=get_admin_main_keyboard()
                )
        else:
            # Regular user fallback
            if user_state == UserStates.IN_DIALOG:
                handle_user_dialog_message(message)
            else:
                bot.send_message(
                    message.chat.id,
                    "❓ Використовуйте кнопки меню або напишіть /start",
                    reply_markup=get_main_keyboard()
                )
        
    except Exception as e:
        logger.error(f"Error in default handler: {e}")
        bot.send_message(message.chat.id, Messages.ERROR_SEND_FAILED)

# === FLASK WEB SERVER ===

app = Flask(__name__)
bot_start_time = time.time()

@app.route('/')
def health_check():
    """Main page for bot status check."""
    stats = memory.get_statistics()
    uptime = format_time_duration(stats['uptime_seconds'])
    
    return f"""
    <h1>🎵 Kuznya Music Studio Bot - Enhanced</h1>
    <p><strong>Статус:</strong> ✅ Активний</p>
    <p><strong>Uptime:</strong> {uptime}</p>
    <p><strong>Час запуску:</strong> {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(bot_start_time))}</p>
    <p><strong>Поточний час:</strong> {time.strftime('%Y-%m-%d %H:%M:%S')}</p>
    <p><strong>Користувачів:</strong> {stats['total_users']}</p>
    <p><strong>Активних діалогів:</strong> {stats['active_dialogs']}</p>
    <p><strong>Всього повідомлень:</strong> {stats['total_messages']}</p>
    <p><strong>Версія:</strong> Enhanced v2.0 with Dialog System</p>
    """

@app.route('/health')
def health():
    """JSON health endpoint."""
    try:
        bot_info = bot.get_me()
        stats = memory.get_statistics()
        
        return jsonify({
            "status": "healthy",
            "timestamp": time.time(),
            "uptime_seconds": stats['uptime_seconds'],
            "bot_username": bot_info.username,
            "total_users": stats['total_users'],
            "active_dialogs": stats['active_dialogs'],
            "total_messages": stats['total_messages'],
            "version": "enhanced_v2.0"
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
    """Simple ping endpoint."""
    return "pong", 200

@app.route('/stats')
def stats_endpoint():
    """Statistics endpoint."""
    try:
        stats = memory.get_statistics()
        return jsonify(stats)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/dialogs')
def dialogs_endpoint():
    """Active dialogs endpoint."""
    try:
        dialogs = memory.get_active_dialogs()
        return jsonify({
            "active_dialogs": len(dialogs),
            "dialogs": dialogs
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def self_ping():
    """Self-ping function to keep bot alive."""
    while True:
        try:
            time.sleep(config.SELF_PING_INTERVAL)
            # Make request to self
            try:
                response = requests.get(f"http://localhost:{config.WEBHOOK_PORT}/ping", timeout=5)
                if response.status_code == 200:
                    logger.info("🏓 Self-ping successful")
                else:
                    logger.warning(f"🏓 Self-ping failed with status {response.status_code}")
            except Exception as ping_error:
                logger.warning(f"🏓 Self-ping error: {ping_error}")
                
        except Exception as e:
            logger.error(f"Self-ping thread error: {e}")

def run_flask():
    """Run Flask server."""
    app.run(
        host='0.0.0.0', 
        port=config.WEBHOOK_PORT, 
        debug=False,
        threaded=True
    )

# === MAIN EXECUTION ===

if __name__ == "__main__":
    try:
        logger.info("🎵 Starting Kuznya Music Studio Bot - Enhanced Version...")
        
        # Start Flask server
        flask_thread = Thread(target=run_flask, daemon=True)
        flask_thread.start()
        logger.info(f"🌐 Flask server started on port {config.WEBHOOK_PORT}")
        
        # Start self-ping system
        self_ping_thread = Thread(target=self_ping, daemon=True)
        self_ping_thread.start()
        logger.info("🔄 Self-ping system started")
        
        # Log available endpoints
        logger.info("📡 Health check endpoints:")
        logger.info(f"  - Main: http://localhost:{config.WEBHOOK_PORT}/")
        logger.info(f"  - Health: http://localhost:{config.WEBHOOK_PORT}/health")
        logger.info(f"  - Stats: http://localhost:{config.WEBHOOK_PORT}/stats")
        logger.info(f"  - Dialogs: http://localhost:{config.WEBHOOK_PORT}/dialogs")
        
        # Clear previous instances
        logger.info("🧹 Clearing previous bot instances...")
        try:
            bot.remove_webhook()
            bot.stop_polling()
        except Exception as clear_error:
            logger.warning(f"Warning during cleanup: {clear_error}")
        
        time.sleep(3)
        
        # Start bot
        logger.info("🚀 Enhanced Music Studio Bot started successfully!")
        logger.info(f"👨‍💼 Admin ID: {config.ADMIN_ID}")
        logger.info("🎯 NEW FEATURES:")
        logger.info("  - Advanced dialog system")
        logger.info("  - Enhanced admin panel")
        logger.info("  - Real-time messaging")
        logger.info("  - Dialog management")
        logger.info("  - Broadcasting system")
        logger.info("  - Comprehensive statistics")
        logger.info("💬 Bot is now polling for messages...")
        
        # Start polling with conflict handling
        while True:
            try:
                bot.polling(none_stop=True, interval=1, timeout=30)
            except telebot.apihelper.ApiTelegramException as api_error:
                if "409" in str(api_error) or "Conflict" in str(api_error):
                    logger.warning("⚠️ Conflict detected - retrying in 10 seconds...")
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
        logger.info("🛑 Bot stopped by user")
        try:
            bot.stop_polling()
        except:
            pass
    except Exception as e:
        logger.critical(f"💥 Critical error: {e}")
        try:
            bot.stop_polling()
        except:
            pass
        exit(1)

