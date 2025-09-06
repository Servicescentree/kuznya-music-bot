import os
import time
import logging
import telebot
from telebot import types
from flask import Flask, jsonify
from threading import Thread

# Налаштування логування
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Конфігурація
BOT_TOKEN = os.getenv('BOT_TOKEN', 'your_token_here')
ADMIN_ID = int(os.getenv('ADMIN_ID', '7276479457'))
PORT = int(os.getenv('PORT', 8080))

# Ініціалізація бота
bot = telebot.TeleBot(BOT_TOKEN)

# Стани користувачів (простий словник замість БД)
user_states = {}

# Константи
CHANNEL_URL = 'https://t.me/kuznya_music'
EXAMPLES_URL = 'https://t.me/kuznya_music/41'

# Повідомлення
MESSAGES = {
    'welcome': """Привіт, {}! 👋
Ласкаво просимо до музичної студії Kuznya Music!

Оберіть дію з меню:""",
    
    'recording_prompt': """🎤 *Запис треку*

Опишіть ваші побажання:
• Запис, Зведення
• Аранжування 
• Референси (приклади)
• Терміни (коли хочете записатись)

_Ваше повідомлення буде передано адміністратору_""",
    
    'examples_info': f"""🎵 *Наші роботи:*

Послухати приклади можна тут:
{EXAMPLES_URL}

Тут ви знайдете найкращі зразки нашої творчості!""",
    
    'channel_info': f"""📢 *Підписуйтесь на наш канал:*

{CHANNEL_URL}

Там ви знайдете:
• Нові роботи
• Закулісся студії
• Акції та знижки""",
    
    'contacts_info': """📲 *Контакти студії:*

Telegram: @kuznya_music
Або використовуйте кнопку '🎤 Записати трек' для прямого зв'язку""",
    
    'message_sent': """✅ Повідомлення відправлено адміністратору!
Очікуйте відповіді...

_Ви можете відправити додаткові повідомлення або завершити діалог_""",
    
    'dialog_ended': "✅ Діалог завершено. Повертаємося до головного меню."
}

# Клавіатури
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

# Обробники команд
@bot.message_handler(commands=['start'])
def handle_start(message):
    try:
        user_id = message.from_user.id
        user_states[user_id] = 'idle'
        
        first_name = message.from_user.first_name or "друже"
        markup = get_main_keyboard()
        
        bot.send_message(
            message.chat.id,
            MESSAGES['welcome'].format(first_name),
            reply_markup=markup
        )
        logger.info(f"User {user_id} started bot")
    except Exception as e:
        logger.error(f"Error in start: {e}")

@bot.message_handler(func=lambda message: message.text == "🎤 Записати трек")
def handle_recording(message):
    try:
        user_id = message.from_user.id
        user_states[user_id] = 'waiting_message'
        
        markup = get_chat_keyboard()
        bot.send_message(
            message.chat.id,
            MESSAGES['recording_prompt'],
            parse_mode='Markdown',
            reply_markup=markup
        )
        logger.info(f"User {user_id} started recording mode")
    except Exception as e:
        logger.error(f"Error in recording: {e}")

