# bot.py
import os
import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from aiogram import Bot, Dispatcher, types
from aiogram.types import Message, CallbackQuery, FSInputFile, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram import Router
from sqlalchemy import create_engine, Column, Integer, String, Date, DateTime, Boolean, ForeignKey, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from openpyxl import Workbook, load_workbook
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv

# === LOGGING SETUP ===
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

# === DATABASE ===
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    tg_user_id = Column(Integer, unique=True, nullable=False)
    full_name = Column(String, nullable=False)
    tg_username = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime, default=func.now())

class Task(Base):
    __tablename__ = "tasks"
    id = Column(Integer, primary_key=True)
    practice_name = Column(String, nullable=True)
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    description = Column(String, nullable=True)
    status = Column(String, default="ещё не смотрел")  # enum: ещё не смотрел | в работе | просмотренно | готово
    next_reminder = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="tasks")

User.tasks = relationship("Task", back_populates="user")

engine = create_engine("sqlite:///practice_bot.db", echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    Base.metadata.create_all(engine)

# === FSM STATES ===
class AdminAddTask(StatesGroup):
    waiting_full_name = State()
    waiting_practice_name = State()
    waiting_end_date = State()
    waiting_description = State()

class AdminSendMessage(StatesGroup):
    waiting_recipient_full_name = State()
    waiting_message_text = State()

class AdminSetAdmin(StatesGroup):
    waiting_target_full_name = State()

class RegistrationState(StatesGroup):
    waiting_full_name = State()

# === EXCEL PARSER ===
def parse_date(date_str: str) -> Optional[datetime.date]:
    if not date_str:
        return None
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue
    return None

def parse_excel(file_path: str) -> List[Dict]:
    wb = load_workbook(file_path)
    ws = wb.active
    headers = [cell.value for cell in ws[1]]

    rows = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        data = dict(zip(headers, row))
        rows.append(data)

    tasks = []

    # Определяем формат
    if "practice_name" in headers and "full_name" in headers and "end_date" in headers:
        # Формат 1: Полный
        for r in rows:
            task = {
                "practice_name": r.get("practice_name"),
                "start_date": parse_date(r.get("start_date")),
                "end_date": parse_date(r.get("end_date")),
                "full_name": r.get("full_name"),
                "tg_username": r.get("tg_username"),
                "phone": r.get("phone"),
                "description": r.get("task_description") or r.get("practice_name") or "",
            }
            tasks.append(task)
    elif "full_name" in headers and "task_description" in headers and "end_date" in headers:
        # Формат 2: Краткий
        for r in rows:
            task = {
                "practice_name": r.get("task_description"),
                "start_date": None,
                "end_date": parse_date(r.get("end_date")),
                "full_name": r.get("full_name"),
                "tg_username": None,
                "phone": None,
                "description": r.get("task_description"),
            }
            tasks.append(task)
    else:
        raise ValueError("Неизвестный формат Excel")

    return tasks

# === KEYBOARDS ===
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
       
        [InlineKeyboardButton(text="◀ Назад", callback_data="back_to_main")],
    ])

# === REMINDER SCHEDULER ===
scheduler = AsyncIOScheduler()

