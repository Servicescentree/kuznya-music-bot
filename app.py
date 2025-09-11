import asyncio
import logging
import sqlite3
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from datetime import datetime
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

BOT_TOKEN = "8177077520:AAFqmsMicgg2WHY-1l_fLAZjTHq8oSCbdcs"
ADMIN_ID = 7276479457

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# --- Ініціалізація бази ---
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
            dialog_id INTEGER,
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

# --- FSM States ---
class UserStates(StatesGroup):
    in_dialog = State()

class AdminStates(StatesGroup):
    replying_to_user = State()
    broadcasting = State()

# --- DB допоміжні ---
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

def start_dialog(user_id, admin_id, username=None, full_name=None):
    if username is not None and full_name is not None:
        save_user(user_id, username, full_name)
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

def get_stats():
    conn = sqlite3.connect('messages.db')
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM users WHERE user_id != ?', (ADMIN_ID,))
    total_users = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*) FROM dialogs')
    total_dialogs = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*) FROM dialogs WHERE is_active = 1')
    active_dialogs = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*) FROM messages')
    total_messages = cursor.fetchone()[0]
    conn.close()
    return total_users, total_dialogs, active_dialogs, total_messages

# --- Клавіатури ---
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
        [KeyboardButton(text="👥 Список користувачів")],
        [KeyboardButton(text="📢 Розсилка всім")],
        [KeyboardButton(text="📊 Статистика")],
        [KeyboardButton(text="🏠 Головне меню")]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

def admin_dialog_keyboard():
    keyboard = [
        [KeyboardButton(text="❌ Завершити діалог")]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

# --- Відправлення повідомлення користувача адміну з кнопками ---
async def send_user_message_to_admin(user_id, full_name, message_text, dialog_id, message_db_id):
    admin_text = (
        f"💬 <b>Діалог з {full_name}</b>\n\n"
        f"👤 {message_text}"
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="↩️ Відповісти", callback_data=f"admin_reply:{user_id}:{dialog_id}")
            ]
        ]
    )
    await bot.send_message(ADMIN_ID, admin_text, reply_markup=keyboard, parse_mode="HTML")

async def send_admin_message_to_user(user_id, admin_text):
    text = f"👨‍💼 <b>Адмін:</b> {admin_text}"
    await bot.send_message(user_id, text, parse_mode="HTML")

# --- Хендлери ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    user = message.from_user
    save_user(user.id, user.username, user.full_name)
    if user.id == ADMIN_ID:
        active_dialogs = get_admin_active_dialogs()
        await message.answer(
            "👨‍💼 <b>Ласкаво просимо в адмін-панель!</b>\n"
            "Використовуйте кнопки для управління ботом.\n\n"
            f"🟢 Активних діалогів: {len(active_dialogs)}",
            reply_markup=admin_keyboard(),
            parse_mode="HTML"
        )
    else:
        dialog = get_active_dialog(user.id)
        name = user.full_name or user.first_name or user.username or "користувачу"
        if dialog:
            await state.set_state(UserStates.in_dialog)
            await message.answer(
                f"💬 Ви у діалозі з адміністратором, {name}!",
                reply_markup=dialog_keyboard()
            )
        else:
            await message.answer(
                f"👋 Привіт, {name}! Я бот-консультант. Оберіть дію або почніть діалог.",
                reply_markup=main_keyboard()
            )

@dp.message(F.text == "ℹ️ Про бота")
async def about_bot(message: types.Message, state: FSMContext):
    await message.answer(
        "🤖 Це бот для зв'язку з адміністратором. Натисніть 'Почати діалог', щоб поставити питання або отримати консультацію.",
        reply_markup=main_keyboard()
    )

@dp.message(F.text == "📞 Контакти")
async def contacts(message: types.Message, state: FSMContext):
    await message.answer(
        "📞 Зв'язок з адміном: @admin\nНапишіть у діалог або використайте кнопку для зв'язку.",
        reply_markup=main_keyboard()
    )

