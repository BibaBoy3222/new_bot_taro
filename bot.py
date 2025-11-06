import asyncio
import sqlite3
from datetime import datetime, date, timezone

from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder


# 1. ВСТАВЬ СВОЙ ТОКЕН СЮДА
API_TOKEN = "7662481854:AAE7WzZaIbzCEmi5qXY37C0dErxej4uXWA4"

# сюда tg-id таролога, которому будет прилетать анкета
TAROLOG_ID = 7109352431  # поменяй на настоящий id
# если есть username таролога, укажи — дадим кнопку пользователю
TAROLOG_USERNAME = "whatthebiba588"  # без @, можно оставить пустым ""

# ================= БАЗА =================
conn = sqlite3.connect("bot_leads.db")
conn.row_factory = sqlite3.Row

conn.execute("""
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id INTEGER UNIQUE,
    name TEXT,
    birth_date TEXT
)
""")
conn.commit()


def get_user_by_tg(tg_id: int):
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE tg_id = ?", (tg_id,))
    return cur.fetchone()


def create_or_update_user(tg_id: int, name: str | None = None, birth_date: str | None = None):
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE tg_id = ?", (tg_id,))
    row = cur.fetchone()
    if row:
        # обновим только то, что пришло
        if name is not None or birth_date is not None:
            cur.execute("""
                UPDATE users
                SET name = COALESCE(?, name),
                    birth_date = COALESCE(?, birth_date)
                WHERE tg_id = ?
            """, (name, birth_date, tg_id))
            conn.commit()
        return row["id"]
    else:
        cur.execute("INSERT INTO users (tg_id, name, birth_date) VALUES (?, ?, ?)",
                    (tg_id, name, birth_date))
        conn.commit()
        return cur.lastrowid


# ================= FSM =================
class LeadForm(StatesGroup):
    waiting_name = State()
    waiting_problem = State()
    waiting_birthdate = State()


# ================= РОУТЕРЫ =================
router = Router()


# ================= ВСПОМОГАТЕЛЬНЫЕ =================
def main_menu_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="📝 Заполнить мини-анкету снова", callback_data="start_form")
    if TAROLOG_USERNAME:
        kb.button(text="📩 Написать Елизавете", url=f"https://t.me/{TAROLOG_USERNAME}")
    kb.adjust(1)
    return kb.as_markup()


def to_tarolog_text(user_name: str, problem: str, birth_date: str | None, user_tg_id: int):
    # посчитаем возраст, если есть дата
    age_str = "не указано"
    if birth_date:
        try:
            dt = datetime.strptime(birth_date, "%d.%m.%Y").date()
            today = date.today()
            age = today.year - dt.year - ((today.month, today.day) < (dt.month, dt.day))
            age_str = f"{age} лет"
        except ValueError:
            pass

    profile_link = f"tg://user?id={user_tg_id}"
    return (
        "🔔 Новая анкета от пользователя\n"
        f"Имя: {user_name}\n"
        f"Возраст: {age_str}\n"
        f"Дата рождения: {birth_date or 'не указана'}\n"
        f"Запрос/проблема:\n{problem}\n"
        f"Профиль: {profile_link}"
    )


# ================= ХЕНДЛЕРЫ =================
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    user_row = get_user_by_tg(message.from_user.id)

    # если знаем пользователя — просто приветствуем
    if user_row and user_row["name"]:
        name = user_row["name"]
        await message.answer(
            f"Здравствуйте, {name}, меня зовут Елизавета, приятно познакомиться 🥰\n"
            "Рада снова вас видеть! Чем могу быть полезна сейчас?",
            reply_markup=main_menu_kb()
        )
        await state.clear()
        return

    # если не знаем — начнём с имени
    await message.answer("Давайте познакомимся 🌸\nКак вас зовут?")
    await state.set_state(LeadForm.waiting_name)


