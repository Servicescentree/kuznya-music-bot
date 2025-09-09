import asyncio
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from datetime import datetime
import sqlite3

BOT_TOKEN = "8177077520:AAFqmsMicgg2WHY-1l_fLAZjTHq8oSCbdcs"
ADMIN_ID = 7276479457

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

def init_db():
    conn = sqlite3.connect('messages.db')
    cursor = conn.cursor()
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
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT,
            full_name TEXT,
            message_text TEXT,
            message_type TEXT DEFAULT 'text',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            admin_replied BOOLEAN DEFAULT 0,
            admin_reply_text TEXT,
            dialog_id TEXT,
            is_from_admin BOOLEAN DEFAULT 0
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS dialogs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            admin_id INTEGER NOT NULL,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ended_at TIMESTAMP DEFAULT NULL,
            is_active BOOLEAN DEFAULT 1
        )
    ''')
    conn.commit()
    conn.close()

class UserStates(StatesGroup):
    writing_message = State()
    in_dialog = State()
    replying_to_admin = State()

class AdminStates(StatesGroup):
    replying_to_user = State()
    broadcasting = State()
    in_dialog = State()
    selecting_user = State()

def save_user(user_id, username, full_name):
    conn = sqlite3.connect('messages.db')
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

def save_message(user_id, username, full_name, message_text, message_type='text', is_from_admin=False, dialog_id=None):
    conn = sqlite3.connect('messages.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO messages (user_id, username, full_name, message_text, message_type, is_from_admin, dialog_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (user_id, username, full_name, message_text, message_type, is_from_admin, dialog_id))
    message_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return message_id

def start_dialog(user_id, admin_id):
    conn = sqlite3.connect('messages.db')
    cursor = conn.cursor()
    cursor.execute('SELECT id FROM dialogs WHERE user_id = ? AND is_active = 1', (user_id,))
    existing = cursor.fetchone()
    if existing:
        conn.close()
        return existing[0]
    cursor.execute('''
        INSERT INTO dialogs (user_id, admin_id) VALUES (?, ?)
    ''', (user_id, admin_id))
    dialog_id = cursor.lastrowid
    cursor.execute('''
        UPDATE users SET in_dialog = 1, dialog_with = ? WHERE user_id = ?
    ''', (admin_id, user_id))
    conn.commit()
    conn.close()
    return dialog_id

def end_dialog(user_id):
    conn = sqlite3.connect('messages.db')
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE dialogs SET is_active = 0, ended_at = ? 
        WHERE user_id = ? AND is_active = 1
    ''', (datetime.now(), user_id))
    cursor.execute('''
        UPDATE users SET in_dialog = 0, dialog_with = NULL WHERE user_id = ?
    ''', (user_id,))
    conn.commit()
    conn.close()