async def send_reminder(bot: Bot, task_id: int):
    session = SessionLocal()
    task = session.query(Task).filter(Task.id == task_id).first()
    if not task or task.status == "готово":
        session.close()
        logger.info(f"Reminder skipped for task {task_id}, status: {task.status if task else 'not found'}")
        return

    user = session.query(User).filter(User.id == task.user_id).first()
    if not user:
        session.close()
        logger.warning(f"User not found for task {task_id}")
        return

    msg = (
        f"🔔 Напоминание: {task.practice_name or 'Задача'}\n"
        f"Описание: {task.description}\n"
        f"Срок: {task.end_date}\n\n"
        f"Статус: {task.status}\n"
        f"Напоминание повторяется еженедельно, пока задача не будет отмечена как «готово»."
    )

    try:
        await bot.send_message(user.tg_user_id, msg)
        logger.info(f"Reminder sent to {user.full_name} for task {task_id}")
    except Exception as e:
        logger.error(f"Error sending reminder to user {user.tg_user_id}: {e}")

    # Обновляем следующее напоминание (через неделю), если статус ≠ готово
    if task.status != "готово":
        new_reminder = datetime.combine(task.end_date, datetime.min.time()) - timedelta(days=7)
        if new_reminder < datetime.now():
            new_reminder = datetime.now() + timedelta(weeks=1)
        task.next_reminder = new_reminder
        session.commit()

        scheduler.add_job(
            send_reminder,
            'date',
            run_date=new_reminder,
            args=[bot, task.id],
            id=f"remind_{task.id}",
            replace_existing=True
        )
        logger.info(f"Scheduled next reminder for task {task.id} at {new_reminder}")
    session.close()

def schedule_reminders(bot: Bot):
    session = SessionLocal()
    now = datetime.now()
    tasks = session.query(Task).filter(
        Task.next_reminder <= now,
        Task.status != "готово"
    ).all()

    for task in tasks:
        scheduler.add_job(
            send_reminder,
            'date',
            run_date=task.next_reminder,
            args=[bot, task.id],
            id=f"remind_{task.id}",
            replace_existing=True
        )
        logger.info(f"Scheduled reminder for task {task.id} at {task.next_reminder}")
    session.close()

# === HANDLERS ===
router = Router()

@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    logger.info(f"User {message.from_user.id} ({message.from_user.full_name}) started bot")
    session = SessionLocal()
    user = session.query(User).filter(User.tg_user_id == message.from_user.id).first()

    if user:
        await message.answer("Добро пожаловать!", reply_markup=main_menu(user.is_admin))
        await state.clear()
        logger.info(f"Welcome message sent to {user.full_name}")
    else:
        await message.answer("Введите своё ФИО (например: Иванов И.И.):")
        await state.set_state(RegistrationState.waiting_full_name)
        logger.info("Asking for full name for registration")

@router.message(RegistrationState.waiting_full_name)
async def register_user(message: Message, state: FSMContext):
    full_name = message.text.strip()
    logger.info(f"User {message.from_user.id} entered full name: {full_name}")
    session = SessionLocal()

    # Проверяем, зарегистрирован ли уже пользователь с этим tg_user_id
    existing_user = session.query(User).filter(User.tg_user_id == message.from_user.id).first()

    if existing_user:
        # Если пользователь уже есть, просто обновляем его ФИО, если оно изменилось
        old_name = existing_user.full_name
        existing_user.full_name = full_name
        session.commit()
        await message.answer(
            f"✅ Ваши данные обновлены: {full_name}",
            reply_markup=main_menu(existing_user.is_admin)
        )
        logger.info(f"Updated user {existing_user.tg_user_id} name from '{old_name}' to '{full_name}'")
        await state.clear()
        session.close()
        return

    # Проверяем, не занят ли ФИО кем-то другим
    user_with_same_name = session.query(User).filter(User.full_name == full_name).first()
    if user_with_same_name and user_with_same_name.tg_user_id != message.from_user.id:
        await message.answer("⚠️ ФИО уже занято другим пользователем.")
        logger.warning(f"User {message.from_user.id} tried to register with duplicate name: {full_name}")
        session.close()
        return

    # Создаем нового пользователя
    new_user = User(
        tg_user_id=message.from_user.id,
        full_name=full_name,
        tg_username=message.from_user.username,
        phone=getattr(message.contact, 'phone_number', None),
        is_admin=False  # Не делать админом при регистрации!
    )
    session.add(new_user)
    session.commit()
    logger.info(f"New user registered: {full_name}, ID: {message.from_user.id}")
    session.close()

    await message.answer("✅ Регистрация завершена!", reply_markup=main_menu(False))
    await state.clear()

