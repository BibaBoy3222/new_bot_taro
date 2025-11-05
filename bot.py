import asyncio
import sqlite3
from datetime import datetime, timezone

from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder


# 1. ВСТАВЬ СВОЙ ТОКЕН СЮДА
API_TOKEN = "7662481854:AAE7WzZaIbzCEmi5qXY37C0dErxej4uXWA4"

# 2. ID сотрудников (замени на свои)
ADMINS = {1091379648}  # <-- сюда свой telegram id
# категории, которые поддерживает бот
CATEGORIES = {
    "taro": "🔮 Расклад Таро",
    "matrix": "🧬 Матрица судьбы",
}

# ======= БАЗА ДАННЫХ =======
conn = sqlite3.connect("bot.db")
conn.row_factory = sqlite3.Row

# пользователи
conn.execute("""
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id INTEGER UNIQUE,
    name TEXT,
    birth_date TEXT,
    birth_place TEXT,
    birth_time TEXT
)
""")

# заявки
conn.execute("""
CREATE TABLE IF NOT EXISTS requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    category TEXT,
    status TEXT,
    assigned_to INTEGER,
    created_at TEXT
)
""")

# сотрудники
conn.execute("""
CREATE TABLE IF NOT EXISTS staff (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id INTEGER UNIQUE,
    name TEXT
)
""")

# категории сотрудников
conn.execute("""
CREATE TABLE IF NOT EXISTS staff_categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    staff_id INTEGER,
    category TEXT
)
""")

conn.commit()


# ======= ФУНКЦИИ ДЛЯ БД =======
def get_user_by_tg(tg_id: int):
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE tg_id = ?", (tg_id,))
    return cur.fetchone()

def get_request_with_user(req_id: int):
    """Возвращает заявку вместе с данными клиента."""
    cur = conn.cursor()
    cur.execute("""
        SELECT
            requests.id AS req_id,
            requests.category AS category,
            requests.status AS status,
            requests.assigned_to AS assigned_to,
            users.tg_id AS user_tg_id,
            users.name AS user_name
        FROM requests
        JOIN users ON users.id = requests.user_id
        WHERE requests.id = ?
    """, (req_id,))
    return cur.fetchone()



def user_profile_is_filled(row: sqlite3.Row | None) -> bool:
    """Проверяем, ввёл ли пользователь свои данные раньше."""
    if not row:
        return False
    return bool(row["name"]) and bool(row["birth_date"]) and bool(row["birth_place"])
    # время рождения может быть пустым — это нормально


def get_or_create_user(tg_id: int) -> int:
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE tg_id = ?", (tg_id,))
    row = cur.fetchone()
    if row:
        return row["id"]
    cur.execute("INSERT INTO users (tg_id) VALUES (?)", (tg_id,))
    conn.commit()
    return cur.lastrowid


def update_user_data(tg_id: int, name: str, birth_date: str, birth_place: str, birth_time: str):
    cur = conn.cursor()
    cur.execute("""
        UPDATE users
        SET name = ?, birth_date = ?, birth_place = ?, birth_time = ?
        WHERE tg_id = ?
    """, (name, birth_date, birth_place, birth_time, tg_id))
    conn.commit()


def create_request(user_id: int, category: str):
    cur = conn.cursor()
    created_at = datetime.now(timezone.utc).isoformat()  # Исправлено

    cur.execute("""
        INSERT INTO requests (user_id, category, status, assigned_to, created_at)
        VALUES (?, ?, 'new', NULL, ?)
    """, (user_id, category, created_at))
    conn.commit()
    return cur.lastrowid