@router.callback_query(F.data == "start_form")
async def start_form_again(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("Хорошо, давайте ещё раз пройдём мини-анкету 💜\nКак вас зовут?")
    await state.set_state(LeadForm.waiting_name)
    await callback.answer()


@router.message(LeadForm.waiting_name)
async def get_name(message: Message, state: FSMContext):
    name = message.text.strip()
    # сохраним имя в БД сразу
    create_or_update_user(message.from_user.id, name=name)

    # отправляем "шапку"
    await message.answer(
        f"Здравствуйте, {name}, меня зовут Елизавета, приятно познакомиться 🥰\n\n"
        "Я очень хороший специалист в своей области, но работаю далеко не со всеми.\n"
        "Мне изначально важно понимать специфику проблем и вопросов, с которыми вы обращаетесь, "
        "чтобы я понимала, смогу ли я вам действительно помочь 🤲\n\n"
        "1️⃣ Расскажите чуть подробнее, с какими проблемами обращаетесь, что тревожит на данный момент?\n"
        "Можете написать текстом или записать голосовое, как вам комфортнее! "
        "Главное — не стесняйтесь, между нами всё строго конфиденциально 💖"
    )
    await state.update_data(name=name)
    await state.set_state(LeadForm.waiting_problem)


@router.message(LeadForm.waiting_problem, F.voice)
async def get_problem_voice(message: Message, state: FSMContext):
    # человек прислал голосовое
    file_id = message.voice.file_id
    problem_text = f"Пользователь отправил голосовое сообщение (file_id={file_id})"
    await state.update_data(problem=problem_text)
    await message.answer(
        "Спасибо, я сохранила 💜\n\n"
        "2️⃣ Теперь укажите, пожалуйста, вашу дату рождения в формате ДД.ММ.ГГГГ\n"
        "Например: 21.07.1995"
    )
    await state.set_state(LeadForm.waiting_birthdate)


@router.message(LeadForm.waiting_problem)
async def get_problem_text(message: Message, state: FSMContext):
    problem_text = message.text.strip()
    await state.update_data(problem=problem_text)
    await message.answer(
        "Спасибо, я сохранила 💜\n\n"
        "2️⃣ Теперь укажите, пожалуйста, вашу дату рождения в формате ДД.ММ.ГГГГ\n"
        "Например: 21.07.1995"
    )
    await state.set_state(LeadForm.waiting_birthdate)


@router.message(LeadForm.waiting_birthdate)
async def get_birthdate(message: Message, state: FSMContext, bot: Bot):
    birth_date_raw = message.text.strip()

    # проверим формат
    try:
        dt = datetime.strptime(birth_date_raw, "%d.%m.%Y")
    except ValueError:
        await message.answer("Немного не в том формате 🥲 Попробуйте так: 21.07.1995")
        return

    # сохраним в БД
    create_or_update_user(message.from_user.id, birth_date=birth_date_raw)

    data = await state.get_data()
    name = data.get("name") or "—"
    problem = data.get("problem") or "—"

    # отправим тарологу
    text_for_tarolog = to_tarolog_text(
        user_name=name,
        problem=problem,
        birth_date=birth_date_raw,
        user_tg_id=message.from_user.id
    )

    try:
        await bot.send_message(chat_id=TAROLOG_ID, text=text_for_tarolog)
    except Exception:
        # если вдруг таролога нет/неправильный id — просто пропустим
        pass

    # ответ пользователю
    if TAROLOG_USERNAME:
        await message.answer(
            "Благодарю, я всё записала 💜\n"
            "Чтобы быстрее получить обратную связь — можете написать мне прямо сюда 👇",
            reply_markup=InlineKeyboardBuilder().button(
                text="📩 Написать Елизавете",
                url=f"https://t.me/{TAROLOG_USERNAME}"
            ).as_markup()
        )
    else:
        await message.answer(
            "Благодарю, я всё записала 💜\n"
            "Специалист посмотрит ваш запрос и свяжется с вами."
        )

    await state.clear()


# ================= ЗАПУСК =================
async def main():
    bot = Bot(API_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)

    print("Bot started...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())