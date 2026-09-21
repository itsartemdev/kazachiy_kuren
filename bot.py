"""
Бот бронирования столика (aiogram 3).
Запуск: python bot.py
Токен: переменная окружения BOT_TOKEN или строка BOT_TOKEN ниже.
"""
import asyncio
import calendar
import copy
import json
import logging
import os
import re
from datetime import date, datetime, time, timedelta
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BotCommand,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

# ==================== НАСТРОЙКИ ====================
BOT_TOKEN = os.getenv("BOT_TOKEN", "8989681189:AAGn9PJ3BK_wpT91weuOKC5bRa-VFnCZ1_8")
MANAGER_CHAT_ID = int(os.getenv("MANAGER_CHAT_ID", "-5251415817"))  # 0 — не слать менеджеру; ID узнаём через /myid

TIMEZONE = os.getenv("TIMEZONE", "Europe/Moscow")  # часовой пояс ресторана
BOOKING_FROM = time(10, 0)   # с какого времени принимаем брони
BOOKING_TO = time(22, 0)     # до какого времени (включительно)
MIN_LEAD_MINUTES = 30        # минимум за сколько минут можно бронировать
MAX_DAYS_AHEAD = 90          # на сколько дней вперёд открыт календарь
MAX_GUESTS = 100             # максимум гостей
MAX_DISH_QTY = 99            # максимум порций одного блюда
BOOKINGS_FILE = Path("bookings.json")  # сюда сохраняются брони (переживают перезапуск)

if ":" not in BOT_TOKEN:
    raise SystemExit("❌ Укажите токен бота: переменная окружения BOT_TOKEN или строка BOT_TOKEN в коде.")

# ==================== МЕНЮ ====================
# unit — что означает одна "единица" при нажатии ➕/➖.
# Для большинства блюд это "порция", для блюд на развес — конкретный вес.
MENU = {
    "Холодные закуски": [
        ("Рулет из курицы", 200, "порция"),
        ("Рулет из утки", 300, "порция"),
        ("Буженина домашняя", 300, "порция"),
        ("Мясное ассорти", 1300, "порция"),
        ("Сало солёное/копчёное", 400, "порция"),
        ("Язык отварной с хреном", 950, "порция"),
        ("Сельдь с отварным картофелем", 450, "порция"),
    ],
    "Салаты": [
        ("«Цезарь» с курицей", 450, "порция"),
        ("Оливье", 400, "порция"),
        ("Тёплый салат из телятины", 800, "порция"),
        ("«Казачок» с говяжьим языком", 550, "порция"),
        ("«Заморский» с сёмгой и тигровыми креветками", 1000, "порция"),
        ("«Сельдь под шубой»", 350, "порция"),
    ],
    "Первые блюда": [
        ("Уха из карпа", 500, "порция"),
        ("Борщ из телятины", 550, "порция"),
        ("Солянка мясная", 500, "порция"),
        ("Окрошка мясная", 400, "порция"),
    ],
    "Горячее из мяса и птицы": [
        ("Домашние котлеты", 550, "порция"),
        ("Куриная отбивная в кляре", 420, "порция"),
        ("Бефстроганов", 1200, "порция"),
        ("Баранина тушёная", 1500, "порция"),
        ("Медальоны из телятины под грибным соусом", 1500, "порция"),
        ("Рёбра барбекю", 210, "100 г"),
    ],
    "Горячее из рыбы": [
        ("Филе сёмги в горчичном маринаде", 1400, "порция"),
        ("Котлеты из судака", 750, "порция"),
        ("Судак запечённый под сыром с овощами", 750, "порция"),
        ("Карп, запечённый на луке", 750, "порция"),
    ],
    "Морепродукты": [
        ("Креветки тигровые в сливочно-чесночном соусе", 750, "порция"),
        ("Жареные морепродукты с чесноком и томатами", 1500, "порция"),
        ("Мидии «Киви», запечённые под сыром", 550, "порция"),
    ],
    "Гарниры": [
        ("Картофель отварной", 350, "порция"),
        ("Картофель фри", 350, "порция"),
        ("Картофельное пюре", 300, "порция"),
        ("Рис с овощами", 300, "порция"),
        ("Каша гречневая", 250, "порция"),
    ],
    "Десерты": [
        ("Сырники со сметаной", 400, "порция"),
        ("Творожная запеканка", 400, "порция"),
        ("Ванильный блинчик", 50, "1 шт"),
        ("Мороженое в ассортименте", 120, "порция"),
    ],
}
CATEGORY_LIST = list(MENU.keys())

CATEGORY_EMOJI = {
    "Холодные закуски": "🥓",
    "Салаты": "🥗",
    "Первые блюда": "🍲",
    "Горячее из мяса и птицы": "🍖",
    "Горячее из рыбы": "🐟",
    "Морепродукты": "🦐",
    "Гарниры": "🍚",
    "Десерты": "🍰",
}

# Короткие названия ТОЛЬКО для кнопок в списке блюд.
# В заказе, у менеджера и на экране блюда (ℹ️) всегда полное название.
SHORT_NAMES = {
    "Сельдь с отварным картофелем": "Сельдь с картофелем",
    "Тёплый салат из телятины": "Салат из телятины",
    "«Казачок» с говяжьим языком": "«Казачок» с языком",
    "«Заморский» с сёмгой и тигровыми креветками": "«Заморский» с сёмгой",
    "Медальоны из телятины под грибным соусом": "Медальоны из телятины",
    "Филе сёмги в горчичном маринаде": "Сёмга в горчице",
    "Судак запечённый под сыром с овощами": "Судак под сыром",
    "Креветки тигровые в сливочно-чесночном соусе": "Тигровые креветки",
    "Жареные морепродукты с чесноком и томатами": "Жареные морепродукты",
    "Мидии «Киви», запечённые под сыром": "Мидии «Киви»",
    "Мороженое в ассортименте": "Мороженое",
    "Куриная отбивная в кляре": "Куриная отбивная",
}
MAX_BUTTON_NAME = 24