def get_requests_by_status(status: str | None = None):
    cur = conn.cursor()
    base_query = """
        SELECT
            requests.id,
            requests.category,
            requests.status,
            requests.assigned_to,
            requests.created_at,
            users.name AS user_name,
            users.tg_id AS user_tg_id,
            users.birth_date AS user_birth_date,
            users.birth_place AS user_birth_place,
            users.birth_time AS user_birth_time
        FROM requests
        JOIN users ON users.id = requests.user_id
    """
    params = []
    if status:
        base_query += " WHERE requests.status = ?"
        params.append(status)
    base_query += " ORDER BY requests.created_at DESC"
    cur.execute(base_query, params)
    return cur.fetchall()


def get_new_requests():
    cur = conn.cursor()
    cur.execute("""
        SELECT
            requests.id,
            requests.category,
            requests.created_at,
            users.name,
            users.tg_id,
            users.birth_date,
            users.birth_place,
            users.birth_time
        FROM requests
        JOIN users ON users.id = requests.user_id
        WHERE requests.status = 'new'
        ORDER BY requests.created_at ASC
    """)
    return cur.fetchall()


def assign_request(req_id: int, staff_id: int):
    cur = conn.cursor()
    cur.execute("""
        UPDATE requests
        SET status = 'in_progress', assigned_to = ?
        WHERE id = ?
    """, (staff_id, req_id))
    conn.commit()



def get_staff_active(staff_id: int):
    cur = conn.cursor()
    cur.execute("""
        SELECT requests.id, users.name, users.tg_id, requests.category
        FROM requests
        JOIN users ON users.id = requests.user_id
        WHERE requests.status = 'in_progress' AND requests.assigned_to = ?
    """, (staff_id,))
    return cur.fetchall()


def finish_request(req_id: int):
    cur = conn.cursor()
    cur.execute("UPDATE requests SET status = 'done' WHERE id = ?", (req_id,))
    conn.commit()



# ---- STAFF: БД ----
def add_staff(tg_id: int, name: str):
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO staff (tg_id, name) VALUES (?, ?)", (tg_id, name))
    conn.commit()
    cur.execute("SELECT id FROM staff WHERE tg_id = ?", (tg_id,))
    return cur.fetchone()["id"]


def set_staff_categories(staff_id: int, categories: list[str]):
    cur = conn.cursor()
    cur.execute("DELETE FROM staff_categories WHERE staff_id = ?", (staff_id,))
    for cat in categories:
        cur.execute("INSERT INTO staff_categories (staff_id, category) VALUES (?, ?)", (staff_id, cat))
    conn.commit()


def get_staff_by_category(category: str):
    cur = conn.cursor()
    cur.execute("""
        SELECT staff.tg_id, staff.name
        FROM staff
        JOIN staff_categories ON staff.id = staff_categories.staff_id
        WHERE staff_categories.category = ?
    """, (category,))
    return cur.fetchall()


def get_all_staff():
    cur = conn.cursor()
    cur.execute("""
        SELECT staff.id, staff.tg_id, staff.name,
               GROUP_CONCAT(staff_categories.category, ',') as cats
        FROM staff
        LEFT JOIN staff_categories ON staff.id = staff_categories.staff_id
        GROUP BY staff.id
        ORDER BY staff.id ASC
    """)
    return cur.fetchall()


def delete_staff(staff_id: int):
    cur = conn.cursor()
    cur.execute("DELETE FROM staff_categories WHERE staff_id = ?", (staff_id,))
    cur.execute("DELETE FROM staff WHERE id = ?", (staff_id,))
    conn.commit()


# ======= СОСТОЯНИЯ =======
class UserForm(StatesGroup):
    choosing_category = State()
    waiting_name = State()
    waiting_birth_date = State()
    waiting_birth_place = State()
    waiting_birth_time = State()


class AdminAddStaff(StatesGroup):
    waiting_tg_id = State()
    waiting_name = State()
    waiting_categories = State()


# ======= РОУТЕРЫ =======
user_router = Router()
staff_router = Router()
admin_router = Router()


