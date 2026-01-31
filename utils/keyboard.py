# utils/keyboard.py
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton

def main_menu(is_admin: bool):
    buttons = [
        [KeyboardButton(text="📋 Мои задачи")]
    ]
    if is_admin:
        buttons.append([KeyboardButton(text="👨‍💼 Админ-панель")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def task_list_buttons(tasks):
    buttons = []
    for i, t in enumerate(tasks, 1):
        text = f"{i}. {t.practice_name or t.description[:20]} ({t.end_date})"
        buttons.append([InlineKeyboardButton(text=text, callback_data=f"task_{t.id}")])
    buttons.append([InlineKeyboardButton(text="◀ Назад", callback_data="back_to_main")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def task_actions(task_id):
    status_btns = [
        InlineKeyboardButton(text="👀 ещё не смотрел", callback_data=f"status_{task_id}_ещё не смотрел"),
        InlineKeyboardButton(text="⚙️ в работе", callback_data=f"status_{task_id}_в работе"),
        InlineKeyboardButton(text="✅ просмотренно", callback_data=f"status_{task_id}_просмотренно"),
        InlineKeyboardButton(text="✔️ готово", callback_data=f"status_{task_id}_готово"),
    ]
    remind_btns = [
        InlineKeyboardButton(text="⏰ Через 1 день", callback_data=f"remind_{task_id}_1d"),
        InlineKeyboardButton(text="📅 Через 3 дня", callback_data=f"remind_{task_id}_3d"),
        InlineKeyboardButton(text="📆 Через неделю", callback_data=f"remind_{task_id}_1w"),
    ]
    return InlineKeyboardMarkup(inline_keyboard=[
        status_btns,
        remind_btns,
        [InlineKeyboardButton(text="◀ Назад", callback_data=f"back_task_{task_id}")]
    ])

def admin_panel():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить задачу вручную", callback_data="add_task")],
        [InlineKeyboardButton(text="📤 Загрузить Excel", callback_data="upload_excel")],
        [InlineKeyboardButton(text="📥 Выгрузить все задачи", callback_data="export_all")],
        [InlineKeyboardButton(text="📧 Написать пользователю", callback_data="send_message")],
        [InlineKeyboardButton(text="👁️ Посмотреть задачи пользователя", callback_data="view_user_tasks")],
        [InlineKeyboardButton(text="👑 Назначить админа", callback_data="set_admin")],
        [InlineKeyboardButton(text="◀ Назад", callback_data="back_to_main")],
    ])