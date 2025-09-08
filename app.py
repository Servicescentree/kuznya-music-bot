# ... (інші імпорти, класи, функції, і т.д.)

# --- Хендлери для адмінських кнопок ---
@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text == "📢 Розсилка")
def handle_admin_broadcast(message):
    bot.send_message(message.chat.id, "✍️ Відправте текст розсилки. Всі користувачі отримають це повідомлення.")

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
• Зберігання: In-Memory
• Рейт-лімітинг: {config.RATE_LIMIT_MESSAGES} повідомлень/хвилину"""
    bot.send_message(message.chat.id, stats_text, parse_mode='Markdown')

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