# ======= КЛАВИАТУРЫ =======
def categories_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text=CATEGORIES["taro"], callback_data="cat_taro")
    kb.button(text=CATEGORIES["matrix"], callback_data="cat_matrix")
    kb.adjust(1)
    return kb.as_markup()


def user_main_kb():
    """Меню для клиента, который уже заполнил данные."""
    kb = InlineKeyboardBuilder()
    kb.button(text="📋 Записаться на расклад", callback_data="user_book")
    kb.button(text="📝 Обновить данные", callback_data="user_update_profile")
    kb.adjust(1)
    return kb.as_markup()


def staff_menu_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="🆕 Новые заявки", callback_data="staff_new")
    kb.button(text="📂 Мои в работе", callback_data="staff_my")
    kb.adjust(1)
    return kb.as_markup()


def admin_menu_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="👥 Список сотрудников", callback_data="admin_staff_list")
    kb.button(text="📦 Заявки", callback_data="admin_requests")
    kb.button(text="➕ Добавить сотрудника", callback_data="admin_staff_add")
    kb.button(text="➖ Удалить сотрудника", callback_data="admin_staff_delete")
    kb.adjust(1)
    return kb.as_markup()


# ======= ПОЛЬЗОВАТЕЛЬ =======
@user_router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, bot: Bot):
    # админ → админка
    if message.from_user.id in ADMINS:
        await message.answer("Привет, админ 👋", reply_markup=admin_menu_kb())
        return

    tg_id = message.from_user.id
    user_row = get_user_by_tg(tg_id)

    # если профиль уже заполнен → сразу меню услуг
    if user_profile_is_filled(user_row):
        await message.answer(
            "Снова привет 👋\nТвои данные у меня уже есть.\nЧто делаем?",
            reply_markup=user_main_kb()
        )
        await state.clear()
        return

    # если первый раз → стандартный сценарий
    await message.answer(
        "Привет 👋\nЯ бот для записи на расклады и консультации.\nВыбери, что тебя интересует:",
        reply_markup=categories_kb()
    )
    await state.set_state(UserForm.choosing_category)


@user_router.callback_query(F.data == "user_book")
async def user_book(callback: CallbackQuery, state: FSMContext):
    # показываем категории сразу
    await callback.message.answer("Выбери услугу:", reply_markup=categories_kb())
    await state.set_state(UserForm.choosing_category)
    await callback.answer()


@user_router.callback_query(F.data == "user_update_profile")
async def user_update_profile(callback: CallbackQuery, state: FSMContext):
    # принудительно заново собираем данные
    await callback.message.answer("📝 Обновим данные.\nВведите ваше имя:")
    await state.set_state(UserForm.waiting_name)
    await callback.answer()


