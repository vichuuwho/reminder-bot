from __future__ import annotations

import asyncio
import os
import re
from datetime import date as Date, datetime, timedelta, timezone
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

load_dotenv()
TOKEN = os.getenv("tg_token")

PROXY_URL = os.getenv("PROXY_URL")
session = AiohttpSession(proxy=PROXY_URL) if PROXY_URL else None

bot = Bot(token=TOKEN, session=session) if session else Bot(token=TOKEN)
dp = Dispatcher()

from events_store import (
    add_event,
    delete_event_by_index,
    get_user_tz_offset_min,
    init_db,
    list_events,
    set_notified_for_event_id,
    set_user_tz_offset_min,
    update_event_fields_by_id,
    update_event_fields_by_index,
    delete_event_id,
)


DATE_RE = re.compile(r"^\s*(\d{1,2})\.(\d{1,2})\.(\d{4})\s*$")
TIME_RE = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*$")


def _parse_date(s: str) -> Date | None:
    m = DATE_RE.match(s or "")
    if not m:
        return None
    d, mo, y = map(int, m.groups())
    try:
        return Date(year=y, month=mo, day=d)
    except ValueError:
        return None


def _parse_time(s: str) -> tuple[int, int] | None:
    m = TIME_RE.match(s or "")
    if not m:
        return None
    hh, mm = map(int, m.groups())
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        return None
    return hh, mm


def _user_tz(user_id: int) -> timezone:
    offset_min = get_user_tz_offset_min(user_id)
    return timezone(timedelta(minutes=offset_min))


def _event_dt_user_tz(user_id: int, date_s: str, time_s: str) -> datetime | None:
    d = _parse_date(date_s)
    t = _parse_time(time_s)
    if not d or not t:
        return None
    hh, mm = t
    return datetime(d.year, d.month, d.day, hh, mm, tzinfo=_user_tz(user_id))


def _format_tz_offset(offset_min: int) -> str:
    sign = "+" if offset_min >= 0 else "-"
    v = abs(int(offset_min))
    hh = v // 60
    mm = v % 60
    return f"UTC{sign}{hh:02d}:{mm:02d}"


def _parse_tz_offset(text: str) -> int | None:
    # accepts: +3, -5, +03:00, -0430, UTC+3
    s = (text or "").strip().upper().replace("UTC", "").strip()
    m = re.match(r"^([+-])\s*(\d{1,2})(?::?(\d{2}))?\s*$", s)
    if not m:
        return None
    sign, hh, mm = m.group(1), int(m.group(2)), int(m.group(3) or 0)
    if hh > 14 or mm > 59:
        return None
    total = hh * 60 + mm
    return total if sign == "+" else -total


def _parse_msk_diff(text: str) -> int | None:
    s = (text or "").strip().upper().replace("МСК", "").replace("MSK", "").strip()
    m = re.match(r"^([+-])\s*(\d{1,2})(?::?(\d{2}))?\s*$", s)
    if not m:
        return None
    sign, hh, mm = m.group(1), int(m.group(2)), int(m.group(3) or 0)
    if hh > 14 or mm > 59:
        return None
    total = hh * 60 + mm
    return total if sign == "+" else -total


class AddEventStates(StatesGroup):
    title = State()
    date = State()
    time = State()
    place = State()
    remind_before = State()
    repeat = State()


class EditEventStates(StatesGroup):
    pick = State()
    field = State()
    value = State()


class DeleteEventStates(StatesGroup):
    pick = State()


class MskDiffStates(StatesGroup):
    diff = State()


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        f"Привет, {message.from_user.first_name}! Готов записать твои события.\n\n"
        "Команды:\n"
        "/add_event — добавить событие\n"
        "/events — список событий\n"
        "/delete_event — удалить (выбор из списка)\n"
        "/edit_event — редактировать (выбор из списка)\n"
        "/your_time — установить разницу с Москвой"
    )


@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer(
        "Команды:\n"
        "/add_event — добавить событие\n"
        "/events — список событий\n"
        "/delete_event — удалить (выбор из списка)\n"
        "/edit_event — редактировать (выбор из списка)\n"
        "/your_time — установить разницу с Москвой"
    )


@dp.message(Command("your_time"))
async def cmd_your_time(message: types.Message, state: FSMContext):
    await state.clear()
    await state.set_state(MskDiffStates.diff)
    await message.answer(
        "Какая у тебя разница с время МСК?\n"
        "Примеры: +2, -1, +02:30.\n"
        "Если у тебя Москва — напиши +0."
    )