def get_active_dialog(user_id):
    conn = sqlite3.connect('messages.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, admin_id FROM dialogs 
        WHERE user_id = ? AND is_active = 1
    ''', (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result

def get_user_info(user_id):
    conn = sqlite3.connect('messages.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT username, full_name FROM users WHERE user_id = ?
    ''', (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result

def get_all_users():
    conn = sqlite3.connect('messages.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT user_id, username, full_name, total_messages, last_activity, in_dialog
        FROM users
        WHERE user_id != ?
        ORDER BY in_dialog DESC, last_activity DESC
    ''', (ADMIN_ID,))
    users = cursor.fetchall()
    conn.close()
    return users

def get_admin_active_dialogs():
    conn = sqlite3.connect('messages.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT d.id, d.user_id, u.username, u.full_name, d.started_at,
               (SELECT COUNT(*) FROM messages m WHERE m.dialog_id = d.id) as msg_count
        FROM dialogs d
        JOIN users u ON d.user_id = u.user_id
        WHERE d.is_active = 1 AND d.admin_id = ?
        ORDER BY d.started_at DESC
    ''', (ADMIN_ID,))
    dialogs = cursor.fetchall()
    conn.close()
    return dialogs

def main_keyboard():
    keyboard = [
        [KeyboardButton(text="💬 Почати діалог")],
        [KeyboardButton(text="ℹ️ Про бота"), KeyboardButton(text="📞 Контакти")]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

def dialog_keyboard():
    keyboard = [
        [KeyboardButton(text="❌ Завершити діалог")]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

def admin_keyboard():
    keyboard = [
        [KeyboardButton(text="💬 Активні діалоги")],
        [KeyboardButton(text="🆕 Почати новий діалог")],
        [KeyboardButton(text="👥 Список користувачів")],
        [KeyboardButton(text="📊 Статистика")],
        [KeyboardButton(text="📢 Розсилка всім")]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

def admin_dialog_keyboard():
    keyboard = [
        [KeyboardButton(text="❌ Завершити діалог")],
        [KeyboardButton(text="🔄 Перейти до іншого діалогу")],
        [KeyboardButton(text="🏠 Головне меню")]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

async def send_user_message_to_admin(user_id, full_name, message_text, dialog_id, message_db_id):
    admin_text = (
        f"💬 <b>Діалог з {full_name}</b>\n\n"
        f"👤 {message_text}"
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="↩️ Відповісти", callback_data=f"admin_reply_{message_db_id}")]
        ]
    )
    await bot.send_message(ADMIN_ID, admin_text, reply_markup=keyboard, parse_mode="HTML")

async def send_admin_message_to_user(user_id, admin_text, orig_text, message_db_id):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="↩️ Відповісти", callback_data=f"user_reply_{message_db_id}")]
        ]
    )
    text = f"👨‍💼 <b>Адмін:</b> {admin_text}"
    await bot.send_message(user_id, text, reply_markup=keyboard, parse_mode="HTML")

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    user = message.from_user
    save_user(user.id, user.username, user.full_name)
    if user.id == ADMIN_ID:
        active_dialogs = get_admin_active_dialogs()
        await message.answer(
            "👨‍💼 <b>Адмін панель</b>\n\n"
            f"🟢 Активних діалогів: {len(active_dialogs)}",
            reply_markup=admin_keyboard(),
            parse_mode="HTML"
        )
    else:
        dialog = get_active_dialog(user.id)
        if dialog:
            await state.set_state(UserStates.in_dialog)
            await message.answer(
                "💬 Ви у діалозі з адміністратором!",
                reply_markup=dialog_keyboard()
            )
        else:
            await message.answer(
                "👋 Привіт! Я бот-консультант. Оберіть дію або почніть діалог.",
                reply_markup=main_keyboard()
            )

@dp.message(F.text == "💬 Почати діалог")
async def start_dialog_user(message: types.Message, state: FSMContext):
    if message.from_user.id == ADMIN_ID:
        await message.answer("Виберіть користувача у меню для старту нового діалогу.", reply_markup=admin_keyboard())
        return
    user_id = message.from_user.id
    dialog = get_active_dialog(user_id)
    if dialog:
        await state.set_state(UserStates.in_dialog)
        await message.answer("Ви вже в діалозі!", reply_markup=dialog_keyboard())
        return
    user = message.from_user
    dialog_id = start_dialog(user_id, ADMIN_ID)
    await state.set_state(UserStates.in_dialog)
    await message.answer(
        "✅ Діалог розпочато! Пишіть повідомлення, адміністратор їх бачить.",
        reply_markup=dialog_keyboard()
    )
    await bot.send_message(ADMIN_ID, f"🆕 Новий діалог з {user.full_name} (@{user.username})", parse_mode="HTML")