# Состав блюд (экран ℹ️). Ключ — ПОЛНОЕ название блюда из MENU. ЗАМЕНИТЕ примеры на реальный состав.
# Позже можно вынести в dish_info.py: from dish_info import DISH_INFO, DEFAULT_INFO
DEFAULT_INFO = "Состав уточняйте у администратора."
DISH_INFO = {
    "Оливье": "Картофель, морковь, яйцо, огурец солёный, горошек, колбаса/курица, майонез. (пример — замените)",
    "«Цезарь» с курицей": "Куриное филе, салат романо, пармезан, сухарики, соус «Цезарь». (пример — замените)",
    "«Сельдь под шубой»": "Сельдь, свёкла, морковь, картофель, яйцо, лук, майонез. (пример — замените)",
    "Борщ из телятины": "Телятина, свёкла, капуста, картофель, морковь, лук, томат, сметана. (пример — замените)",
    "Бефстроганов": "Говядина, лук, грибы, сметанный соус. (пример — замените)",
}

MONTHS_RU = ["", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
             "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
WEEKDAYS_HEADER = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
WEEKDAYS_SHORT = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]

# ==================== ИНИЦИАЛИЗАЦИЯ ====================
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo(TIMEZONE)
except Exception:  # на Windows может понадобиться: pip install tzdata
    TZ = None
    logging.warning("Часовой пояс %s недоступен, используется время сервера", TIMEZONE)

# ==== Хранилище броней (сохраняется в BOOKINGS_FILE) ====
BOOKINGS: dict[int, dict] = {}
NEXT_BOOKING_ID = 1


class Booking(StatesGroup):
    waiting_for_date = State()
    waiting_for_time = State()
    waiting_for_guests = State()
    picking_category = State()
    picking_dishes = State()
    waiting_for_phone = State()

    # ---- редактирование существующей брони ----
    edit_menu = State()
    editing_date = State()
    editing_time = State()
    editing_guests = State()
    editing_phone = State()


# ==================== ТЕКСТЫ ОШИБОК ====================
TIME_ERR = (
    "⚠️ Не удалось распознать время.\n"
    "Введите, например: 19:00, 19 30 или просто 19"
)
GUESTS_ERR = f"⚠️ Введите количество гостей числом от 1 до {MAX_GUESTS}.\nНапример: 4"
GUESTS_TOO_MANY = (
    f"👥 Для компаний больше {MAX_GUESTS} человек, пожалуйста, "
    "свяжитесь с администратором напрямую."
)
PHONE_ERR = (
    "⚠️ Не удалось распознать номер телефона.\n"
    "Введите в любом формате, например: +7 999 123-45-67 или 89991234567.\n"
    "Для номеров других стран — с плюсом и кодом страны."
)
EXPIRED_TEXT = "⌛ Сессия устарела. Нажмите /start, чтобы начать заново."


# ==================== ВРЕМЯ И ДАТЫ ====================
def now_local() -> datetime:
    return datetime.now(TZ).replace(tzinfo=None) if TZ else datetime.now()


def today_local() -> date:
    return now_local().date()


def fmt_date(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d:%d.%m.%Y} ({WEEKDAYS_SHORT[d.weekday()]})"


def fmt_date_short(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d:%d.%m} {WEEKDAYS_SHORT[d.weekday()]}"


def parse_date_callback(data: str) -> date | None:
    try:
        return date.fromisoformat(data.split("_", 1)[1])
    except (ValueError, IndexError):
        return None


def is_bookable_date(d: date) -> bool:
    today = today_local()
    return today <= d <= today + timedelta(days=MAX_DAYS_AHEAD)


# ==================== ВАЛИДАЦИЯ ВВОДА ====================
def parse_time(raw: str | None) -> time | None:
    """Понимает: 22, 9, 22 34, 22:34, 22.34, 22-34, 2234, 930, «в 19:30», «19 ч»."""
    s = (raw or "").strip().lower()
    if not s or len(s) > 20:
        return None
    s = re.sub(r"^(в|к|на)\s+", "", s)
    s = re.sub(r"\s*(часов|часа|час|ч)\.?$", "", s).strip()

    m = re.fullmatch(r"(\d{1,2})(?:[\s:.,\-]+(\d{2}))?", s)  # 19 | 19:30 | 19 30
    if not m:
        m = re.fullmatch(r"(\d{1,2})(\d{2})", s)              # 1930 | 930
    if not m:
        return None

    hours, minutes = int(m.group(1)), int(m.group(2) or 0)
    if hours > 23 or minutes > 59:
        return None
    return time(hours, minutes)


def check_booking_time(t: time, date_iso: str) -> str | None:
    """Возвращает текст ошибки или None, если время подходит."""
    if not (BOOKING_FROM <= t <= BOOKING_TO):
        return (
            f"🕙 Мы принимаем брони на время с {BOOKING_FROM:%H:%M} до {BOOKING_TO:%H:%M}.\n"
            "Выберите время из этого промежутка."
        )
    if datetime.combine(date.fromisoformat(date_iso), t) < now_local() + timedelta(minutes=MIN_LEAD_MINUTES):
        return (
            f"⏳ Это время уже прошло или слишком близко: бронь принимается минимум за {MIN_LEAD_MINUTES} минут.\n"
            "Выберите более позднее время."
        )
    return None


def parse_guests(raw: str | None) -> tuple[int | None, str | None]:
    """Возвращает (число, None) или (None, текст ошибки)."""
    s = (raw or "").strip()
    if not re.fullmatch(r"[^\d\-−+]*\d{1,4}[^\d\-−+]*", s) or len(s) > 40:
        return None, GUESTS_ERR
    n = int(re.search(r"\d+", s).group())
    if n < 1:
        return None, GUESTS_ERR
    if n > MAX_GUESTS:
        return None, GUESTS_TOO_MANY
    return n, None


