# handlers/common.py
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from db import SessionLocal, User, Task
from utils.keyboard import main_menu
from states import AdminAddTask
from aiogram.fsm.context import FSMContext

router = Router()

@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    session = SessionLocal()
    user = session.query(User).filter(User.tg_user_id == message.from_user.id).first()

    if user:
        await message.answer("Добро пожаловать!", reply_markup=main_menu(user.is_admin))
        await state.clear()
    else:
        await message.answer("Введите своё ФИО (например: Иванов И.И.):")
        await state.set_state(AdminAddTask.waiting_full_name)  # переиспользуем FSM для регистрации

@router.message(AdminAddTask.waiting_full_name)
async def register_user(message: Message, state: FSMContext):
    full_name = message.text.strip()
    session = SessionLocal()
    user = session.query(User).filter(User.full_name == full_name).first()
    if user and user.tg_user_id != message.from_user.id:
        await message.answer("⚠️ ФИО уже занято. Уточните ФИО или обратитесь к администратору.")
        return
    new_user = User(
        tg_user_id=message.from_user.id,
        full_name=full_name,
        tg_username=message.from_user.username,
        phone=message.contact.phone_number if hasattr(message, 'contact') else None,
        is_admin=False
    )
    session.add(new_user)
    session.commit()
    await message.answer("Регистрация завершена!", reply_markup=main_menu(False))
    await state.clear()