@bot.message_handler(func=lambda message: message.text == "🎧 Приклади робіт")
def handle_examples(message):
    try:
        bot.send_message(
            message.chat.id,
            MESSAGES['examples_info'],
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Error in examples: {e}")

@bot.message_handler(func=lambda message: message.text == "📢 Підписатися")
def handle_channel(message):
    try:
        bot.send_message(
            message.chat.id,
            MESSAGES['channel_info'],
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Error in channel: {e}")

@bot.message_handler(func=lambda message: message.text == "📲 Контакти")
def handle_contacts(message):
    try:
        bot.send_message(
            message.chat.id,
            MESSAGES['contacts_info'],
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Error in contacts: {e}")

@bot.message_handler(func=lambda message: message.text == "❌ Завершити діалог")
def handle_end_dialog(message):
    try:
        user_id = message.from_user.id
        user_states[user_id] = 'idle'
        
        markup = get_main_keyboard()
        bot.send_message(
            message.chat.id,
            MESSAGES['dialog_ended'],
            reply_markup=markup
        )
        logger.info(f"User {user_id} ended dialog")
    except Exception as e:
        logger.error(f"Error in end dialog: {e}")

@bot.message_handler(func=lambda message: user_states.get(message.from_user.id) == 'waiting_message')
def handle_user_message(message):
    try:
        user = message.from_user
        user_id = user.id
        
        # Формуємо повідомлення для адміна
        admin_text = f"""💬 *Нове повідомлення від клієнта*

👤 *Клієнт:* {user.first_name or ''} {user.last_name or ''}
🆔 *Username:* @{user.username or 'немає'}
🆔 *ID:* {user_id}
⏰ *Час:* {time.strftime('%H:%M %d.%m.%Y')}

📝 *Повідомлення:*
{message.text}"""
        
        # Створюємо кнопку відповіді
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(
            "✍️ Відповісти", 
            callback_data=f"reply_{user_id}"
        ))
        
        # Відправляємо адміну
        bot.send_message(
            ADMIN_ID,
            admin_text,
            parse_mode='Markdown',
            reply_markup=markup
        )
        
        # Підтверджуємо користувачу
        bot.send_message(message.chat.id, MESSAGES['message_sent'])
        
        logger.info(f"Message forwarded from user {user_id} to admin")
        
    except Exception as e:
        logger.error(f"Error forwarding message: {e}")
        bot.send_message(message.chat.id, "❌ Помилка при відправці. Спробуйте пізніше.")

@bot.callback_query_handler(func=lambda call: call.data.startswith('reply_'))
def handle_admin_reply_callback(call):
    try:
        if call.from_user.id != ADMIN_ID:
            bot.answer_callback_query(call.id, "❌ Немає доступу")
            return
        
        user_id = int(call.data.split('_')[1])
        user_states[ADMIN_ID] = f'replying_{user_id}'
        
        bot.answer_callback_query(call.id, "Напишіть відповідь наступним повідомленням")
        bot.send_message(
            ADMIN_ID,
            f"✍️ Напишіть відповідь клієнту (ID: {user_id}):\n\n_Наступне повідомлення буде відправлено клієнту_",
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"Error in reply callback: {e}")

@bot.message_handler(func=lambda message: message.from_user.id == ADMIN_ID and user_states.get(ADMIN_ID, '').startswith('replying_'))
def handle_admin_reply(message):
    try:
        admin_state = user_states.get(ADMIN_ID, '')
        target_user_id = int(admin_state.split('_')[1])
        
        # Відправляємо відповідь користувачу
        reply_text = f"💬 *Відповідь від адміністратора:*\n\n{message.text}"
        bot.send_message(target_user_id, reply_text, parse_mode='Markdown')
        
        # Підтверджуємо адміну
        bot.send_message(ADMIN_ID, f"✅ Відповідь відправлено клієнту (ID: {target_user_id})")
        
        # Скидаємо стан адміна
        user_states[ADMIN_ID] = 'idle'
        
        logger.info(f"Admin replied to user {target_user_id}")
        
    except Exception as e:
        logger.error(f"Error in admin reply: {e}")
        bot.send_message(ADMIN_ID, "❌ Помилка при відправці відповіді")
        user_states[ADMIN_ID] = 'idle'

@bot.message_handler(func=lambda message: True)
def handle_other_messages(message):
    try:
        if user_states.get(message.from_user.id, 'idle') == 'idle':
            markup = get_main_keyboard()
            bot.send_message(
                message.chat.id,
                "🤔 Використовуйте кнопки меню для навігації",
                reply_markup=markup
            )
    except Exception as e:
        logger.error(f"Error in other messages: {e}")

# Flask для health check
app = Flask(__name__)

@app.route('/')
def home():
    return "🎵 Kuznya Music Bot is running!"

@app.route('/health')
def health():
    return jsonify({"status": "healthy", "timestamp": time.time()})

def run_flask():
    app.run(host='0.0.0.0', port=PORT)

# Запуск
if __name__ == "__main__":
    try:
        # Запускаємо Flask в окремому потоці
        flask_thread = Thread(target=run_flask, daemon=True)
        flask_thread.start()
        
        logger.info(f"Flask server started on port {PORT}")
        logger.info("🎵 Music Studio Bot started!")
        logger.info(f"Admin ID: {ADMIN_ID}")
        
        # Запускаємо бота
        bot.polling(none_stop=True, interval=1, timeout=30)
        
    except Exception as e:
        logger.error(f"Critical error: {e}")