@dp.message(F.text == "💬 Почати діалог")
async def start_dialog_handler(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id == ADMIN_ID:
        await message.answer("Ця функція недоступна для адміністратора.", reply_markup=admin_keyboard())
        return
    dialog = get_active_dialog(user_id)
    if dialog:
        await state.set_state(UserStates.in_dialog)
        await message.answer("Ви вже у діалозі!", reply_markup=dialog_keyboard())
        return
    start_dialog(user_id, ADMIN_ID, message.from_user.username, message.from_user.full_name)
    await state.set_state(UserStates.in_dialog)
    await message.answer("✅ Діалог створено! Пишіть своє питання адміну.", reply_markup=dialog_keyboard())
    await bot.send_message(ADMIN_ID, f"🔔 Новий діалог з {message.from_user.full_name} (@{message.from_user.username})")

@dp.message(F.text == "❌ Завершити діалог")
async def end_dialog_handler(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id == ADMIN_ID:
        data = await state.get_data()
        if not data or not data.get("user_id"):
            await message.answer("Діалог для завершення не обрано.", reply_markup=admin_keyboard())
            await state.clear()
            return
        end_user_id = data.get("user_id")
        end_dialog(end_user_id)
        await bot.send_message(end_user_id, "❌ Діалог завершено адміністратором.", reply_markup=main_keyboard())
        await message.answer("Діалог завершено!", reply_markup=admin_keyboard())
        await state.clear()
        return

    dialog = get_active_dialog(user_id)
    if not dialog:
        await message.answer("Ви не перебуваєте у діалозі.", reply_markup=main_keyboard())
        return
    end_dialog(user_id)
    await state.clear()
    await message.answer("✅ Діалог завершено.", reply_markup=main_keyboard())
    await bot.send_message(ADMIN_ID, f"❌ Діалог завершено користувачем {message.from_user.full_name} (@{message.from_user.username})")

@dp.message(UserStates.in_dialog)
async def user_dialog_message(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    dialog = get_active_dialog(user_id)
    if not dialog:
        await state.clear()
        await message.answer("Діалог завершено. Щоб почати новий — натисніть 'Почати діалог'.", reply_markup=main_keyboard())
        return
    dialog_id, _ = dialog
    message_db_id = save_message(user_id=user_id, username=message.from_user.username, full_name=message.from_user.full_name, message_text=message.text, is_from_admin=False, dialog_id=dialog_id)
    await send_user_message_to_admin(user_id, message.from_user.full_name, message.text, dialog_id, message_db_id)
    await message.answer("✅ Повідомлення надіслано адміністратору.", reply_markup=dialog_keyboard())

@dp.callback_query(F.data.startswith("admin_reply:"))
async def admin_reply_callback(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Доступ лише для адміністратора", show_alert=True)
        return
    try:
        _, user_id, dialog_id = callback.data.split(":")
        user_id, dialog_id = int(user_id), int(dialog_id)
    except Exception:
        await callback.answer("Помилка в параметрах", show_alert=True)
        return
    await state.set_state(AdminStates.replying_to_user)
    await state.update_data(user_id=user_id, dialog_id=dialog_id)
    user_info = get_user_info(user_id)
    username = user_info[0] if user_info else ""
    full_name = user_info[1] if user_info else ""
    await callback.message.answer(
        f"Ви відповідаєте користувачу:\n<b>{full_name}</b> (<a href='https://t.me/{username}'>@{username}</a>, id <code>{user_id}</code>)\n\n"
        f"Напишіть текст відповіді або натисніть '❌ Завершити діалог'.",
        parse_mode="HTML",
        reply_markup=admin_dialog_keyboard()
    )
    await callback.answer("Введіть відповідь користувачу...")

@dp.callback_query(F.data.startswith("admin_end:"))
async def admin_end_dialog_callback(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Доступ лише для адміністратора", show_alert=True)
        return
    try:
        _, user_id, dialog_id = callback.data.split(":")
        user_id, dialog_id = int(user_id), int(dialog_id)
    except Exception:
        await callback.answer("Помилка в параметрах", show_alert=True)
        return
    end_dialog(user_id)
    await bot.send_message(user_id, "❌ Діалог завершено адміністратором.", reply_markup=main_keyboard())
    await callback.message.answer("Діалог завершено.", reply_markup=admin_keyboard())
    await state.clear()
    await callback.answer("Діалог завершено!")

@dp.message(AdminStates.replying_to_user)
async def admin_send_reply(message: types.Message, state: FSMContext):
    data = await state.get_data()
    user_id = data.get("user_id")
    dialog_id = data.get("dialog_id")
    if not (user_id and dialog_id):
        await message.answer("Помилка: не знайдено діалог або користувача.", reply_markup=admin_keyboard())
        await state.clear()
        return
    user_info = get_user_info(user_id)
    username = user_info[0] if user_info else ""
    full_name = user_info[1] if user_info else ""
    save_message(
        user_id=ADMIN_ID,
        username="admin",
        full_name="Адміністратор",
        message_text=message.text,
        is_from_admin=True,
        dialog_id=dialog_id
    )
    await send_admin_message_to_user(user_id, message.text)
    await message.answer(
        f"Відповідь відправлено користувачу:\n<b>{full_name}</b> (<a href='https://t.me/{username}'>@{username}</a>, id <code>{user_id}</code>)",
        parse_mode="HTML",
        reply_markup=admin_dialog_keyboard()
    )

@dp.message(F.text == "💬 Активні діалоги")
async def admin_active_dialogs(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    dialogs = get_admin_active_dialogs()
    if not dialogs:
        await message.answer("Немає активних діалогів.", reply_markup=admin_keyboard())
        return
    text = "🟢 <b>Активні діалоги:</b>\n\n"
    for d in dialogs:
        text += f"👤 {d[3]} | ID: <code>{d[1]}</code> | Повідомлень: {d[5]}\n"
    await message.answer(text, parse_mode="HTML", reply_markup=admin_keyboard())

@dp.message(F.text == "👥 Список користувачів")
async def admin_users_list(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    users = get_all_users()
    text = "👥 <b>Список користувачів:</b>\n\n"
    for u in users:
        text += f"👤 {u[2]} (@{u[1]}) | ID: <code>{u[0]}</code>\n"
    await message.answer(text, parse_mode="HTML", reply_markup=admin_keyboard())

@dp.message(F.text == "📢 Розсилка всім")
async def admin_broadcast(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer("Введіть текст розсилки:", reply_markup=admin_keyboard())
    await state.set_state(AdminStates.broadcasting)

@dp.message(AdminStates.broadcasting)
async def process_broadcast(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    users = get_all_users()
    sent = 0
    failed = 0
    blocked = 0
    failed_users = []
    blocked_users = []

    for u in users:
        try:
            await bot.send_message(u[0], f"📢 Адмін: {message.text}")
            sent += 1
        except TelegramForbiddenError as e:
            blocked += 1
            failed += 1
            name = u[2]
            username = f"@{u[1]}" if u[1] else ""
            blocked_users.append(f"{name} {username} (ID:{u[0]})")
        except TelegramBadRequest as e:
            if "blocked" in str(e).lower():
                blocked += 1
                failed += 1
                name = u[2]
                username = f"@{u[1]}" if u[1] else ""
                blocked_users.append(f"{name} {username} (ID:{u[0]})")
            else:
                failed += 1
                name = u[2]
                username = f"@{u[1]}" if u[1] else ""
                failed_users.append(f"{name} {username} (ID:{u[0]})")
        except Exception:
            failed += 1
            name = u[2]
            username = f"@{u[1]}" if u[1] else ""
            failed_users.append(f"{name} {username} (ID:{u[0]})")

    stat_text = (
        f"✅ Розсилку завершено.\n\n"
        f"Доставлено: <b>{sent}</b>\n"
        f"Не доставлено: <b>{failed}</b>\n"
        f"Заблокували бота: <b>{blocked}</b>"
    )
    if blocked_users:
        stat_text += "\n\n<b>Заблокували бота:</b>\n" + "\n".join(blocked_users)
    if failed_users:
        stat_text += "\n\n<b>Не доставлено іншим користувачам:</b>\n" + "\n".join(failed_users)

    await message.answer(stat_text, parse_mode="HTML", reply_markup=admin_keyboard())
    await state.clear()

@dp.message(F.text == "📊 Статистика")
async def admin_stats(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    total_users, total_dialogs, active_dialogs, total_messages = get_stats()
    text = (
        f"📊 <b>Статистика бота</b>:\n\n"
        f"👥 Користувачів: <b>{total_users}</b>\n"
        f"💬 Діалогів всього: <b>{total_dialogs}</b>\n"
        f"🟢 Активних діалогів: <b>{active_dialogs}</b>\n"
        f"✉️ Повідомлень: <b>{total_messages}</b>"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=admin_keyboard())

@dp.message(F.text == "🏠 Головне меню")
async def admin_main_menu(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await state.clear()
    await message.answer("Повернуто у головне меню.", reply_markup=admin_keyboard())

@dp.message()
async def fallback(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id == ADMIN_ID:
        await message.answer("Оберіть дію в меню.", reply_markup=admin_keyboard())
        return

    dialog = get_active_dialog(user_id)
    if dialog:
        await state.set_state(UserStates.in_dialog)
        await user_dialog_message(message, state)
    else:
        start_dialog(user_id, ADMIN_ID, message.from_user.username, message.from_user.full_name)
        await state.set_state(UserStates.in_dialog)
        dialog = get_active_dialog(user_id)
        dialog_id, _ = dialog
        message_db_id = save_message(
            user_id=user_id,
            username=message.from_user.username,
            full_name=message.from_user.full_name,
            message_text=message.text,
            is_from_admin=False,
            dialog_id=dialog_id
        )
        await send_user_message_to_admin(user_id, message.from_user.full_name, message.text, dialog_id, message_db_id)
        await message.answer("✅ Ваше повідомлення надіслано адміністратору!", reply_markup=dialog_keyboard())

async def main():
    init_db()
    print("🚀 Consultant Bot запущено!")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