def normalize_phone(raw: str | None) -> str | None:
    """
    Принимает любые форматы: +7 (999) 123-45-67, 8 999 123 45 67, 9991234567,
    +380 50 123 4567 и т.п. Возвращает красивый номер или None.
    """
    s = (raw or "").strip()
    if not s or len(s) > 30 or not re.fullmatch(r"[\d\s()+\-.]+", s):
        return None
    if "+" in s[1:]:
        return None

    digits = re.sub(r"\D", "", s)
    if len(set(digits)) < 3 or digits[0] == "0":  # 1111111111, 0000...
        return None

    if s.startswith("+"):
        if not 10 <= len(digits) <= 15:
            return None
    elif len(digits) == 11 and digits[0] in "78":
        digits = "7" + digits[1:]
    elif len(digits) == 10:
        digits = "7" + digits
    elif not 11 <= len(digits) <= 15:
        return None

    if digits.startswith("7"):
        if len(digits) != 11 or digits[1] not in "3456789":
            return None
        return f"+7 ({digits[1:4]}) {digits[4:7]}-{digits[7:9]}-{digits[9:11]}"
    return f"+{digits}"


def extract_phone(message: Message) -> str | None:
    if message.contact and message.contact.phone_number:
        raw = message.contact.phone_number
        return normalize_phone(raw if raw.startswith("+") else f"+{raw}")
    return normalize_phone(message.text)


# ==================== ХРАНИЛИЩЕ ====================
def load_bookings() -> None:
    global NEXT_BOOKING_ID
    if not BOOKINGS_FILE.exists():
        return
    try:
        raw = json.loads(BOOKINGS_FILE.read_text(encoding="utf-8"))
        BOOKINGS.update({int(k): v for k, v in raw.get("bookings", {}).items()})
        NEXT_BOOKING_ID = raw.get("next_id", max(BOOKINGS, default=0) + 1)
        logging.info("Загружено броней: %d", len(BOOKINGS))
    except Exception:
        logging.exception("Не удалось прочитать %s", BOOKINGS_FILE)