@dp.message(MskDiffStates.diff)
async def msk_diff_set(message: types.Message, state: FSMContext):
    diff_min = _parse_msk_diff(message.text or "")
    if diff_min is None:
        await message.answer("Не понял. Примеры: +2, -1, +02:30")
        return

    user_offset = 180 + diff_min
    if user_offset < -14 * 60 or user_offset > 14 * 60:
        await message.answer("Не похоже на реальный часовой пояс. Ты врун. Напиши снова.")
        return

    set_user_tz_offset_min(message.from_user.id, user_offset)
    await state.clear()
    await message.answer(f"Ок! Твой часовой пояс теперь {_format_tz_offset(user_offset)}")


@dp.message(Command("cancel"))
async def cmd_cancel(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state and current_state.startswith("AddEventStates:"):
        await state.clear()
        await message.answer("Создание события отменено.")
        return
    await message.answer("Сейчас нечего отменять.")


@dp.message(Command("add_event"))
async def cmd_add_event(message: types.Message, state: FSMContext):
    await state.clear()
    await state.set_state(AddEventStates.title)
    await message.answer(
        "Введи название события (например День рождения, Встреча, Собеседование).\n"
        "Чтобы отменить создание, напиши /cancel"
    )


@dp.message(AddEventStates.title)
async def add_event_title(message: types.Message, state: FSMContext):
    title = (message.text or "").strip()
    if not title:
        await message.answer("Название не должно быть пустым. Введи снова.")
        return
    await state.update_data(title=title)
    await state.set_state(AddEventStates.date)
    await message.answer("Введи дату события (например 14.04.2026).")


@dp.message(AddEventStates.date)
async def add_event_date(message: types.Message, state: FSMContext):
    date_s = (message.text or "").strip()
    parsed = _parse_date(date_s)
    if parsed is None:
        await message.answer("Неверный формат даты.")
        return

    now_user = datetime.now(tz=_user_tz(message.from_user.id))
    if parsed < now_user.date():
        await message.answer("Эта дата уже прошла.")
        return

    await state.update_data(date=date_s)
    await state.set_state(AddEventStates.time)
    await message.answer("Введи время (например 18:30).")


@dp.message(AddEventStates.time)
async def add_event_time(message: types.Message, state: FSMContext):
    time_s = (message.text or "").strip()
    if _parse_time(time_s) is None:
        await message.answer("Неверный формат времени.")
        return
    await state.update_data(time=time_s)

    data = await state.get_data()
    date_s = (data.get("date") or "").strip()
    dt = _event_dt_user_tz(message.from_user.id, date_s, time_s)
    if dt is None:
        await state.clear()
        await message.answer("Не смог распознать дату/время. Попробуй ещё раз: /add_event")
        return
    now_user = datetime.now(tz=_user_tz(message.from_user.id))
    if dt <= now_user:
        await state.clear()
        await message.answer("Это время уже прошло. Попробуй ещё раз: /add_event")
        return

    await state.set_state(AddEventStates.place)
    await message.answer("Введи место (например Дом/Офис/Кафе).")


@dp.message(AddEventStates.place)
async def add_event_place(message: types.Message, state: FSMContext):
    data = await state.get_data()
    date = (data.get("date") or "").strip()
    time = (data.get("time") or "").strip()
    place = (message.text or "").strip()

    if not date or not time or not place:
        await state.clear()
        await message.answer("Поля не должны быть пустыми. Попробуй ещё раз: /add_event")
        return

    event_dt = _event_dt_user_tz(message.from_user.id, date, time)
    if event_dt is None:
        await state.clear()
        await message.answer("Не смогла распознать дату/время. Попробуй ещё раз: /add_event")
        return

    now_user = datetime.now(tz=_user_tz(message.from_user.id))
    if event_dt <= now_user:
        await state.clear()
        await message.answer("Это время уже в прошлом по твоему часовому поясу. Попробуй ещё раз: /add_event")
        return

    await state.update_data(place=place)
    await state.set_state(AddEventStates.remind_before)
    await message.answer("За сколько минут напомнить? (например 10). Напиши 0, если не надо.")


@dp.message(AddEventStates.remind_before)
async def add_event_remind_before(message: types.Message, state: FSMContext):
    s = (message.text or "").strip()
    if not s.isdigit():
        await message.answer("Нужно число целое.")
        return
    minutes = int(s)
    if minutes < 0 or minutes > 7 * 24 * 60:
        await message.answer("Слишком большое число. Давай до 10080 минут (7 дней).")
        return
    await state.update_data(remind_before_min=minutes)
    await state.set_state(AddEventStates.repeat)
    await message.answer("Напоминание один раз или каждый день? Напиши 1 (один раз) или 2 (ежедневно).")


@dp.message(AddEventStates.repeat)
async def add_event_repeat(message: types.Message, state: FSMContext):
    choice = (message.text or "").strip()
    if choice not in {"1", "2"}:
        await message.answer("Ответь нормально(")
        return
    repeat = "once" if choice == "1" else "daily"

    data = await state.get_data()
    title = (data.get("title") or "").strip()
    date = (data.get("date") or "").strip()
    time = (data.get("time") or "").strip()
    place = (data.get("place") or "").strip()
    remind_before_min = int(data.get("remind_before_min") or 0)

    dt = _event_dt_user_tz(message.from_user.id, date, time)
    if dt is None:
        await state.clear()
        await message.answer("Не смог распознать дату/время. Попробуй ещё раз: /add_event")
        return
    now_user = datetime.now(tz=_user_tz(message.from_user.id))
    if dt <= now_user:
        await state.clear()
        await message.answer("Пока мы вводили данные, время уже стало прошлым, блин. Попробуй ещё раз: /add_event")
        return

    add_event(
        user_id=message.from_user.id,
        title=title,
        date=date,
        time=time,
        place=place,
        remind_before_min=remind_before_min,
        repeat=repeat,
    )
    await state.clear()
    await message.answer("Событие добавлено. Список: /events")


def _cleanup_and_roll_user_events(user_id: int) -> None:
    tz = _user_tz(user_id)
    now_user = datetime.now(tz=tz)
    events = list_events(user_id=user_id)
    for e in events:
        dt = _event_dt_user_tz(user_id, e.date, e.time)
        if dt is None:
            continue

        if now_user > dt:
            if e.repeat == "daily":
                next_dt = dt
                while next_dt <= now_user:
                    next_dt = next_dt + timedelta(days=1)
                update_event_fields_by_id(
                    user_id=user_id,
                    event_id=e.id,
                    date=next_dt.strftime("%d.%m.%Y"),
                    time=next_dt.strftime("%H:%M"),
                    reset_notified=True,
                )
            else:
                delete_event_id(user_id=user_id, event_id=e.id)


@dp.message(Command("events"))
async def cmd_events(message: types.Message):
    _cleanup_and_roll_user_events(message.from_user.id)
    events = list_events(user_id=message.from_user.id)
    if not events:
        await message.answer("Событий пока нет. Добавить: /add_event")
        return

    lines: list[str] = ["Твои события:"]
    for i, e in enumerate(events, start=1):
        rep = "один раз" if e.repeat == "once" else "ежедневно"
        remind = f", напомнить за {e.remind_before_min} мин" if e.remind_before_min else ""
        title = e.title.strip() or "Без названия"
        lines.append(f"{i}) {title}: {e.date} {e.time} — {e.place} ({rep}{remind})")
    lines.append("")
    lines.append("Удалить: /delete_event")
    lines.append("Редактировать: /edit_event")
    await message.answer("\n".join(lines))


@dp.message(Command("delete_event"))
async def cmd_delete_event(message: types.Message, state: FSMContext):
    _cleanup_and_roll_user_events(message.from_user.id)
    events = list_events(user_id=message.from_user.id)
    if not events:
        await message.answer("Событий нет. /add_event")
        return

    lines = ["Что удалить? Напиши индекс из списка:"]
    for i, e in enumerate(events, start=1):
        title = e.title.strip() or "Без названия"
        lines.append(f"{i}) {title}: {e.date} {e.time} — {e.place}")
    await state.clear()
    await state.set_state(DeleteEventStates.pick)
    await message.answer("\n".join(lines))


@dp.message(DeleteEventStates.pick)
async def delete_pick(message: types.Message, state: FSMContext):
    s = (message.text or "").strip()
    if not s.isdigit():
        await message.answer("Нужен индекс числом.")
        return
    idx = int(s)
    ok = delete_event_by_index(user_id=message.from_user.id, index_1based=idx)
    await state.clear()
    await message.answer("Удалено. /events" if ok else "Не нашел такой индекс. /events")


@dp.message(Command("edit_event"))
async def cmd_edit_event(message: types.Message, state: FSMContext):
    _cleanup_and_roll_user_events(message.from_user.id)
    events = list_events(user_id=message.from_user.id)
    if not events:
        await message.answer("Событий нет. /add_event")
        return

    lines = ["Что редактировать? Напиши индекс из списка:"]
    for i, e in enumerate(events, start=1):
        title = e.title.strip() or "Без названия"
        lines.append(f"{i}) {title}: {e.date} {e.time} — {e.place}")
    await state.clear()
    await state.set_state(EditEventStates.pick)
    await message.answer("\n".join(lines))


@dp.message(EditEventStates.pick)
async def edit_pick(message: types.Message, state: FSMContext):
    s = (message.text or "").strip()
    if not s.isdigit():
        await message.answer("Нужен индекс числом.")
        return
    idx = int(s)
    events = list_events(user_id=message.from_user.id)
    if idx < 1 or idx > len(events):
        await message.answer("Не нашел такой индекс. Попробуй ещё раз.")
        return
    await state.update_data(index=idx)
    await state.set_state(EditEventStates.field)
    await message.answer(
        "Что изменить?\n"
        "1) название\n"
        "2) дата\n"
        "3) время\n"
        "4) место\n"
        "5) за сколько минут напоминать\n"
        "6) повтор (один раз/ежедневно)\n"
        "Напиши номер."
    )


@dp.message(EditEventStates.field)
async def edit_field(message: types.Message, state: FSMContext):
    field = (message.text or "").strip()
    if field not in {"1", "2", "3", "4", "5", "6"}:
        await message.answer("Нужно число 1-6.")
        return
    await state.update_data(field=field)
    await state.set_state(EditEventStates.value)
    if field == "1":
        await message.answer("Введи новое название.")
    elif field == "2":
        await message.answer("Введи новую дату (14.04.2026).")
    elif field == "3":
        await message.answer("Введи новое время (18:30).")
    elif field == "4":
        await message.answer("Введи новое место.")
    else:
        if field == "5":
            await message.answer("Введи минуты (например 10 или 0).")
        else:
            await message.answer("1 — один раз, 2 — ежедневно.")


@dp.message(EditEventStates.value)
async def edit_value(message: types.Message, state: FSMContext):
    data = await state.get_data()
    idx = int(data.get("index") or 0)
    field = data.get("field")
    value = (message.text or "").strip()

    if not idx or field is None:
        await state.clear()
        await message.answer("Что-то пошло не так. /edit_event")
        return

    kwargs: dict[str, object] = {}
    if field == "1":
        if not value:
            await message.answer("Название не должно быть пустым.")
            return
        kwargs["title"] = value
    elif field == "2":
        if _parse_date(value) is None:
            await message.answer("Неверный формат даты.")
            return
        kwargs["date"] = value
    elif field == "3":
        if _parse_time(value) is None:
            await message.answer("Неверный формат времени.")
            return
        kwargs["time"] = value
    elif field == "4":
        if not value:
            await message.answer("Место не должно быть пустым.")
            return
        kwargs["place"] = value
    elif field == "5":
        if not value.isdigit():
            await message.answer("Нужно число минут.")
            return
        minutes = int(value)
        if minutes < 0 or minutes > 7 * 24 * 60:
            await message.answer("Слишком большое число. Давай до 10080 минут (7 дней).")
            return
        kwargs["remind_before_min"] = minutes
        kwargs["reset_notified"] = True
    else:
        if value not in {"1", "2"}:
            await message.answer("Ответь 1 или 2.")
            return
        kwargs["repeat"] = "once" if value == "1" else "daily"
        kwargs["reset_notified"] = True

    events = list_events(user_id=message.from_user.id)
    if 1 <= idx <= len(events) and field in {"2", "3"}:
        e = events[idx - 1]
        new_date = kwargs.get("date", e.date)
        new_time = kwargs.get("time", e.time)
        dt = _event_dt_user_tz(message.from_user.id, str(new_date), str(new_time))
        if dt is None:
            await message.answer("Не смог распознать дату/время.")
            return
        now_user = datetime.now(tz=_user_tz(message.from_user.id))
        if dt <= now_user:
            await message.answer("Это время уже в прошло.")
            return
        kwargs["reset_notified"] = True

    ok = update_event_fields_by_index(user_id=message.from_user.id, index_1based=idx, **kwargs)
    await state.clear()
    await message.answer("Готово. /events" if ok else "Не получилось обновить. /events")


async def reminder_loop() -> None:
    while True:
        try:
            import sqlite3
            from events_store import DB_PATH

            with sqlite3.connect(DB_PATH) as conn:
                user_rows = conn.execute("SELECT DISTINCT user_id FROM events").fetchall()
            user_ids = [int(r[0]) for r in user_rows]

            for user_id in user_ids:
                _cleanup_and_roll_user_events(user_id)
                tz = _user_tz(user_id)
                now_user = datetime.now(tz=tz)
                events = list_events(user_id=user_id)
                for e in events:
                    dt = _event_dt_user_tz(user_id, e.date, e.time)
                    if dt is None:
                        continue

                    if e.remind_before_min <= 0:
                        continue

                    trigger_at = dt - timedelta(minutes=e.remind_before_min)
                    if now_user >= trigger_at:
                        notified_key = dt.isoformat()
                        if e.notified_for == notified_key:
                            continue
                        await bot.send_message(
                            user_id,
                            f"Скоро событие: {e.date} {e.time} — {e.place}\n"
                            f"(через {e.remind_before_min} мин)",
                        )
                        set_notified_for_event_id(
                            user_id=user_id, event_id=e.id, notified_for=notified_key
                        )
        except Exception:
            continue
        await asyncio.sleep(30)


async def main():
    init_db()
    asyncio.create_task(reminder_loop())
    await bot.get_me()
    await dp.start_polling(bot, polling_timeout=5)


if __name__ == '__main__':
    asyncio.run(main())
