# utils/reminder_scheduler.py
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime, timedelta
from aiogram import Bot
from sqlalchemy import create_engine
from db import SessionLocal, Task, User
import asyncio

scheduler = AsyncIOScheduler()

async def send_reminder(bot: Bot, task_id: int):
    session = SessionLocal()
    task = session.query(Task).filter(Task.id == task_id).first()
    if not task or task.status == "готово":
        session.close()
        return

    user = session.query(User).filter(User.id == task.user_id).first()
    if not user:
        session.close()
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
    except Exception as e:
        print(f"Ошибка отправки напоминания пользователю {user.tg_user_id}: {e}")

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
            args=[bot, task.id],  # исправлено: task.id, а не task.user_id
            id=f"remind_{task.id}",
            replace_existing=True
        )
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
            args=[bot, task.id],  # исправлено: bot передается
            id=f"remind_{task.id}",
            replace_existing=True
        )
    session.close()