@router.message(lambda m: m.text == "📋 Мои задачи")
async def my_tasks(message: Message):
    session = SessionLocal()
    user = session.query(User).filter(User.tg_user_id == message.from_user.id).first()
    if not user:
        await message.answer("Сначала зарегистрируйтесь через /start")
        logger.warning(f"User {message.from_user.id} tried to access tasks without registration")
        return
    tasks = session.query(Task).filter(Task.user_id == user.id).all()
    if not tasks:
        await message.answer("У вас нет задач.")
        logger.info(f"No tasks found for user {user.full_name}")
    else:
        await message.answer("Ваши задачи:", reply_markup=task_list_buttons(tasks))
        logger.info(f"Sent task list to user {user.full_name}, count: {len(tasks)}")
    session.close()

@router.callback_query(lambda c: c.data.startswith("task_"))
async def show_task_detail(callback: CallbackQuery):
    task_id = int(callback.data.split("_")[1])
    session = SessionLocal()
    task = session.query(Task).filter(Task.id == task_id).first()
    if not task:
        await callback.answer("Задача не найдена")
        logger.warning(f"Task {task_id} not found")
        return
    user = session.query(User).filter(User.id == task.user_id).first()
    msg = (
        f"📌 {task.practice_name or 'Без названия'}\n"
        f"Описание: {task.description}\n"
        f"Срок: {task.end_date}\n"
        f"Статус: {task.status}\n"
        f"След. напоминание: {task.next_reminder or '—'}"
    )
    await callback.message.edit_text(msg, reply_markup=task_actions(task.id))
    logger.info(f"Task detail shown: {task_id}, status: {task.status}")
    session.close()

@router.callback_query(lambda c: c.data.startswith("status_"))
async def update_status(callback: CallbackQuery):
    _, task_id, status = callback.data.split("_", 2)
    task_id = int(task_id)
    session = SessionLocal()
    task = session.query(Task).filter(Task.id == task_id).first()
    if task:
        old_status = task.status
        task.status = status
        task.updated_at = datetime.utcnow()
        session.commit()
        await callback.answer(f"Статус изменён на: {status}")
        await callback.message.edit_reply_markup(reply_markup=task_actions(task.id))
        logger.info(f"Status updated for task {task_id}: {old_status} → {status}")
    session.close()

@router.callback_query(lambda c: c.data.startswith("remind_"))
async def set_reminder(callback: CallbackQuery):
    parts = callback.data.split("_")
    task_id = int(parts[1])
    period = parts[2]
    session = SessionLocal()
    task = session.query(Task).filter(Task.id == task_id).first()
    if not task:
        await callback.answer("Задача не найдена")
        logger.warning(f"Reminder requested for non-existent task {task_id}")
        return

    now = datetime.now()
    if period == "1d":
        dt = now + timedelta(days=1)
    elif period == "3d":
        dt = now + timedelta(days=3)
    elif period == "1w":
        dt = now + timedelta(weeks=1)
    else:
        await callback.answer("Неизвестный период")
        logger.warning(f"Unknown reminder period: {period}")
        return

    task.next_reminder = dt
    session.commit()

    job_id = f"remind_{task_id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
    scheduler.add_job(
        send_reminder,
        'date',
        run_date=dt,
        args=[callback.bot, task_id],
        id=job_id,
        replace_existing=True
    )

    await callback.answer(f"Напоминание установлено на: {dt.strftime('%d.%m %H:%M')}")
    logger.info(f"Manual reminder scheduled for task {task_id} at {dt}")
    session.close()

@router.message(lambda m: m.text == "👨‍💼 Админ-панель")
async def admin_panel_cmd(message: Message):
    session = SessionLocal()
    user = session.query(User).filter(User.tg_user_id == message.from_user.id).first()
    session.close()

    if not user or not user.is_admin:
        await message.answer("❌ У вас нет прав администратора.")
        logger.warning(f"User {message.from_user.id} tried to access admin panel without permission")
        return

    await message.answer("🔧 Админ-панель:", reply_markup=admin_panel())
    logger.info(f"Admin panel opened for user {user.full_name}")