@user_router.callback_query(F.data.startswith("cat_"))
async def user_choose_category(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Выбор категории. Если профиль уже есть — сразу создаём заявку. Если нет — собираем данные."""
    category_code = callback.data.split("_", 1)[1]  # taro / matrix
    tg_id = callback.from_user.id
    user_row = get_user_by_tg(tg_id)

    # если данные уже есть → создаём заявку сразу
    if user_profile_is_filled(user_row):
        user_id = user_row["id"]
        req_id = create_request(user_id, category_code)

        # уведомим сотрудников нужной категории
        staff_list = get_staff_by_category(category_code)
        if staff_list:
            for staff in staff_list:
                await bot.send_message(
                    chat_id=staff["tg_id"],
                    text=(
                        f"📥 Новая заявка #{req_id} по категории: {CATEGORIES[category_code]}\n"
                        f"Клиент: {user_row['name']}\n"
                        f"Откройте меню сотрудника, чтобы взять в работу."
                    )
                )

        await callback.message.answer(
            f"✅ Заявка на {CATEGORIES[category_code]} принята.\nСпециалист свяжется с вами."
        )
        await state.clear()
        await callback.answer()
        return

    # если данных нет → как раньше
    await state.update_data(category=category_code)
    await callback.message.answer("Введите ваше имя:")
    await state.set_state(UserForm.waiting_name)
    await callback.answer()


@user_router.message(UserForm.waiting_name)
async def user_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await message.answer("Введите дату рождения (например 21.07.1995):")
    await state.set_state(UserForm.waiting_birth_date)


@user_router.message(UserForm.waiting_birth_date)
async def user_birth_date(message: Message, state: FSMContext):
    await state.update_data(birth_date=message.text.strip())
    await message.answer("Введите место рождения (город/страна):")
    await state.set_state(UserForm.waiting_birth_place)


@user_router.message(UserForm.waiting_birth_place)
async def user_birth_place(message: Message, state: FSMContext):
    await state.update_data(birth_place=message.text.strip())
    await message.answer("Введите время рождения (если не знаете — напишите «нет»):")
    await state.set_state(UserForm.waiting_birth_time)


@user_router.message(UserForm.waiting_birth_time)
async def user_birth_time(message: Message, state: FSMContext, bot: Bot):
    birth_time = message.text.strip()
    if birth_time.lower() in ("нет", "не знаю", "no"):
        birth_time = ""

    data = await state.get_data()
    tg_id = message.from_user.id

    user_id = get_or_create_user(tg_id)
    update_user_data(
        tg_id=tg_id,
        name=data["name"],
        birth_date=data["birth_date"],
        birth_place=data["birth_place"],
        birth_time=birth_time
    )

    # после ввода данных = создаём заявку по выбранной категории
    category = data["category"]
    req_id = create_request(user_id, category)

    # уведомим сотрудников этой категории
    staff_list = get_staff_by_category(category)
    if staff_list:
        for staff in staff_list:
            await bot.send_message(
                chat_id=staff["tg_id"],
                text=(
                    f"📥 Новая заявка #{req_id} по категории: {CATEGORIES[category]}\n"
                    f"Клиент: {data['name']}\n"
                    f"Возьмите в работу в меню сотрудника."
                )
            )

    await message.answer(
        "Спасибо! 🎉 Ваши данные сохранены.\n"
        "Заявка создана, специалист свяжется с вами.\n"
        "В следующий раз я уже не буду спрашивать ваши данные 😉",
        reply_markup=user_main_kb()
    )
    await state.clear()


# ======= СОТРУДНИК =======
@staff_router.callback_query(F.data == "staff_new")
async def staff_show_new(callback: CallbackQuery):
    reqs = get_new_requests()
    if not reqs:
        await callback.message.answer("Пока новых заявок нет 🙂")
        await callback.answer()
        return

    for row in reqs:
        req_id = row["id"]
        name = row["name"]
        cat = row["category"]
        birth_date = row["birth_date"] or "—"
        birth_place = row["birth_place"] or "—"
        birth_time = row["birth_time"] or "—"
        created_at = row["created_at"]

        # приводим дату к нормальному виду
        try:
            dt = datetime.fromisoformat(created_at)
            created_at_str = dt.strftime("%d.%m.%Y %H:%M")
        except Exception:
            created_at_str = created_at  # если вдруг не распарсилось

        kb = InlineKeyboardBuilder()
        kb.button(text="Взять в работу", callback_data=f"staff_take_{req_id}")
        kb.adjust(1)

        await callback.message.answer(
            f"📥 Заявка #{req_id}\n"
            f"Создано: {created_at_str}\n"
            f"Услуга: {CATEGORIES.get(cat, cat)}\n"
            f"👤 Клиент: {name}\n"
            f"📅 Дата рождения: {birth_date}\n"
            f"📍 Место рождения: {birth_place}\n"
            f"⏰ Время рождения: {birth_time}",
            reply_markup=kb.as_markup()
        )

    await callback.answer()


@staff_router.callback_query(F.data.startswith("staff_take_"))
async def staff_take(callback: CallbackQuery, bot: Bot):
    req_id = int(callback.data.split("_")[-1])

    # назначаем на сотрудника
    assign_request(req_id, callback.from_user.id)

    # берём данные по заявке и пользователю
    req_row = get_request_with_user(req_id)
    if req_row:
        user_tg_id = req_row["user_tg_id"]
        user_name = req_row["user_name"]
        category = req_row["category"]

        # текст для пользователя
        try:
            await bot.send_message(
                chat_id=user_tg_id,
                text=(
                    f"✨ Ваша заявка на {CATEGORIES.get(category, category)} принята специалистом.\n"
                    f"Он скоро свяжется с вами прямо в Telegram."
                )
            )
        except Exception:
            # если у пользователя закрыты ЛС — просто пропускаем
            pass

    # ответ сотруднику + кнопка завершить
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Завершить заявку", callback_data=f"staff_finish_{req_id}")
    kb.adjust(1)

    await callback.message.answer(
        f"Вы взяли заявку #{req_id} в работу ✅",
        reply_markup=kb.as_markup()
    )
    await callback.answer()


@staff_router.callback_query(F.data == "staff_my")
async def staff_my(callback: CallbackQuery):
    active = get_staff_active(callback.from_user.id)
    if not active:
        await callback.message.answer("У вас сейчас нет активных заявок.")
        await callback.answer()
        return

    for row in active:
        req_id = row["id"]
        name = row["name"]
        tg_id = row["tg_id"]
        cat = row["category"]

        kb = InlineKeyboardBuilder()
        kb.button(text="✅ Завершить заявку", callback_data=f"staff_finish_{req_id}")
        kb.adjust(1)

        await callback.message.answer(
            f"🟣 Заявка #{req_id}\n"
            f"Клиент: {name}\n"
            f"Услуга: {CATEGORIES.get(cat, cat)}\n"
            f"[написать клиенту](tg://user?id={tg_id})",
            reply_markup=kb.as_markup(),
            parse_mode="Markdown"
        )

    await callback.answer()


@staff_router.callback_query(F.data.startswith("staff_take_"))
async def staff_take(callback: CallbackQuery):
    req_id = int(callback.data.split("_")[-1])

    # назначаем заявку на этого сотрудника
    assign_request(req_id, callback.from_user.id)

    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Завершить заявку", callback_data=f"staff_finish_{req_id}")
    kb.adjust(1)

    await callback.message.answer(
        f"Вы взяли заявку #{req_id} в работу ✅",
        reply_markup=kb.as_markup()
    )
    await callback.answer()

@staff_router.callback_query(F.data.startswith("staff_finish_"))
async def staff_finish(callback: CallbackQuery):
    req_id = int(callback.data.split("_")[-1])
    finish_request(req_id)
    await callback.message.answer(f"Заявка #{req_id} завершена ✅")
    await callback.answer()



# ======= АДМИН =======
@admin_router.message(Command("admin"))
async def admin_cmd(message: Message):
    if message.from_user.id not in ADMINS:
        return
    await message.answer("Админ-меню:", reply_markup=admin_menu_kb())


@admin_router.callback_query(F.data == "admin_requests")
async def admin_requests_menu(callback: CallbackQuery):
    if callback.from_user.id not in ADMINS:
        await callback.answer()
        return

    kb = InlineKeyboardBuilder()
    kb.button(text="🆕 Новые", callback_data="admin_req_status_new")
    kb.button(text="📂 В работе", callback_data="admin_req_status_in_progress")
    kb.button(text="✅ Завершённые", callback_data="admin_req_status_done")
    kb.button(text="📋 Все", callback_data="admin_req_status_all")
    kb.adjust(2)
    await callback.message.answer("Что показать?", reply_markup=kb.as_markup())
    await callback.answer()


@admin_router.callback_query(F.data.startswith("admin_req_status_"))
async def admin_show_requests(callback: CallbackQuery):
    if callback.from_user.id not in ADMINS:
        await callback.answer()
        return

    status_key = callback.data.split("_")[-1]
    if status_key == "all":
        rows = get_requests_by_status(None)
        title = "Все заявки"
    elif status_key == "new":
        rows = get_requests_by_status("new")
        title = "Новые заявки"
    elif status_key in ("in", "in_progress"):
        rows = get_requests_by_status("in_progress")
        title = "Заявки в работе"
    else:
        rows = get_requests_by_status("done")
        title = "Завершённые заявки"

    if not rows:
        await callback.message.answer(f"{title}: нет записей.")
        await callback.answer()
        return

    await callback.message.answer(title + ":")

    for row in rows:
        req_id = row["id"]
        user_name = row["user_name"]
        user_tg_id = row["user_tg_id"]
        category = row["category"]
        status = row["status"]
        assigned_to = row["assigned_to"]
        created_at = row["created_at"]

        birth_date = row["user_birth_date"] or "—"
        birth_place = row["user_birth_place"] or "—"
        birth_time = row["user_birth_time"] or "—"

        # красивая дата
        try:
            dt = datetime.fromisoformat(created_at)
            created_at_str = dt.strftime("%d.%m.%Y %H:%M")
        except Exception:
            created_at_str = created_at

        client_link = f"[клиент](tg://user?id={user_tg_id})"

        kb = InlineKeyboardBuilder()
        if status == "new":
            # новую можно взять
            kb.button(text="Взять (админ)", callback_data=f"admin_take_{req_id}")

        elif status == "in_progress":
            # заявку уже кто-то взял
            # если взял именно этот админ — даём завершить
            if assigned_to == callback.from_user.id:
                kb.button(text="✅ Завершить", callback_data=f"admin_finish_{req_id}")
            else:
                # можно просто показать, кто взял, без кнопки
                pass

        if kb.buttons:
            kb.adjust(1)
            markup = kb.as_markup()
        else:
            markup = None

        taken_text = f"\nВзял: {assigned_to}" if assigned_to else ""

        await callback.message.answer(
            f"#{req_id} | {CATEGORIES.get(category, category)}\n"
            f"Создано: {created_at_str}\n"
            f"Клиент: {user_name} {client_link}\n"
            f"📅 Дата рождения: {birth_date}\n"
            f"📍 Место рождения: {birth_place}\n"
            f"⏰ Время рождения: {birth_time}\n"
            f"Статус: {status}{taken_text}",
            reply_markup=markup,
            parse_mode="Markdown"
        )

    await callback.answer()


@admin_router.callback_query(F.data.startswith("admin_take_"))
async def admin_take_request(callback: CallbackQuery, bot: Bot):
    if callback.from_user.id not in ADMINS:
        await callback.answer()
        return

    req_id = int(callback.data.split("_")[-1])

    # назначаем на админа
    assign_request(req_id, callback.from_user.id)

    # достаём данные заявки и клиента
    req_row = get_request_with_user(req_id)
    if req_row:
        user_tg_id = req_row["user_tg_id"]
        category = req_row["category"]
        try:
            await bot.send_message(
                chat_id=user_tg_id,
                text=(
                    f"✨ Ваша заявка на {CATEGORIES.get(category, category)} принята специалистом.\n"
                    f"Ожидайте сообщения."
                )
            )
        except Exception:
            pass

    # самому админу — кнопку завершить
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Завершить заявку", callback_data=f"admin_finish_{req_id}")
    kb.adjust(1)

    await callback.message.answer(
        f"Вы взяли заявку #{req_id} в работу ✅",
        reply_markup=kb.as_markup()
    )
    await callback.answer()


@admin_router.callback_query(F.data.startswith("admin_finish_"))
async def admin_finish_request(callback: CallbackQuery):
    if callback.from_user.id not in ADMINS:
        await callback.answer()
        return

    req_id = int(callback.data.split("_")[-1])
    finish_request(req_id)
    await callback.message.answer(f"Заявка #{req_id} завершена ✅")
    await callback.answer()



@admin_router.callback_query(F.data == "admin_staff_list")
async def admin_staff_list(callback: CallbackQuery):
    if callback.from_user.id not in ADMINS:
        await callback.answer()
        return

    staff = get_all_staff()
    if not staff:
        await callback.message.answer("Сотрудников пока нет.")
        await callback.answer()
        return

    lines = []
    for row in staff:
        cats = row["cats"] or ""
        if cats:
            cat_names = [CATEGORIES.get(c, c) for c in cats.split(",")]
            cats = ", ".join(cat_names)
        lines.append(f"ID#{row['id']} | {row['name']} | tg_id={row['tg_id']} | {cats}")

    await callback.message.answer("\n".join(lines))
    await callback.answer()


@admin_router.callback_query(F.data == "admin_staff_add")
async def admin_staff_add(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMINS:
        await callback.answer()
        return
    await callback.message.answer("Введи Telegram ID сотрудника (числом).")
    await state.set_state(AdminAddStaff.waiting_tg_id)
    await callback.answer()


@admin_router.message(AdminAddStaff.waiting_tg_id)
async def admin_staff_add_tg_id(message: Message, state: FSMContext):
    try:
        tg_id = int(message.text.strip())
    except ValueError:
        await message.answer("Нужно число. Введи Telegram ID сотрудника:")
        return

    await state.update_data(tg_id=tg_id)
    await message.answer("Введи имя сотрудника (как будет видно в списке):")
    await state.set_state(AdminAddStaff.waiting_name)


@admin_router.message(AdminAddStaff.waiting_name)
async def admin_staff_add_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    cats_text = ", ".join(CATEGORIES.keys())
    await message.answer(
        "Введи категории через запятую.\n"
        f"Доступные: {cats_text}\n"
        "Например: taro,matrix"
    )
    await state.set_state(AdminAddStaff.waiting_categories)


@admin_router.message(AdminAddStaff.waiting_categories)
async def admin_staff_add_categories(message: Message, state: FSMContext):
    data = await state.get_data()
    tg_id = data["tg_id"]
    name = data["name"]

    raw = message.text.strip()
    cats = [c.strip() for c in raw.split(",") if c.strip()]
    valid_cats = [c for c in cats if c in CATEGORIES.keys()]

    staff_id = add_staff(tg_id, name)
    set_staff_categories(staff_id, valid_cats)

    await message.answer("Сотрудник добавлен ✅")
    await state.clear()


@admin_router.callback_query(F.data == "admin_staff_delete")
async def admin_staff_delete(callback: CallbackQuery):
    if callback.from_user.id not in ADMINS:
        await callback.answer()
        return

    staff = get_all_staff()
    if not staff:
        await callback.message.answer("Сотрудников нет.")
        await callback.answer()
        return

    kb = InlineKeyboardBuilder()
    for row in staff:
        kb.button(text=f"{row['id']}: {row['name']}", callback_data=f"admin_del_{row['id']}")
    kb.adjust(1)
    await callback.message.answer("Выбери сотрудника для удаления:", reply_markup=kb.as_markup())
    await callback.answer()


@admin_router.callback_query(F.data.startswith("admin_del_"))
async def admin_staff_delete_one(callback: CallbackQuery):
    if callback.from_user.id not in ADMINS:
        await callback.answer()
        return

    staff_id = int(callback.data.split("_")[-1])
    delete_staff(staff_id)
    await callback.message.answer("Сотрудник удалён ✅")
    await callback.answer()


# ======= ЗАПУСК =======
async def main():
    bot = Bot(API_TOKEN)
    dp = Dispatcher()
    dp.include_router(user_router)
    dp.include_router(staff_router)
    dp.include_router(admin_router)

    print("Бот запущен...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())