def save_bookings() -> None:
    try:
        tmp = BOOKINGS_FILE.with_suffix(".tmp")
        tmp.write_text(
            json.dumps({"next_id": NEXT_BOOKING_ID, "bookings": BOOKINGS}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(BOOKINGS_FILE)
    except Exception:
        logging.exception("Не удалось сохранить брони")


def get_own_booking(booking_id: int | None, user_id: int) -> dict | None:
    booking = BOOKINGS.get(booking_id)
    return booking if booking and booking["user_id"] == user_id else None


async def current_editing_booking(user_id: int, state: FSMContext) -> dict | None:
    data = await state.get_data()
    return get_own_booking(data.get("editing_booking_id"), user_id)


def upcoming_bookings(user_id: int) -> list[dict]:
    now = now_local()
    items = [
        b for b in BOOKINGS.values()
        if b["user_id"] == user_id
        and datetime.combine(date.fromisoformat(b["date"]), parse_time(b["time"])) >= now
    ]
    return sorted(items, key=lambda b: (b["date"], b["time"]))


# ==================== ФОРМАТИРОВАНИЕ ====================
def cat_title(category: str) -> str:
    return f"{CATEGORY_EMOJI.get(category, '🍽')} {category}"


def short_name(name: str) -> str:
    if name in SHORT_NAMES:
        return SHORT_NAMES[name]
    if len(name) <= MAX_BUTTON_NAME:
        return name
    return name[: MAX_BUTTON_NAME - 1].rstrip() + "…"


def order_total(selected: dict) -> int:
    return sum(info["price"] * info["qty"] for info in selected.values())


def format_dishes_by_category(selected: dict) -> str:
    """selected: {dish_name: {"name", "qty", "price", "unit", "category"}}"""
    if not selected:
        return "— уточним по телефону"

    lines = []
    for category in CATEGORY_LIST:
        items = [i for i in selected.values() if i["category"] == category]
        if not items:
            continue
        lines.append(f"{cat_title(category)}:")
        for item in items:
            qty, unit = item["qty"], item["unit"]
            qty_label = f"{qty} × {unit}" if unit != "порция" else f"{qty} порц."
            lines.append(f"  • {item['name']} — {qty_label} — {item['price'] * qty}₽")
    lines.append(f"\n🧮 Итого по блюдам: {order_total(selected)}₽")
    return "\n".join(lines)


def booking_summary_text(booking: dict, header: str, for_manager: bool = False) -> str:
    lines = [
        header,
        "",
        f"📅 Дата: {fmt_date(booking['date'])}",
        f"⏰ Время: {booking['time']}",
        f"👥 Гостей: {booking['guests']}",
        f"📞 Телефон: {booking['phone']}",
        "",
        "🍽 Заказ:",
        format_dishes_by_category(booking["selected_dishes"]),
    ]
    if for_manager:
        lines += ["", f"👤 От: {booking['guest_name']} ({booking['guest_username']})"]
    return "\n".join(lines)


# ==================== ВСПОМОГАТЕЛЬНОЕ ДЛЯ TELEGRAM ====================
async def safe_edit(message: Message, text: str, reply_markup: InlineKeyboardMarkup | None = None) -> None:
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            raise


async def safe_edit_markup(message: Message, reply_markup: InlineKeyboardMarkup) -> None:
    try:
        await message.edit_reply_markup(reply_markup=reply_markup)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            raise


async def session_expired(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(EXPIRED_TEXT, reply_markup=ReplyKeyboardRemove())


async def sync_group_message(booking: dict, change: str | None = None, cancelled: bool = False) -> None:
    """Создаёт/обновляет сообщение о брони в группе менеджера. Никогда не роняет бота."""
    if not MANAGER_CHAT_ID:
        return
    header = f"❌ Бронь #{booking['id']} ОТМЕНЕНА гостем" if cancelled else f"📋 Бронь #{booking['id']}"
    text = booking_summary_text(booking, header, for_manager=True)

    try:
        message_id = booking.get("group_message_id")
        edited = False
        if message_id:
            try:
                await bot.edit_message_text(chat_id=MANAGER_CHAT_ID, message_id=message_id, text=text)
                edited = True
            except TelegramBadRequest as e:
                if "message is not modified" in str(e).lower():
                    edited = True
                else:
                    logging.warning("Не удалось обновить сообщение в группе, отправляю новое: %s", e)

        if not edited:
            sent = await bot.send_message(MANAGER_CHAT_ID, text)
            booking["group_message_id"] = sent.message_id
            return

        if cancelled or change:
            note = (
                f"❌ Гость отменил бронь #{booking['id']}"
                if cancelled
                else f"✏️ Бронь #{booking['id']} изменена: {change}"
            )
            await bot.send_message(MANAGER_CHAT_ID, note, reply_to_message_id=message_id)
    except Exception:
        logging.exception("Не удалось отправить сообщение менеджеру")


async def apply_booking_change(booking: dict, field: str, value, change_text: str) -> None:
    if booking[field] != value:
        booking[field] = value
        await sync_group_message(booking, change=change_text)
        save_bookings()


# ==================== КЛАВИАТУРЫ ====================
def build_calendar(year: int, month: int, back_id: int | None = None) -> InlineKeyboardMarkup:
    today = today_local()
    last_day = today + timedelta(days=MAX_DAYS_AHEAD)

    rows = [[InlineKeyboardButton(text=f"📅 {MONTHS_RU[month]} {year}", callback_data="ignore")]]
    rows.append([InlineKeyboardButton(text=d, callback_data="ignore") for d in WEEKDAYS_HEADER])

    for week in calendar.monthcalendar(year, month):
        row = []
        for day in week:
            if day == 0:
                row.append(InlineKeyboardButton(text=" ", callback_data="ignore"))
                continue
            d = date(year, month, day)
            if d < today or d > last_day:
                row.append(InlineKeyboardButton(text="·", callback_data="ignore"))
            else:
                row.append(InlineKeyboardButton(text=str(day), callback_data=f"date_{d.isoformat()}"))
        rows.append(row)

    prev_y, prev_m = (year - 1, 12) if month == 1 else (year, month - 1)
    next_y, next_m = (year + 1, 1) if month == 12 else (year, month + 1)
    can_prev = (year, month) > (today.year, today.month)
    can_next = (year, month) < (last_day.year, last_day.month)
    blank = InlineKeyboardButton(text=" ", callback_data="ignore")
    rows.append([
        InlineKeyboardButton(text="◀️", callback_data=f"cal_{prev_y}_{prev_m}") if can_prev else blank,
        InlineKeyboardButton(text="▶️", callback_data=f"cal_{next_y}_{next_m}") if can_next else blank,
    ])
    if back_id:
        rows.append([InlineKeyboardButton(text="↩️ Назад", callback_data=f"editback_{back_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def back_keyboard(booking_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="↩️ Назад", callback_data=f"editback_{booking_id}")]
    ])


def contact_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Поделиться номером", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
        input_field_placeholder="+7 999 123-45-67",
    )


def categories_keyboard(selected: dict, editing: bool = False) -> InlineKeyboardMarkup:
    subtotals: dict[str, int] = {}
    for info in selected.values():
        subtotals[info["category"]] = subtotals.get(info["category"], 0) + info["price"] * info["qty"]

    rows = []
    for i, cat in enumerate(CATEGORY_LIST):
        label = f"✅ {cat} — {subtotals[cat]}₽" if cat in subtotals else cat_title(cat)
        rows.append([InlineKeyboardButton(text=label, callback_data=f"cat_{i}")])

    if editing:
        rows.append([InlineKeyboardButton(text="💾 Сохранить заказ", callback_data="dishes_done")])
        rows.append([InlineKeyboardButton(text="↩️ Отмена (без изменений)", callback_data="dishes_cancel_edit")])
    else:
        rows.append([InlineKeyboardButton(text="✅ Готово", callback_data="dishes_done")])
        rows.append([InlineKeyboardButton(text="⏭ Пропустить (ждать звонка)", callback_data="dishes_skip")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def categories_screen_text(selected: dict) -> str:
    if not selected:
        return "🍽 Выберите категорию, чтобы добавить блюда:"
    return (
        f"🧾 Ваш текущий заказ:\n\n{format_dishes_by_category(selected)}\n\n"
        "👇 Выберите категорию, чтобы добавить ещё:"
    )


def dishes_screen_text(cat_index: int, selected: dict) -> str:
    text = (
        f"{cat_title(CATEGORY_LIST[cat_index])}\n\n"
        "➕ ➖ — количество\n"
        "ℹ️ — полное название и состав"
    )
    total = order_total(selected)
    if total:
        text += f"\n\n🧾 В заказе на: {total}₽"
    return text


def dishes_keyboard(cat_index: int, selected: dict) -> InlineKeyboardMarkup:
    category = CATEGORY_LIST[cat_index]
    rows = []
    for dish_index, (name, price, unit) in enumerate(MENU[category]):
        qty = selected.get(name, {}).get("qty", 0)
        price_label = f"{price}₽" if unit == "порция" else f"{price}₽/{unit}"
        prefix = "✅ " if qty > 0 else ""

        rows.append([InlineKeyboardButton(text=f"{prefix}{short_name(name)} — {price_label}", callback_data="ignore")])
        rows.append([
            InlineKeyboardButton(text="➖", callback_data=f"qdec_{cat_index}_{dish_index}"),
            InlineKeyboardButton(text=str(qty), callback_data="ignore"),
            InlineKeyboardButton(text="➕", callback_data=f"qinc_{cat_index}_{dish_index}"),
            InlineKeyboardButton(text="ℹ️", callback_data=f"info_{cat_index}_{dish_index}"),
        ])
    rows.append([InlineKeyboardButton(text="⬅️ К категориям", callback_data="back_to_categories")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def dish_detail_text(cat_index: int, dish_index: int, selected: dict) -> str:
    name, price, unit = MENU[CATEGORY_LIST[cat_index]][dish_index]
    qty = selected.get(name, {}).get("qty", 0)
    info = DISH_INFO.get(name, DEFAULT_INFO)

    if qty:
        qty_label = f"{qty} × {unit}" if unit != "порция" else f"{qty} порц."
        chosen_line = f"✅ Выбрано: {qty_label} = {price * qty}₽"
    else:
        chosen_line = "▫️ Пока не выбрано"

    return f"🍽 {name}\n💰 {price}₽ / {unit}\n\n📝 Состав:\n{info}\n\n{chosen_line}"


def dish_detail_keyboard(cat_index: int, dish_index: int, selected: dict) -> InlineKeyboardMarkup:
    name, price, unit = MENU[CATEGORY_LIST[cat_index]][dish_index]
    qty = selected.get(name, {}).get("qty", 0)
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="➖", callback_data=f"dqdec_{cat_index}_{dish_index}"),
            InlineKeyboardButton(text=f"{qty} {unit}" if qty else "0", callback_data="ignore"),
            InlineKeyboardButton(text="➕", callback_data=f"dqinc_{cat_index}_{dish_index}"),
        ],
        [InlineKeyboardButton(text="⬅️ К списку блюд", callback_data=f"bd_{cat_index}")],
    ])


def edit_menu_keyboard(booking_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Изменить дату", callback_data=f"editfield_date_{booking_id}")],
        [InlineKeyboardButton(text="⏰ Изменить время", callback_data=f"editfield_time_{booking_id}")],
        [InlineKeyboardButton(text="👥 Изменить кол-во гостей", callback_data=f"editfield_guests_{booking_id}")],
        [InlineKeyboardButton(text="📞 Изменить телефон", callback_data=f"editfield_phone_{booking_id}")],
        [InlineKeyboardButton(text="🍽 Изменить блюда", callback_data=f"editfield_dishes_{booking_id}")],
        [InlineKeyboardButton(text="🗑 Отменить бронь", callback_data=f"cancelbooking_{booking_id}")],
        [InlineKeyboardButton(text="✅ Готово", callback_data="editfield_close")],
    ])


async def show_edit_menu(message: Message, state: FSMContext, booking_id: int,
                         notice: str = "", edit: bool = False) -> None:
    booking = BOOKINGS[booking_id]
    text = booking_summary_text(booking, f"✏️ Бронь #{booking_id}") + "\n\n👇 Что хотите изменить?"
    if notice:
        text = f"{notice}\n\n{text}"
    keyboard = edit_menu_keyboard(booking_id)
    if edit:
        await safe_edit(message, text, keyboard)
    else:
        await message.answer(text, reply_markup=keyboard)
    await state.update_data(editing_booking_id=booking_id)
    await state.set_state(Booking.edit_menu)


# ==================== КОМАНДЫ (регистрируются первыми) ====================
@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    today = today_local()
    await message.answer(
        "👋 Здравствуйте! Это бот бронирования столика 🍽\n\nВыберите дату 📅",
        reply_markup=build_calendar(today.year, today.month),
    )
    await state.set_state(Booking.waiting_for_date)


@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "ℹ️ Я помогу забронировать столик.\n\n"
        "/start — новая бронь\n"
        "/myorders — мои брони (изменить или отменить)\n"
        "/cancel — прервать оформление"
    )


@dp.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "❌ Оформление отменено.\n/start — начать заново, /myorders — мои брони",
        reply_markup=ReplyKeyboardRemove(),
    )