@router.callback_query(lambda c: c.data == "back_to_main")
async def back_to_main(callback: CallbackQuery):
    session = SessionLocal()
    user = session.query(User).filter(User.tg_user_id == callback.from_user.id).first()
    session.close()

    if user:
        await callback.message.edit_text("Главное меню:", reply_markup=main_menu(user.is_admin))
        logger.info(f"Back to main menu for user {user.full_name}")
    else:
        await callback.message.edit_text("Вы не авторизованы.")

# --- АДМИНКА ---

@router.callback_query(lambda c: c.data == "add_task")
async def start_add_task(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите ФИО преподавателя:")
    await state.set_state(AdminAddTask.waiting_full_name)
    logger.info(f"Admin {callback.from_user.id} started adding task manually")

@router.message(AdminAddTask.waiting_full_name)
async def admin_enter_full_name(message: Message, state: FSMContext):
    """
    FSM: Админ вводит ФИО преподавателя при добавлении задачи.
    Не регистрирует пользователя, просто сохраняет в состояние.
    """
    await state.update_data(full_name=message.text)
    await message.answer("Введите название практики:")
    await state.set_state(AdminAddTask.waiting_practice_name)
    logger.info(f"Admin entered teacher name: {message.text}")

@router.message(AdminAddTask.waiting_practice_name)
async def get_practice_name(message: Message, state: FSMContext):
    await state.update_data(practice_name=message.text)
    await message.answer("Введите дату окончания (ДД.ММ.ГГГГ):")
    await state.set_state(AdminAddTask.waiting_end_date)
    logger.info(f"Admin entered practice name: {message.text}")

@router.message(AdminAddTask.waiting_end_date)
async def get_end_date(message: Message, state: FSMContext):
    end_date = parse_date(message.text)
    if not end_date:
        await message.answer("❌ Неверный формат даты. Попробуйте ещё раз (ДД.ММ.ГГГГ).")
        logger.warning(f"Invalid date format entered by admin: {message.text}")
        return
    await state.update_data(end_date=end_date)
    await message.answer("Введите описание задачи:")
    await state.set_state(AdminAddTask.waiting_description)
    logger.info(f"Admin entered end date: {end_date}")

@router.message(AdminAddTask.waiting_description)
async def save_task(message: Message, state: FSMContext):
    data = await state.get_data()
    session = SessionLocal()

    # Найти пользователя по ФИО
    user = session.query(User).filter(User.full_name == data["full_name"]).first()
    if not user:
        # Если нет — создать "заглушку" без tg_user_id
        user = User(tg_user_id=0, full_name=data["full_name"], is_admin=False)
        session.add(user)
        session.commit()
        logger.info(f"Created stub user for task: {data['full_name']}")
    # Если есть — использовать существующего

    # Проверить дубликат задачи
    existing = session.query(Task).filter(
        Task.user_id == user.id,
        Task.practice_name == data["practice_name"],
        Task.end_date == data["end_date"]
    ).first()

    if existing:
        await message.answer("⚠️ Такая задача уже существует для этого преподавателя.")
        logger.warning(f"Duplicate task attempt for {data['full_name']}: {data['practice_name']}")
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
    logger.info(f"Task added: {task.practice_name} for {user.full_name}")
    session.close()

    await message.answer("✅ Задача успешно добавлена!")
    await state.clear()

@router.callback_query(lambda c: c.data == "upload_excel")
async def ask_for_excel_upload(callback: CallbackQuery):
    await callback.message.answer("Отправьте файл Excel с задачами (в любом из двух форматов).")
    logger.info(f"Admin {callback.from_user.id} initiated Excel upload")

@router.message(lambda m: m.document)
async def handle_excel_upload(message: Message):
    session = SessionLocal()
    user = session.query(User).filter(User.tg_user_id == message.from_user.id).first()
    if not user or not user.is_admin:
        session.close()
        await message.answer("❌ У вас нет прав администратора.")
        logger.warning(f"Non-admin {message.from_user.id} tried to upload Excel")
        return
    session.close()

    file_info = await message.bot.get_file(message.document.file_id)
    file_path = f"temp_{message.document.file_id}.xlsx"
    await message.bot.download_file(file_info.file_path, file_path)
    logger.info(f"Excel file downloaded: {file_path}")

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
                logger.info(f"Created stub user from Excel: {t_data['full_name']}")

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
                logger.info(f"Added task from Excel: {task.practice_name} for {user_obj.full_name}")
            else:
                logger.info(f"Skipped duplicate task from Excel: {t_data['practice_name']} for {t_data['full_name']}")

        session.commit()
        session.close()
        await message.answer(f"✅ Загружено {added_count} новых задач из Excel.")
        logger.info(f"Excel upload completed, {added_count} tasks added")
    except ValueError as ve:
        await message.answer(f"❌ Ошибка формата Excel: {ve}")
        logger.error(f"Excel format error: {ve}")
    except Exception as e:
        await message.answer(f"❌ Ошибка при загрузке: {e}")
        logger.error(f"Excel upload error: {e}")
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)
            logger.info(f"Temporary Excel file removed: {file_path}")

