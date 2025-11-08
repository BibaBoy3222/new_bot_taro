import asyncio
import os
import sqlite3
from datetime import datetime, date
from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import CommandStart
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import FSInputFile


# 1. ВСТАВЬ СВОЙ ТОКЕН СЮДА
API_TOKEN = "7662481854:AAE7WzZaIbzCEmi5qXY37C0dErxej4uXWA4"

# сюда tg-id таролога, которому будет прилетать анкета
TAROLOG_ID = 7109352431  # поменяй на настоящий id
# если есть username таролога, укажи — дадим кнопку пользователю
TAROLOG_USERNAME = "whatthebiba588"  # без @, можно оставить пустым ""

# =============== БАЗА ДАННЫХ ===============
conn = sqlite3.connect("leads.db")
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


def get_user_by_tg(tg_id):
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE tg_id=?", (tg_id,))
    return cur.fetchone()


def create_or_update_user(tg_id: int, name: str | None = None, birth_date: str | None = None):
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE tg_id=?", (tg_id,))
    if cur.fetchone():
        cur.execute("""
            UPDATE users
            SET name = COALESCE(?, name),
                birth_date = COALESCE(?, birth_date)
            WHERE tg_id = ?
        """, (name, birth_date, tg_id))
    else:
        cur.execute("INSERT INTO users (tg_id, name, birth_date) VALUES (?, ?, ?)", (tg_id, name, birth_date))
    conn.commit()

# =============== СОСТОЯНИЯ ===============
class Form(StatesGroup):
    waiting_name = State()
    waiting_birth = State()
    waiting_question = State()

# =============== РОУТЕР ===============
router = Router()

# =============== ТЕКСТЫ ===============

WELCOME_TEXT = (
    "🔮 *Я Таролог Елизавета*\n"
    "✨ Опытный специалист с более чем *15-летним стажем.*\n\n"
    "За эти годы я помогла сотням людей понять, что скрыто за их судьбой — "
    "без фантазий и ложных обещаний 🌙\n\n"
    "Иногда достаточно взглянуть на вещи чуть иначе, чтобы найти правильное направление 🌿\n\n"
    "Если хочешь разобраться и найти ответы — нажми кнопку ниже, и я помогу тебе понять всё важное 💫"
)

# =============== ХЕНДЛЕРЫ ===============

@router.message(CommandStart())
async def start_cmd(message: Message, state: FSMContext, bot: Bot):
    user = get_user_by_tg(message.from_user.id)
    kb = InlineKeyboardBuilder()
    kb.button(text="✨ Начать", callback_data="start_form")
    kb.adjust(1)

    photo_path = "taro_welcome.png"  # или .jpg — главное, чтобы файл реально был в папке

    # если картинка есть — шлём её
    if os.path.exists(photo_path):
        photo = FSInputFile(photo_path)

        if user and user["name"]:
            await bot.send_photo(
                chat_id=message.chat.id,
                photo=photo,
                caption=f"🌸 Здравствуйте, {user['name']}!\nРада видеть вас снова 💖",
                reply_markup=kb.as_markup()
            )
        else:
            # сначала фото
            await bot.send_photo(
                chat_id=message.chat.id,
                photo=photo,
            )
            # потом текст
            await message.answer(
                WELCOME_TEXT,
                reply_markup=kb.as_markup(),
                parse_mode="Markdown"
            )
    else:
        # если картинки нет — просто текст
        if user and user["name"]:
            await message.answer(
                f"🌸 Здравствуйте, {user['name']}!\nРада видеть вас снова 💖",
                reply_markup=kb.as_markup()
            )
        else:
            await message.answer(
                WELCOME_TEXT,
                reply_markup=kb.as_markup(),
                parse_mode="Markdown"
            )

    await state.clear()


@router.callback_query(F.data == "start_form")
async def start_form(callback: CallbackQuery, state: FSMContext):
    user = get_user_by_tg(callback.from_user.id)

    # если пользователь уже есть и у него есть и имя, и дата рождения —
    # сразу задаём только третий вопрос
    if user and user["name"] and user["birth_date"]:
        await state.update_data(
            name=user["name"],
            birth_date=user["birth_date"]
        )
        await callback.message.answer(
            "3️⃣ Что именно вас тревожит? 💭\nО чём хотели бы узнать?"
        )
        await state.set_state(Form.waiting_question)
    else:
        # идём по полной анкете
        await callback.message.answer(
            "Чтобы я лучше могла понять вас и ситуацию, ответьте на несколько вопросов 💭\n\n1️⃣ Как вас зовут?"
        )
        await state.set_state(Form.waiting_name)

    await callback.answer()


@router.message(Form.waiting_name)
async def get_name(message: Message, state: FSMContext):
    name = message.text.strip()
    await state.update_data(name=name)
    create_or_update_user(message.from_user.id, name=name)
    await message.answer("2️⃣ Ваша дата рождения? 📅\n_Например: 21.07.1995_", parse_mode="Markdown")
    await state.set_state(Form.waiting_birth)


@router.message(Form.waiting_birth)
async def get_birth(message: Message, state: FSMContext):
    birth = message.text.strip()
    try:
        datetime.strptime(birth, "%d.%m.%Y")
    except ValueError:
        await message.answer("Пожалуйста, укажите дату в формате *ДД.ММ.ГГГГ* 🌸", parse_mode="Markdown")
        return

    await state.update_data(birth_date=birth)
    create_or_update_user(message.from_user.id, birth_date=birth)
    await message.answer("3️⃣ Что именно вас тревожит? 💭\nО чём хотели бы узнать?")
    await state.set_state(Form.waiting_question)


@router.message(Form.waiting_question)
async def get_question(message: Message, state: FSMContext, bot: Bot):
    question = message.text.strip()
    data = await state.get_data()
    name = data.get("name", "—")
    birth = data.get("birth_date", "—")

    # вычисляем возраст
    age_text = ""
    try:
        bd = datetime.strptime(birth, "%d.%m.%Y").date()
        today = date.today()
        age = today.year - bd.year - ((today.month, today.day) < (bd.month, bd.day))
        age_text = f"{age} лет"
    except Exception:
        pass

    info = (
        "📩 *Новая анкета клиента*\n\n"
        f"👤 Имя: {name}\n"
        f"📅 Дата рождения: {birth}\n"
        f"🎂 Возраст: {age_text or '—'}\n\n"
        f"💬 Запрос:\n{question}\n\n"
        f"🪄 [Профиль](tg://user?id={message.from_user.id})"
    )

    try:
        await bot.send_message(TAROLOG_ID, info, parse_mode="Markdown")
    except Exception:
        pass

    kb = InlineKeyboardBuilder()
    if TAROLOG_USERNAME:
        kb.button(
            text="Да, приступим 🪄",
            url=f"https://t.me/{TAROLOG_USERNAME}"
        )
    kb.adjust(1)

    await message.answer("Поняла, благодарю 🌷\nПриступим к раскладу?", reply_markup=kb.as_markup())
    await state.clear()

# =============== ЗАПУСК ===============
async def main():
    bot = Bot(API_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    print("Bot started...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())