@dp.message(Command("myorders"))
async def cmd_myorders(message: Message, state: FSMContext):
    await state.clear()
    items = upcoming_bookings(message.from_user.id)
    if not items:
        await message.answer("📭 У вас пока нет активных броней.\n/start — создать бронь.")
        return

    rows = [
        [InlineKeyboardButton(
            text=f"📋 #{b['id']} · {fmt_date_short(b['date'])} {b['time']} · 👥 {b['guests']}",
            callback_data=f"openbooking_{b['id']}",
        )]
        for b in items
    ]
    await message.answer("📋 Ваши брони:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@dp.message(Command("myid"))
async def cmd_myid(message: Message):
    await message.answer(f"🆔 ID этого чата: {message.chat.id}")


# ==================== КАЛЕНДАРЬ ====================
@dp.callback_query(F.data == "ignore")
async def calendar_ignore(callback: CallbackQuery):
    await callback.answer()


@dp.callback_query(StateFilter(Booking.waiting_for_date, Booking.editing_date), F.data.startswith("cal_"))
async def calendar_navigate(callback: CallbackQuery, state: FSMContext):
    try:
        _, y, m = callback.data.split("_")
        year, month = int(y), int(m)
        date(year, month, 1)
    except ValueError:
        await callback.answer()
        return

    today = today_local()
    last_day = today + timedelta(days=MAX_DAYS_AHEAD)
    if not (today.year, today.month) <= (year, month) <= (last_day.year, last_day.month):
        await callback.answer()
        return

    back_id = None
    if await state.get_state() == Booking.editing_date.state:
        back_id = (await state.get_data()).get("editing_booking_id")
    await safe_edit_markup(callback.message, build_calendar(year, month, back_id))
    await callback.answer()


@dp.callback_query(Booking.waiting_for_date, F.data.startswith("date_"))
async def pick_date_new(callback: CallbackQuery, state: FSMContext):
    chosen = parse_date_callback(callback.data)
    if chosen is None or not is_bookable_date(chosen):
        await callback.answer("Эта дата недоступна", show_alert=True)
        return

    await state.update_data(date=chosen.isoformat())
    await safe_edit(
        callback.message,
        f"📅 Дата: {fmt_date(chosen.isoformat())}\n\n"
        f"⏰ На какое время? Например: 19:00, 19 30 или просто 19\n"
        f"Принимаем брони с {BOOKING_FROM:%H:%M} до {BOOKING_TO:%H:%M}.",
    )
    await state.set_state(Booking.waiting_for_time)
    await callback.answer()


@dp.callback_query(Booking.editing_date, F.data.startswith("date_"))
async def pick_date_edit(callback: CallbackQuery, state: FSMContext):
    chosen = parse_date_callback(callback.data)
    if chosen is None or not is_bookable_date(chosen):
        await callback.answer("Эта дата недоступна", show_alert=True)
        return

    booking = await current_editing_booking(callback.from_user.id, state)
    if not booking:
        await callback.answer("Бронь не найдена. Нажмите /myorders", show_alert=True)
        return

    if check_booking_time(parse_time(booking["time"]), chosen.isoformat()):
        await callback.answer(
            f"⏳ Время {booking['time']} на эту дату недоступно. "
            "Выберите другую дату или сначала измените время.",
            show_alert=True,
        )
        return

    await apply_booking_change(booking, "date", chosen.isoformat(), f"дата → {fmt_date(chosen.isoformat())}")
    await show_edit_menu(callback.message, state, booking["id"], notice="✅ Дата обновлена!", edit=True)
    await callback.answer()


# ==================== СОЗДАНИЕ НОВОЙ БРОНИ ====================
@dp.message(Booking.waiting_for_time)
async def process_time(message: Message, state: FSMContext):
    t = parse_time(message.text)
    if t is None:
        await message.answer(TIME_ERR)
        return

    data = await state.get_data()
    if "date" not in data:
        await session_expired(message, state)
        return

    error = check_booking_time(t, data["date"])
    if error:
        await message.answer(error)
        return

    await state.update_data(time=t.strftime("%H:%M"))
    await message.answer(f"⏰ Время: {t:%H:%M}\n\n👥 На сколько гостей? (от 1 до {MAX_GUESTS})")
    await state.set_state(Booking.waiting_for_guests)


@dp.message(Booking.waiting_for_guests)
async def process_guests(message: Message, state: FSMContext):
    guests, error = parse_guests(message.text)
    if error:
        await message.answer(error)
        return

    await state.update_data(guests=guests, selected_dishes={})
    await message.answer(
        f"👥 Гостей: {guests}\n\n"
        "🍽 Хотите выбрать блюда заранее?\n"
        "Выберите категорию или нажмите «Пропустить» — тогда уточним заказ по телефону.",
        reply_markup=categories_keyboard({}),
    )
    await state.set_state(Booking.picking_category)


@dp.message(Booking.waiting_for_phone)
async def process_phone(message: Message, state: FSMContext):
    global NEXT_BOOKING_ID

    phone = extract_phone(message)
    if phone is None:
        await message.answer(PHONE_ERR)
        return

    data = await state.get_data()
    if not all(k in data for k in ("date", "time", "guests")):
        await session_expired(message, state)
        return

    booking_id = NEXT_BOOKING_ID
    NEXT_BOOKING_ID += 1

    booking = {
        "id": booking_id,
        "user_id": message.from_user.id,
        "date": data["date"],
        "time": data["time"],
        "guests": data["guests"],
        "selected_dishes": data.get("selected_dishes", {}),
        "phone": phone,
        "guest_name": message.from_user.full_name,
        "guest_username": f"@{message.from_user.username}" if message.from_user.username else "нет username",
        "group_message_id": None,
    }
    BOOKINGS[booking_id] = booking
    await sync_group_message(booking)
    save_bookings()

    await message.answer(
        f"🎉 Спасибо! Ваша бронь #{booking_id} принята.\n\n"
        f"{booking_summary_text(booking, f'🧾 Бронь #{booking_id}')}\n\n"
        "☎️ Мы свяжемся с вами для подтверждения.\n"
        "✏️ Изменить или отменить бронь: /myorders",
        reply_markup=ReplyKeyboardRemove(),
    )
    await state.clear()


# ==================== ВЫБОР БЛЮД ====================
def is_editing(data: dict) -> bool:
    return bool(data.get("editing_booking_id"))


@dp.callback_query(Booking.picking_category, F.data.startswith("cat_"))
async def open_category(callback: CallbackQuery, state: FSMContext):
    cat_index = int(callback.data.replace("cat_", ""))
    data = await state.get_data()
    selected = data.get("selected_dishes", {})
    await safe_edit(callback.message, dishes_screen_text(cat_index, selected), dishes_keyboard(cat_index, selected))
    await state.set_state(Booking.picking_dishes)
    await callback.answer()


@dp.callback_query(Booking.picking_dishes, F.data.startswith("info_"))
async def open_dish_info(callback: CallbackQuery, state: FSMContext):
    _, ci, di = callback.data.split("_")
    cat_index, dish_index = int(ci), int(di)
    selected = (await state.get_data()).get("selected_dishes", {})
    await safe_edit(
        callback.message,
        dish_detail_text(cat_index, dish_index, selected),
        dish_detail_keyboard(cat_index, dish_index, selected),
    )
    await callback.answer()


@dp.callback_query(Booking.picking_dishes, F.data.startswith("bd_"))
async def back_to_dishes(callback: CallbackQuery, state: FSMContext):
    cat_index = int(callback.data.replace("bd_", ""))
    selected = (await state.get_data()).get("selected_dishes", {})
    await safe_edit(callback.message, dishes_screen_text(cat_index, selected), dishes_keyboard(cat_index, selected))
    await callback.answer()


def apply_quantity_change(selected: dict, cat_index: int, dish_index: int, action: str) -> str:
    """Возвращает 'ok' (изменилось), 'noop' (нечего менять) или 'max' (достигнут максимум)."""
    category = CATEGORY_LIST[cat_index]
    name, price, unit = MENU[category][dish_index]

    old_qty = selected.get(name, {}).get("qty", 0)
    if action.endswith("inc"):
        if old_qty >= MAX_DISH_QTY:
            return "max"
        new_qty = old_qty + 1
    else:
        new_qty = max(0, old_qty - 1)

    if new_qty == old_qty:
        return "noop"
    if new_qty == 0:
        selected.pop(name, None)
    else:
        selected[name] = {"name": name, "qty": new_qty, "price": price, "unit": unit, "category": category}
    return "ok"


@dp.callback_query(Booking.picking_dishes, F.data.regexp(r"^q(inc|dec)_\d+_\d+$"))
async def change_quantity(callback: CallbackQuery, state: FSMContext):
    """➕/➖ в списке блюд категории."""
    action, ci, di = callback.data.split("_")
    cat_index, dish_index = int(ci), int(di)
    selected = (await state.get_data()).get("selected_dishes", {})

    result = apply_quantity_change(selected, cat_index, dish_index, action)
    if result == "max":
        await callback.answer(f"Максимум {MAX_DISH_QTY} порций", show_alert=False)
        return
    if result == "noop":
        await callback.answer()
        return

    await state.update_data(selected_dishes=selected)
    await safe_edit(callback.message, dishes_screen_text(cat_index, selected), dishes_keyboard(cat_index, selected))
    await callback.answer()


@dp.callback_query(Booking.picking_dishes, F.data.regexp(r"^dq(inc|dec)_\d+_\d+$"))
async def change_quantity_detail(callback: CallbackQuery, state: FSMContext):
    """➕/➖ на экране блюда (ℹ️)."""
    action, ci, di = callback.data.split("_")
    cat_index, dish_index = int(ci), int(di)
    selected = (await state.get_data()).get("selected_dishes", {})

    result = apply_quantity_change(selected, cat_index, dish_index, action)
    if result == "max":
        await callback.answer(f"Максимум {MAX_DISH_QTY} порций", show_alert=False)
        return
    if result == "noop":
        await callback.answer()
        return

    await state.update_data(selected_dishes=selected)
    await safe_edit(
        callback.message,
        dish_detail_text(cat_index, dish_index, selected),
        dish_detail_keyboard(cat_index, dish_index, selected),
    )
    await callback.answer()


@dp.callback_query(Booking.picking_dishes, F.data == "back_to_categories")
async def back_to_categories(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected = data.get("selected_dishes", {})
    await safe_edit(
        callback.message,
        categories_screen_text(selected),
        categories_keyboard(selected, editing=is_editing(data)),
    )
    await state.set_state(Booking.picking_category)
    await callback.answer()


async def finalize_dishes(callback: CallbackQuery, state: FSMContext, selected: dict) -> None:
    data = await state.get_data()

    if is_editing(data):
        booking = await current_editing_booking(callback.from_user.id, state)
        if not booking:
            await callback.message.answer(EXPIRED_TEXT)
            await state.clear()
            return
        await apply_booking_change(booking, "selected_dishes", selected, "заказ блюд")
        await show_edit_menu(callback.message, state, booking["id"], notice="✅ Заказ обновлён!", edit=True)
        return

    await state.update_data(selected_dishes=selected)
    if selected:
        await safe_edit(callback.message, f"✅ Заказ сохранён:\n\n{format_dishes_by_category(selected)}")
    else:
        await safe_edit(callback.message, "⏭ Хорошо, блюда уточним по телефону.")
    await callback.message.answer(
        "📞 Оставьте номер телефона для связи.\n"
        "Нажмите кнопку ниже 👇 или напишите номер в любом формате.",
        reply_markup=contact_keyboard(),
    )
    await state.set_state(Booking.waiting_for_phone)


@dp.callback_query(Booking.picking_category, F.data == "dishes_skip")
async def dishes_skip(callback: CallbackQuery, state: FSMContext):
    if is_editing(await state.get_data()):  # в режиме правки «пропустить» не показывается
        await callback.answer()
        return
    await finalize_dishes(callback, state, {})
    await callback.answer()


@dp.callback_query(Booking.picking_category, F.data == "dishes_done")
async def dishes_done(callback: CallbackQuery, state: FSMContext):
    selected = (await state.get_data()).get("selected_dishes", {})
    await finalize_dishes(callback, state, selected)
    await callback.answer()


@dp.callback_query(Booking.picking_category, F.data == "dishes_cancel_edit")
async def dishes_cancel_edit(callback: CallbackQuery, state: FSMContext):
    booking = await current_editing_booking(callback.from_user.id, state)
    if not booking:
        await callback.answer("Бронь не найдена. Нажмите /myorders", show_alert=True)
        return
    await show_edit_menu(callback.message, state, booking["id"], edit=True)
    await callback.answer()


# ==================== РЕДАКТИРОВАНИЕ И ОТМЕНА БРОНИ ====================
@dp.callback_query(F.data.startswith("openbooking_"))
async def open_booking(callback: CallbackQuery, state: FSMContext):
    booking = get_own_booking(int(callback.data.replace("openbooking_", "")), callback.from_user.id)
    if not booking:
        await callback.answer("Бронь не найдена", show_alert=True)
        return
    await show_edit_menu(callback.message, state, booking["id"])
    await callback.answer()


@dp.callback_query(F.data.startswith("editback_"))
async def edit_back(callback: CallbackQuery, state: FSMContext):
    booking = get_own_booking(int(callback.data.replace("editback_", "")), callback.from_user.id)
    if not booking:
        await callback.answer("Бронь не найдена", show_alert=True)
        return
    await show_edit_menu(callback.message, state, booking["id"], edit=True)
    await callback.answer()


@dp.callback_query(F.data == "editfield_close")
async def close_edit_menu(callback: CallbackQuery, state: FSMContext):
    booking = await current_editing_booking(callback.from_user.id, state)
    if booking:
        text = (
            f"{booking_summary_text(booking, f'🧾 Бронь #{booking['id']}')}\n\n"
            "👌 Готово! Изменения сохранены.\n✏️ Если понадобится что-то поменять — /myorders"
        )
    else:
        text = "👌 Готово! Если понадобится что-то поменять — /myorders"
    await safe_edit(callback.message, text)
    await state.clear()
    await callback.answer()


@dp.callback_query(F.data.startswith("editfield_"))
async def edit_field(callback: CallbackQuery, state: FSMContext):
    _, field, booking_id_str = callback.data.split("_")
    booking = get_own_booking(int(booking_id_str), callback.from_user.id)
    if not booking:
        await callback.answer("Бронь не найдена", show_alert=True)
        return

    booking_id = booking["id"]
    await state.update_data(editing_booking_id=booking_id)

    if field == "date":
        today = today_local()
        await safe_edit(
            callback.message,
            "📅 Выберите новую дату:",
            build_calendar(today.year, today.month, back_id=booking_id),
        )
        await state.set_state(Booking.editing_date)
    elif field == "time":
        await safe_edit(
            callback.message,
            f"⏰ Введите новое время (например: 19:00, 19 30 или 19)\n"
            f"Принимаем брони с {BOOKING_FROM:%H:%M} до {BOOKING_TO:%H:%M}.",
            back_keyboard(booking_id),
        )
        await state.set_state(Booking.editing_time)
    elif field == "guests":
        await safe_edit(
            callback.message,
            f"👥 Введите новое количество гостей (от 1 до {MAX_GUESTS})",
            back_keyboard(booking_id),
        )
        await state.set_state(Booking.editing_guests)
    elif field == "phone":
        await safe_edit(callback.message, "📞 Введите новый номер телефона", back_keyboard(booking_id))
        await state.set_state(Booking.editing_phone)
    elif field == "dishes":
        selected = copy.deepcopy(booking["selected_dishes"])
        await state.update_data(selected_dishes=selected)
        await safe_edit(
            callback.message,
            categories_screen_text(selected),
            categories_keyboard(selected, editing=True),
        )
        await state.set_state(Booking.picking_category)

    await callback.answer()


@dp.message(Booking.editing_time)
async def save_time(message: Message, state: FSMContext):
    booking = await current_editing_booking(message.from_user.id, state)
    if not booking:
        await session_expired(message, state)
        return

    t = parse_time(message.text)
    if t is None:
        await message.answer(TIME_ERR, reply_markup=back_keyboard(booking["id"]))
        return
    error = check_booking_time(t, booking["date"])
    if error:
        await message.answer(error, reply_markup=back_keyboard(booking["id"]))
        return

    await apply_booking_change(booking, "time", t.strftime("%H:%M"), f"время → {t:%H:%M}")
    await show_edit_menu(message, state, booking["id"], notice="✅ Время обновлено!")


@dp.message(Booking.editing_guests)
async def save_guests(message: Message, state: FSMContext):
    booking = await current_editing_booking(message.from_user.id, state)
    if not booking:
        await session_expired(message, state)
        return

    guests, error = parse_guests(message.text)
    if error:
        await message.answer(error, reply_markup=back_keyboard(booking["id"]))
        return

    await apply_booking_change(booking, "guests", guests, f"гостей → {guests}")
    await show_edit_menu(message, state, booking["id"], notice="✅ Количество гостей обновлено!")


@dp.message(Booking.editing_phone)
async def save_phone(message: Message, state: FSMContext):
    booking = await current_editing_booking(message.from_user.id, state)
    if not booking:
        await session_expired(message, state)
        return

    phone = extract_phone(message)
    if phone is None:
        await message.answer(PHONE_ERR, reply_markup=back_keyboard(booking["id"]))
        return

    await apply_booking_change(booking, "phone", phone, f"телефон → {phone}")
    await show_edit_menu(message, state, booking["id"], notice="✅ Телефон обновлён!")


@dp.callback_query(F.data.startswith("cancelbooking_"))
async def cancel_booking_ask(callback: CallbackQuery):
    booking = get_own_booking(int(callback.data.replace("cancelbooking_", "")), callback.from_user.id)
    if not booking:
        await callback.answer("Бронь не найдена", show_alert=True)
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Да, отменить", callback_data=f"cancelyes_{booking['id']}")],
        [InlineKeyboardButton(text="↩️ Нет, оставить", callback_data=f"editback_{booking['id']}")],
    ])
    await safe_edit(
        callback.message,
        booking_summary_text(booking, f"⚠️ Отменить бронь #{booking['id']}?"),
        keyboard,
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("cancelyes_"))
async def cancel_booking_confirm(callback: CallbackQuery, state: FSMContext):
    booking = get_own_booking(int(callback.data.replace("cancelyes_", "")), callback.from_user.id)
    if not booking:
        await callback.answer("Бронь уже отменена или не найдена", show_alert=True)
        return

    BOOKINGS.pop(booking["id"], None)
    save_bookings()
    await sync_group_message(booking, cancelled=True)

    await safe_edit(
        callback.message,
        f"🗑 Бронь #{booking['id']} отменена.\n\nБудем рады видеть вас снова! /start — новая бронь",
    )
    await state.clear()
    await callback.answer()