@router.callback_query(lambda c: c.data == "export_all")
async def export_all(callback: CallbackQuery):
    session = SessionLocal()
    tasks = session.query(Task).all()
    logger.info(f"Exporting all tasks, total count: {len(tasks)}")

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
    logger.info(f"Tasks exported to Excel and sent to admin {callback.from_user.id}")

# --- Остальные админ-функции также логируются ---

@router.callback_query(lambda c: c.data == "set_admin")
async def start_set_admin(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите ФИО пользователя, чтобы сделать его администратором:")
    await state.set_state(AdminSetAdmin.waiting_target_full_name)
    logger.info(f"Admin {callback.from_user.id} started promoting user to admin")

@router.message(AdminSetAdmin.waiting_target_full_name)
async def confirm_set_admin(message: Message, state: FSMContext):
    target_name = message.text.strip()
    session = SessionLocal()

    users = session.query(User).filter(User.full_name.contains(target_name)).all()

    if not users:
        await message.answer("❌ Пользователь не найден.")
        logger.warning(f"Admin {message.from_user.id} tried to promote non-existent user: {target_name}")
        await state.clear()
        session.close()
        return

    if len(users) > 1:
        names = "\n".join([f"• {u.full_name}" for u in users])
        await message.answer(f"⚠️ Найдено несколько пользователей:\n{names}\n\nВведите точное ФИО.")
        logger.warning(f"Multiple users found for promotion: {target_name}")
        await state.clear()
        session.close()
        return

    user = users[0]
    await message.answer(f"👤 Найден пользователь: {user.full_name}\n\nПодтвердите действие: сделать администратором? (да/нет)")
    await state.update_data(target_user_id=user.id)
    session.close()
    logger.info(f"Found user for promotion: {user.full_name}")

@router.message(AdminSetAdmin.waiting_target_full_name)
async def finish_set_admin(message: Message, state: FSMContext):
    if message.text.lower() not in ["да", "yes", "y"]:
        await message.answer("❌ Действие отменено.")
        logger.info(f"Admin {message.from_user.id} cancelled admin promotion")
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
        logger.info(f"User {user.full_name} promoted to admin by {message.from_user.id}")
    else:
        await message.answer("❌ Пользователь не найден.")
        logger.error(f"Could not find user {user_id} to promote to admin")

    session.close()
    await state.clear()

# --- MAIN ===
async def main():
    init_db()
    scheduler.start()
    logger.info("Bot started")
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())