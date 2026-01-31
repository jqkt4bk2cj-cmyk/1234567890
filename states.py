# states.py
from aiogram.fsm.state import StatesGroup, State

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