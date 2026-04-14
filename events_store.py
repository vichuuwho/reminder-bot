import sqlite3
from dataclasses import dataclass
from pathlib import Path


DB_PATH = Path(__file__).with_name("events.db")


@dataclass(frozen=True)
class Event:
    id: int
    user_id: int
    title: str
    date: str
    time: str
    place: str
    remind_before_min: int
    repeat: str  # "once" | "daily"
    notified_for: str | None  # ISO string of event datetime for which reminder was already sent


def init_db(db_path: Path = DB_PATH) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                date TEXT NOT NULL,
                time TEXT NOT NULL,
                place TEXT NOT NULL,
                remind_before_min INTEGER NOT NULL DEFAULT 0,
                repeat TEXT NOT NULL DEFAULT 'once',
                notified_for TEXT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                tz_offset_min INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_user_id_id ON events(user_id, id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_user_id_date_time ON events(user_id, date, time)"
        )

        # Lightweight migration for older DBs: add missing columns if needed.
        cols = {
            row[1]: row[2]
            for row in conn.execute("PRAGMA table_info(events)").fetchall()
        }
        if "remind_before_min" not in cols:
            conn.execute("ALTER TABLE events ADD COLUMN remind_before_min INTEGER NOT NULL DEFAULT 0")
        if "repeat" not in cols:
            conn.execute("ALTER TABLE events ADD COLUMN repeat TEXT NOT NULL DEFAULT 'once'")
        if "notified_for" not in cols:
            conn.execute("ALTER TABLE events ADD COLUMN notified_for TEXT NULL")
        if "title" not in cols:
            conn.execute("ALTER TABLE events ADD COLUMN title TEXT NOT NULL DEFAULT ''")
        conn.commit()


def get_user_tz_offset_min(user_id: int, db_path: Path = DB_PATH) -> int:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT tz_offset_min FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    return int(row[0]) if row else 0


def set_user_tz_offset_min(user_id: int, tz_offset_min: int, db_path: Path = DB_PATH) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO users(user_id, tz_offset_min) VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET tz_offset_min = excluded.tz_offset_min
            """,
            (user_id, int(tz_offset_min)),
        )
        conn.commit()


def add_event(
    user_id: int,
    title: str,
    date: str,
    time: str,
    place: str,
    *,
    remind_before_min: int,
    repeat: str,
    db_path: Path = DB_PATH,
) -> int:
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO events(user_id, title, date, time, place, remind_before_min, repeat, notified_for)
            VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (
                user_id,
                title.strip(),
                date.strip(),
                time.strip(),
                place.strip(),
                int(remind_before_min),
                repeat.strip(),
            ),
        )
        conn.commit()
        return int(cur.lastrowid)


def list_events(user_id: int, db_path: Path = DB_PATH) -> list[Event]:
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, user_id, title, date, time, place, remind_before_min, repeat, notified_for
            FROM events
            WHERE user_id = ?
            ORDER BY id ASC
            """,
            (user_id,),
        ).fetchall()
    return [Event(*row) for row in rows]


def delete_event_by_index(user_id: int, index_1based: int, db_path: Path = DB_PATH) -> bool:
    events = list_events(user_id, db_path=db_path)
    if index_1based < 1 or index_1based > len(events):
        return False
    event_id = events[index_1based - 1].id
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute(
            "DELETE FROM events WHERE user_id = ? AND id = ?",
            (user_id, event_id),
        )
        conn.commit()
        return cur.rowcount > 0


def update_event_fields_by_index(
    user_id: int,
    index_1based: int,
    *,
    date: str | None = None,
    time: str | None = None,
    place: str | None = None,
    remind_before_min: int | None = None,
    repeat: str | None = None,
    reset_notified: bool = False,
    db_path: Path = DB_PATH,
) -> bool:
    events = list_events(user_id, db_path=db_path)
    if index_1based < 1 or index_1based > len(events):
        return False
    current = events[index_1based - 1]
    event_id = current.id

    new_date = current.date if date is None else date.strip()
    new_time = current.time if time is None else time.strip()
    new_place = current.place if place is None else place.strip()
    new_remind = current.remind_before_min if remind_before_min is None else int(remind_before_min)
    new_repeat = current.repeat if repeat is None else repeat.strip()
    new_notified_for = None if reset_notified else current.notified_for

    with sqlite3.connect(db_path) as conn:
        cur = conn.execute(
            """
            UPDATE events
            SET date = ?, time = ?, place = ?, remind_before_min = ?, repeat = ?, notified_for = ?
            WHERE user_id = ? AND id = ?
            """,
            (
                new_date,
                new_time,
                new_place,
                new_remind,
                new_repeat,
                new_notified_for,
                user_id,
                event_id,
            ),
        )
        conn.commit()
        return cur.rowcount > 0


def set_notified_for_event_id(user_id: int, event_id: int, notified_for: str | None, db_path: Path = DB_PATH) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE events SET notified_for = ? WHERE user_id = ? AND id = ?",
            (notified_for, user_id, event_id),
        )
        conn.commit()


def delete_event_id(user_id: int, event_id: int, db_path: Path = DB_PATH) -> bool:
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute(
            "DELETE FROM events WHERE user_id = ? AND id = ?",
            (user_id, event_id),
        )
        conn.commit()
        return cur.rowcount > 0


def update_event_fields_by_id(
    user_id: int,
    event_id: int,
    *,
    title: str | None = None,
    date: str | None = None,
    time: str | None = None,
    place: str | None = None,
    remind_before_min: int | None = None,
    repeat: str | None = None,
    reset_notified: bool = False,
    db_path: Path = DB_PATH,
) -> bool:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT title, date, time, place, remind_before_min, repeat, notified_for
            FROM events
            WHERE user_id = ? AND id = ?
            """,
            (user_id, event_id),
        ).fetchone()
        if not row:
            return False
        cur_title, cur_date, cur_time, cur_place, cur_remind, cur_repeat, cur_notified = row

        new_title = cur_title if title is None else title.strip()
        new_date = cur_date if date is None else date.strip()
        new_time = cur_time if time is None else time.strip()
        new_place = cur_place if place is None else place.strip()
        new_remind = cur_remind if remind_before_min is None else int(remind_before_min)
        new_repeat = cur_repeat if repeat is None else repeat.strip()
        new_notified_for = None if reset_notified else cur_notified

        cur = conn.execute(
            """
            UPDATE events
            SET title = ?, date = ?, time = ?, place = ?, remind_before_min = ?, repeat = ?, notified_for = ?
            WHERE user_id = ? AND id = ?
            """,
            (
                new_title,
                new_date,
                new_time,
                new_place,
                new_remind,
                new_repeat,
                new_notified_for,
                user_id,
                event_id,
            ),
        )
        conn.commit()
        return cur.rowcount > 0