@dp.message(F.text == "❌ Завершити діалог")
async def end_dialog_user(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id == ADMIN_ID:
        data = await state.get_data()
        dialog_user_id = data.get("user_id") if data else None
        if dialog_user_id:
            end_dialog(dialog_user_id)
            await bot.send_message(dialog_user_id, "✅ Діалог завершено адміністратором.", reply_markup=main_keyboard())
        await state.clear()
        await message.answer("✅ Діалог завершено", reply_markup=admin_keyboard())
    else:
        dialog = get_active_dialog(user_id)
        if not dialog:
            await message.answer("❌ Ви не у діалозі.", reply_markup=main_keyboard())
            return
        end_dialog(user_id)
        await state.clear()
        await message.answer("✅ Діалог завершено.", reply_markup=main_keyboard())
        user_info = get_user_info(user_id)
        if user_info:
            username, full_name = user_info
            await bot.send_message(ADMIN_ID, f"❌ Діалог завершено користувачем {full_name} (@{username})", parse_mode="HTML")

@dp.message(StateFilter(UserStates.in_dialog))
async def handle_user_dialog_message(message: types.Message, state: FSMContext):
    if message.text == "❌ Завершити діалог":
        return
    user = message.from_user
    dialog = get_active_dialog(user.id)
    if not dialog:
        await state.clear()
        await message.answer("❌ Діалог не активний.", reply_markup=main_keyboard())
        return
    dialog_id, admin_id = dialog
    message_text = message.text or message.caption or "[Медіа файл]"
    message_db_id = save_message(user.id, user.username, user.full_name, message_text, message.content_type, False, dialog_id)
    await send_user_message_to_admin(user.id, user.full_name, message_text, dialog_id, message_db_id)

@dp.message(F.text == "💬 Активні діалоги")
async def admin_active_dialogs(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    dialogs = get_admin_active_dialogs()
    if not dialogs:
        await message.answer("Немає активних діалогів.", reply_markup=admin_keyboard())
    else:
        txt = "Список активних діалогів:\n\n"
        for d in dialogs:
            txt += f"👤 {d[3]} (@{d[2]}) | ID: <code>{d[1]}</code> | {d[5]} повідомлень\n"
        await message.answer(txt, parse_mode="HTML", reply_markup=admin_keyboard())

@dp.message(F.text == "🆕 Почати новий діалог")
async def admin_start_new_dialog(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    users = get_all_users()
    txt = "Оберіть користувача для старту діалогу:\n\n"
    for u in users:
        txt += f"👤 {u[2]} (@{u[1]}) | ID: <code>{u[0]}</code>\n"
    await message.answer(txt, parse_mode="HTML", reply_markup=admin_keyboard())

@dp.message(F.text == "👥 Список користувачів")
async def users_list(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    users = get_all_users()
    txt = "Список користувачів:\n\n"
    for u in users:
        txt += f"👤 {u[2]} (@{u[1]}) | Повідомлень: {u[3]} | Активний діалог: {'✅' if u[5] else '❌'}\n"
    await message.answer(txt, reply_markup=admin_keyboard())

@dp.message(F.text == "📊 Статистика")
async def statistics(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    users = get_all_users()
    await message.answer(f"Користувачів: {len(users)}", reply_markup=admin_keyboard())

@dp.message(F.text == "📢 Розсилка всім")
async def broadcast_message(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer("Введіть текст розсилки:", reply_markup=admin_keyboard())
    await state.set_state(AdminStates.broadcasting)

@dp.message(StateFilter(AdminStates.broadcasting))
async def process_broadcast(message: types.Message, state: FSMContext):
    users = get_all_users()
    for u in users:
        try:
            await bot.send_message(u[0], f"📢 Розсилка від адміна:\n\n{message.text}")
        except Exception:
            pass
    await message.answer("Розсилку завершено.", reply_markup=admin_keyboard())
    await state.clear()

@dp.callback_query(F.data.startswith("admin_reply_"))
async def admin_reply_callback(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    msg_db_id = int(callback.data.split("_")[2])
    conn = sqlite3.connect('messages.db')
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, dialog_id FROM messages WHERE id = ?", (msg_db_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        await callback.answer("Помилка: повідомлення не знайдено")
        return
    user_id, dialog_id = row
    active_dialog = get_active_dialog(user_id)
    if not active_dialog:
        new_dialog_id = start_dialog(user_id, ADMIN_ID)
        await state.set_data({"reply_to_msg_db_id": msg_db_id, "user_id": user_id, "dialog_id": new_dialog_id})
    else:
        await state.set_data({"reply_to_msg_db_id": msg_db_id, "user_id": user_id, "dialog_id": active_dialog[0]})
    await state.set_state(AdminStates.replying_to_user)
    await callback.message.answer("Введіть текст для відповіді користувачу:", reply_markup=admin_dialog_keyboard())
    await callback.answer()

@dp.message(StateFilter(AdminStates.replying_to_user))
async def admin_reply_to_specific_message(message: types.Message, state: FSMContext):
    data = await state.get_data()
    msg_db_id = data.get("reply_to_msg_db_id")
    user_id = data.get("user_id")
    dialog_id = data.get("dialog_id")
    if not msg_db_id or not user_id or not dialog_id:
        await message.answer("Помилка: не вибрано повідомлення для відповіді.", reply_markup=admin_keyboard())
        await state.clear()
        return
    conn = sqlite3.connect('messages.db')
    cursor = conn.cursor()
    cursor.execute("SELECT message_text FROM messages WHERE id = ?", (msg_db_id,))
    row = cursor.fetchone()
    conn.close()
    orig_text = row[0] if row else ""
    message_db_id = save_message(user_id, "admin", "Адміністратор", message.text, message.content_type, True, dialog_id)
    await send_admin_message_to_user(user_id, message.text, orig_text, message_db_id)
    await message.answer("Відповідь надіслано.", reply_markup=admin_dialog_keyboard())
    await state.clear()

@dp.callback_query(F.data.startswith("user_reply_"))
async def user_reply_callback(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    msg_db_id = int(callback.data.split("_")[2])
    conn = sqlite3.connect('messages.db')
    cursor = conn.cursor()
    cursor.execute("SELECT dialog_id FROM messages WHERE id = ?", (msg_db_id,))
    row = cursor.fetchone()
    conn.close()
    active_dialog = get_active_dialog(user_id)
    if not active_dialog:
        new_dialog_id = start_dialog(user_id, ADMIN_ID)
        await state.set_data({"reply_to_msg_db_id": msg_db_id, "dialog_id": new_dialog_id})
    else:
        await state.set_data({"reply_to_msg_db_id": msg_db_id, "dialog_id": active_dialog[0]})
    await state.set_state(UserStates.replying_to_admin)
    await callback.answer("Введіть текст для відповіді адміністратору:")

@dp.message(StateFilter(UserStates.replying_to_admin))
async def user_reply_to_admin(message: types.Message, state: FSMContext):
    data = await state.get_data()
    msg_db_id = data.get("reply_to_msg_db_id")
    dialog_id = data.get("dialog_id")
    user_id = message.from_user.id
    user_info = get_user_info(user_id)
    username, full_name = user_info if user_info else ("", "")
    conn = sqlite3.connect('messages.db')
    cursor = conn.cursor()
    cursor.execute("SELECT message_text FROM messages WHERE id = ?", (msg_db_id,))
    row = cursor.fetchone()
    conn.close()
    orig_text = row[0] if row else ""
    message_db_id = save_message(user_id, username, full_name, message.text, message.content_type, False, dialog_id)
    await send_user_message_to_admin(user_id, full_name, f"🗨️ Відповідь на: <i>{orig_text}</i>\n\n➡️ {message.text}", dialog_id, message_db_id)
    await message.answer("Відповідь надіслано адміністратору.", reply_markup=dialog_keyboard())
    await state.clear()

@dp.message(F.text == "🔄 Перейти до іншого діалогу")
async def admin_switch_dialog(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer("Виберіть інший діалог у списку.", reply_markup=admin_keyboard())

@dp.message(F.text == "🏠 Головне меню")
async def admin_main_menu(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await state.clear()
    await message.answer("Ви повернулись у головне меню.", reply_markup=admin_keyboard())

async def main():
    init_db()
    print("🚀 Universal Consultant Bot launched!")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
