# handlers/admin.py
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from db import SessionLocal, User, Task
from utils.excel_parser import parse_excel
from utils.keyboard import admin_panel
from states import AdminAddTask, AdminSendMessage, AdminSetAdmin
from openpyxl import Workbook
from datetime import datetime, timedelta
import os

router = Router()

# --- АДМИНКА ---

@router.message(F.text == "👨‍💼 Админ-панель")
async def admin_panel_cmd(message: Message):
    session = SessionLocal()
    user = session.query(User).filter(User.tg_user_id == message.from_user.id).first()
    session.close()

    if not user or not user.is_admin:
        await message.answer("❌ У вас нет прав администратора.")
        return

    await message.answer("🔧 Админ-панель:", reply_markup=admin_panel())

@router.callback_query(F.data == "back_to_main")
async def back_to_main(callback: CallbackQuery):
    session = SessionLocal()
    user = session.query(User).filter(User.tg_user_id == callback.from_user.id).first()
    session.close()

    if user:
        from utils.keyboard import main_menu
        await callback.message.edit_text("Главное меню:", reply_markup=main_menu(user.is_admin))
    else:
        await callback.message.edit_text("Вы не авторизованы.")

# --- ДОБАВЛЕНИЕ ЗАДАЧИ ВРУЧНУЮ ---

@router.callback_query(F.data == "add_task")
async def start_add_task(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите ФИО преподавателя:")
    await state.set_state(AdminAddTask.waiting_full_name)

@router.message(AdminAddTask.waiting_full_name)
async def get_full_name(message: Message, state: FSMContext):
    await state.update_data(full_name=message.text)
    await message.answer("Введите название практики:")
    await state.set_state(AdminAddTask.waiting_practice_name)

@router.message(AdminAddTask.waiting_practice_name)
async def get_practice_name(message: Message, state: FSMContext):
    await state.update_data(practice_name=message.text)
    await message.answer("Введите дату окончания (ДД.ММ.ГГГГ):")
    await state.set_state(AdminAddTask.waiting_end_date)

@router.message(AdminAddTask.waiting_end_date)
async def get_end_date(message: Message, state: FSMContext):
    from utils.excel_parser import parse_date
    end_date = parse_date(message.text)
    if not end_date:
        await message.answer("❌ Неверный формат даты. Попробуйте ещё раз (ДД.ММ.ГГГГ).")
        return
    await state.update_data(end_date=end_date)
    await message.answer("Введите описание задачи:")
    await state.set_state(AdminAddTask.waiting_description)

@router.message(AdminAddTask.waiting_description)
async def save_task(message: Message, state: FSMContext):
    data = await state.get_data()
    session = SessionLocal()

    # Найти или создать пользователя
    user = session.query(User).filter(User.full_name == data["full_name"]).first()
    if not user:
        user = User(tg_user_id=0, full_name=data["full_name"], is_admin=False)
        session.add(user)
        session.commit()

    # Проверить дубликат
    existing = session.query(Task).filter(
        Task.user_id == user.id,
        Task.practice_name == data["practice_name"],
        Task.end_date == data["end_date"]
    ).first()

    if existing:
        await message.answer("⚠️ Такая задача уже существует для этого преподавателя.")
        await state.clear()
        session.close()
        return

    # Создать задачу
    task = Task(
        practice_name=data["practice_name"],
        start_date=None,
        end_date=data["end_date"],
        user_id=user.id,
        description=message.text,
        status="ещё не смотрел",
        next_reminder=data["end_date"] - timedelta(days=7)
    )
    session.add(task)
    session.commit()
    session.close()

    await message.answer("✅ Задача успешно добавлена!")
    await state.clear()

# --- ЗАГРУЗКА EXCEL ---

@router.callback_query(F.data == "upload_excel")
async def ask_for_excel_upload(callback: CallbackQuery):
    await callback.message.answer("Отправьте файл Excel с задачами (в любом из двух форматов).")

@router.message(F.document)
async def handle_excel_upload(message: Message):
    session = SessionLocal()
    user = session.query(User).filter(User.tg_user_id == message.from_user.id).first()
    if not user or not user.is_admin:
        session.close()
        await message.answer("❌ У вас нет прав администратора.")
        return
    session.close()

    file_info = await message.bot.get_file(message.document.file_id)
    file_path = f"temp_{message.document.file_id}.xlsx"
    await message.bot.download_file(file_info.file_path, file_path)

    try:
        tasks_data = parse_excel(file_path)
        session = SessionLocal()

        added_count = 0
        for t_data in tasks_data:
            user_obj = session.query(User).filter(User.full_name == t_data["full_name"]).first()
            if not user_obj:
                user_obj = User(tg_user_id=0, full_name=t_data["full_name"], is_admin=False)
                session.add(user_obj)
                session.commit()

            # Проверка дубликата
            existing = session.query(Task).filter(
                Task.user_id == user_obj.id,
                Task.practice_name == t_data["practice_name"],
                Task.end_date == t_data["end_date"]
            ).first()

            if not existing:
                task = Task(
                    practice_name=t_data["practice_name"],
                    start_date=t_data["start_date"],
                    end_date=t_data["end_date"],
                    user_id=user_obj.id,
                    description=t_data["description"],
                    status="ещё не смотрел",
                    next_reminder=t_data["end_date"] - timedelta(days=7) if t_data["end_date"] else None
                )
                session.add(task)
                added_count += 1

        session.commit()
        session.close()
        await message.answer(f"✅ Загружено {added_count} новых задач из Excel.")
    except ValueError as ve:
        await message.answer(f"❌ Ошибка формата Excel: {ve}")
    except Exception as e:
        await message.answer(f"❌ Ошибка при загрузке: {e}")
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)

