# handlers/user.py
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from db import SessionLocal, Task, User
from utils.keyboard import task_list_buttons, task_actions
from datetime import datetime, timedelta
from utils.reminder_scheduler import scheduler

router = Router()

@router.message(F.text == "📋 Мои задачи")
async def my_tasks(message: Message):
    session = SessionLocal()
    user = session.query(User).filter(User.tg_user_id == message.from_user.id).first()
    if not user:
        await message.answer("Сначала зарегистрируйтесь через /start")
        return
    tasks = session.query(Task).filter(Task.user_id == user.id).all()
    if not tasks:
        await message.answer("У вас нет задач.")
        return
    await message.answer("Ваши задачи:", reply_markup=task_list_buttons(tasks))

@router.callback_query(F.data.startswith("task_"))
async def show_task_detail(callback: CallbackQuery):
    task_id = int(callback.data.split("_")[1])
    session = SessionLocal()
    task = session.query(Task).filter(Task.id == task_id).first()
    if not task:
        await callback.answer("Задача не найдена")
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

@router.callback_query(F.data.startswith("status_"))
async def update_status(callback: CallbackQuery):
    _, task_id, status = callback.data.split("_", 2)
    task_id = int(task_id)
    session = SessionLocal()
    task = session.query(Task).filter(Task.id == task_id).first()
    if task:
        task.status = status
        task.updated_at = datetime.utcnow()
        session.commit()
        await callback.answer(f"Статус изменён на: {status}")
        await callback.message.edit_reply_markup(reply_markup=task_actions(task.id))

@router.callback_query(F.data.startswith("remind_"))
async def set_reminder(callback: CallbackQuery):
    parts = callback.data.split("_")
    task_id = int(parts[1])
    period = parts[2]
    session = SessionLocal()
    task = session.query(Task).filter(Task.id == task_id).first()
    if not task:
        await callback.answer("Задача не найдена")
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
        return

    task.next_reminder = dt
    session.commit()

    # Перезапланировать job
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