# ==================== ЗАПАСНЫЕ ОБРАБОТЧИКИ (всегда последними) ====================
@dp.message(StateFilter(Booking.waiting_for_date, Booking.editing_date))
async def hint_use_calendar(message: Message):
    await message.answer("📅 Пожалуйста, выберите дату в календаре выше 👆\nОтмена — /cancel")


@dp.message(StateFilter(Booking.picking_category, Booking.picking_dishes, Booking.edit_menu))
async def hint_use_buttons(message: Message):
    await message.answer("👆 Пожалуйста, используйте кнопки под сообщением.\nОтмена — /cancel")


@dp.message(F.chat.type == "private")
async def fallback_message(message: Message):
    await message.answer(
        "🤔 Не совсем понял.\n\n"
        "/start — новая бронь\n"
        "/myorders — мои брони\n"
        "/help — помощь"
    )


@dp.callback_query()
async def fallback_callback(callback: CallbackQuery):
    await callback.answer("⌛ Эта кнопка устарела. Нажмите /start, чтобы начать заново.", show_alert=True)


# ==================== ЗАПУСК ====================
async def main():
    load_bookings()
    await bot.set_my_commands([
        BotCommand(command="start", description="🍽 Забронировать столик"),
        BotCommand(command="myorders", description="📋 Мои брони"),
        BotCommand(command="cancel", description="❌ Прервать оформление"),
        BotCommand(command="help", description="ℹ️ Помощь"),
    ])
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())