# --- ВЫГРУЗКА ВСЕХ ЗАДАЧ ---

@router.callback_query(F.data == "export_all")
async def export_all(callback: CallbackQuery):
    session = SessionLocal()
    tasks = session.query(Task).all()

    wb = Workbook()
    ws = wb.active
    ws.title = "Все задачи"
    ws.append([
        "practice_name", "start_date", "end_date", "full_name", "tg_username", "phone",
        "task_description", "status", "next_reminder"
    ])

    for t in tasks:
        user = session.query(User).filter(User.id == t.user_id).first()
        ws.append([
            t.practice_name or "",
            t.start_date or "",
            t.end_date,
            user.full_name if user else "",
            user.tg_username if user else "",
            user.phone if user else "",
            t.description,
            t.status,
            t.next_reminder.strftime("%Y-%m-%d %H:%M") if t.next_reminder else ""
        ])

    file_path = "all_tasks.xlsx"
    wb.save(file_path)

    await callback.bot.send_document(callback.from_user.id, FSInputFile(file_path))
    os.remove(file_path)
    await callback.answer("📥 Файл задач выгружен.")

# --- НАЗНАЧЕНИЕ АДМИНА ---

@router.callback_query(F.data == "set_admin")
async def start_set_admin(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите ФИО пользователя, чтобы сделать его администратором:")
    await state.set_state(AdminSetAdmin.waiting_target_full_name)

@router.message(AdminSetAdmin.waiting_target_full_name)
async def confirm_set_admin(message: Message, state: FSMContext):
    target_name = message.text.strip()
    session = SessionLocal()

    users = session.query(User).filter(User.full_name.contains(target_name)).all()

    if not users:
        await message.answer("❌ Пользователь не найден.")
        await state.clear()
        session.close()
        return

    if len(users) > 1:
        names = "\n".join([f"• {u.full_name}" for u in users])
        await message.answer(f"⚠️ Найдено несколько пользователей:\n{names}\n\nВведите точное ФИО.")
        await state.clear()
        session.close()
        return

    user = users[0]
    await message.answer(f"👤 Найден пользователь: {user.full_name}\n\nПодтвердите действие: сделать администратором? (да/нет)")
    await state.update_data(target_user_id=user.id)
    session.close()

@router.message(AdminSetAdmin.waiting_target_full_name)
async def finish_set_admin(message: Message, state: FSMContext):
    if message.text.lower() not in ["да", "yes", "y"]:
        await message.answer("❌ Действие отменено.")
        await state.clear()
        return

    data = await state.get_data()
    user_id = data["target_user_id"]

    session = SessionLocal()
    user = session.query(User).filter(User.id == user_id).first()
    if user:
        user.is_admin = True
        session.commit()
        await message.answer(f"✅ Пользователь {user.full_name} теперь администратор.")
    else:
        await message.answer("❌ Пользователь не найден.")

    session.close()
    await state.clear()

# --- ПРОСМОТР ЗАДАЧ ПОЛЬЗОВАТЕЛЯ ---

@router.callback_query(F.data == "view_user_tasks")
async def start_view_user_tasks(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите ФИО преподавателя, чтобы посмотреть его задачи:")
    await state.set_state(AdminSetAdmin.waiting_target_full_name)

@router.message(AdminSetAdmin.waiting_target_full_name)
async def show_user_tasks(message: Message, state: FSMContext):
    full_name = message.text.strip()
    session = SessionLocal()

    user = session.query(User).filter(User.full_name.contains(full_name)).first()
    if not user:
        await message.answer("❌ Пользователь не найден.")
        session.close()
        await state.clear()
        return

    tasks = session.query(Task).filter(Task.user_id == user.id).all()
    if not tasks:
        await message.answer(f"У пользователя {user.full_name} нет задач.")
        session.close()
        await state.clear()
        return

    task_list = "\n".join([
        f"• {t.practice_name or 'Без названия'} ({t.status}) - до {t.end_date}"
        for t in tasks
    ])
    await message.answer(f"Задачи пользователя {user.full_name}:\n\n{task_list}")

    session.close()
    await state.clear()

# --- ОТПРАВКА СООБЩЕНИЯ ПОЛЬЗОВАТЕЛЮ ---

@router.callback_query(F.data == "send_message")
async def start_send_message(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите ФИО получателя:")
    await state.set_state(AdminSendMessage.waiting_recipient_full_name)

@router.message(AdminSendMessage.waiting_recipient_full_name)
async def get_message_text(message: Message, state: FSMContext):
    session = SessionLocal()
    user = session.query(User).filter(User.full_name.contains(message.text)).first()
    session.close()

    if not user or not user.tg_user_id:
        await message.answer("❌ Пользователь не найден или не зарегистрирован в Telegram.")
        await state.clear()
        return

    await state.update_data(recipient_id=user.tg_user_id)
    await message.answer("Введите текст сообщения:")
    await state.set_state(AdminSendMessage.waiting_message_text)

@router.message(AdminSendMessage.waiting_message_text)
async def send_message_to_user(message: Message, state: FSMContext):
    data = await state.get_data()
    recipient_id = data["recipient_id"]
    text = message.text

    try:
        await message.bot.send_message(recipient_id, f"[Сообщение от администратора]\n\n{text}")
        await message.answer("✅ Сообщение отправлено.")
    except Exception:
        await message.answer("❌ Не удалось отправить сообщение.")

    await state.clear()

# === Регистрация роутера ===
def register_admin_handlers(dp):
    dp.include_router(router)