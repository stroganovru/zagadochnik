# -*- coding: utf-8 -*-
"""SQLite: пользователи, сессии, статистика."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "data" / "game.db"

_local = threading.local()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    con = getattr(_local, "con", None)
    if con is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(DB_PATH, check_same_thread=False)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA foreign_keys=ON")
        _local.con = con
    return con


def init_db() -> None:
    con = connect()
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_key TEXT PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            riddles_shown INTEGER DEFAULT 0,
            riddles_revealed INTEGER DEFAULT 0,
            danetki_started INTEGER DEFAULT 0,
            danetki_solved INTEGER DEFAULT 0,
            danetki_surrendered INTEGER DEFAULT 0,
            questions_asked INTEGER DEFAULT 0,
            created_at TEXT,
            updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS sessions (
            user_key TEXT PRIMARY KEY,
            mode TEXT,
            difficulty TEXT,
            riddle_id INTEGER,
            danetka_id INTEGER,
            answer_shown INTEGER DEFAULT 0,
            hints_used INTEGER DEFAULT 0,
            seen_riddles TEXT DEFAULT '[]',
            seen_danetki TEXT DEFAULT '[]',
            updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS donations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_key TEXT NOT NULL,
            stars INTEGER NOT NULL,
            telegram_payment_charge_id TEXT UNIQUE,
            payload TEXT,
            created_at TEXT
        );
        """
    )
    cols = {row[1] for row in con.execute("PRAGMA table_info(users)")}
    if "stars_donated" not in cols:
        con.execute("ALTER TABLE users ADD COLUMN stars_donated INTEGER DEFAULT 0")
    con.commit()


def ensure_user(user_key: str, username: str | None = None, first_name: str | None = None) -> None:
    con = connect()
    row = con.execute("SELECT user_key FROM users WHERE user_key=?", (user_key,)).fetchone()
    if row:
        con.execute(
            "UPDATE users SET username=COALESCE(?, username), first_name=COALESCE(?, first_name), updated_at=? WHERE user_key=?",
            (username, first_name, _now(), user_key),
        )
    else:
        con.execute(
            "INSERT INTO users (user_key, username, first_name, created_at, updated_at) VALUES (?,?,?,?,?)",
            (user_key, username, first_name, _now(), _now()),
        )
    con.commit()


def get_user(user_key: str) -> dict:
    con = connect()
    row = con.execute("SELECT * FROM users WHERE user_key=?", (user_key,)).fetchone()
    if not row:
        ensure_user(user_key)
        row = con.execute("SELECT * FROM users WHERE user_key=?", (user_key,)).fetchone()
    return dict(row)


def bump(user_key: str, field: str, n: int = 1) -> None:
    allowed = {
        "riddles_shown",
        "riddles_revealed",
        "danetki_started",
        "danetki_solved",
        "danetki_surrendered",
        "questions_asked",
    }
    if field not in allowed:
        raise ValueError(field)
    con = connect()
    ensure_user(user_key)
    con.execute(
        f"UPDATE users SET {field} = {field} + ?, updated_at=? WHERE user_key=?",
        (n, _now(), user_key),
    )
    con.commit()


def get_session(user_key: str) -> dict:
    con = connect()
    row = con.execute("SELECT * FROM sessions WHERE user_key=?", (user_key,)).fetchone()
    if not row:
        con.execute(
            "INSERT INTO sessions (user_key, mode, seen_riddles, seen_danetki, updated_at) VALUES (?,?,?,?,?)",
            (user_key, "menu", "[]", "[]", _now()),
        )
        con.commit()
        row = con.execute("SELECT * FROM sessions WHERE user_key=?", (user_key,)).fetchone()
    data = dict(row)
    from engine import normalize_seen

    data["seen_riddles"] = normalize_seen(json.loads(data["seen_riddles"] or "[]"))
    data["seen_danetki"] = json.loads(data["seen_danetki"] or "[]")
    if not isinstance(data["seen_danetki"], list):
        data["seen_danetki"] = []
    return data


def save_session(user_key: str, **fields) -> dict:
    sess = get_session(user_key)
    sess.update(fields)
    con = connect()
    con.execute(
        """
        UPDATE sessions SET
            mode=?, difficulty=?, riddle_id=?, danetka_id=?,
            answer_shown=?, hints_used=?, seen_riddles=?, seen_danetki=?, updated_at=?
        WHERE user_key=?
        """,
        (
            sess.get("mode"),
            sess.get("difficulty"),
            sess.get("riddle_id"),
            sess.get("danetka_id"),
            int(sess.get("answer_shown") or 0),
            int(sess.get("hints_used") or 0),
            json.dumps(sess.get("seen_riddles") or []),
            json.dumps(sess.get("seen_danetki") or []),
            _now(),
            user_key,
        ),
    )
    con.commit()
    return sess


def record_donation(user_key: str, stars: int, charge_id: str, payload: str = "") -> bool:
    """True, если платёж новый. Повторный charge_id не плюсует звёзды."""
    con = connect()
    ensure_user(user_key)
    try:
        con.execute(
            "INSERT INTO donations (user_key, stars, telegram_payment_charge_id, payload, created_at) VALUES (?,?,?,?,?)",
            (user_key, int(stars), charge_id, payload, _now()),
        )
    except sqlite3.IntegrityError:
        con.rollback()
        return False
    con.execute(
        "UPDATE users SET stars_donated = COALESCE(stars_donated, 0) + ?, updated_at=? WHERE user_key=?",
        (int(stars), _now(), user_key),
    )
    con.commit()
    return True


def donation_totals(user_key: str | None = None) -> dict:
    con = connect()
    if user_key:
        row = con.execute(
            "SELECT COALESCE(SUM(stars),0) AS stars, COUNT(*) AS n FROM donations WHERE user_key=?",
            (user_key,),
        ).fetchone()
    else:
        row = con.execute(
            "SELECT COALESCE(SUM(stars),0) AS stars, COUNT(*) AS n FROM donations"
        ).fetchone()
    return {"stars": int(row["stars"]), "n": int(row["n"])}


def set_level_seen(user_key: str, level: str, ids: list[int]) -> None:
    """Заменить список показанных id одного уровня. Без усечения, без keep."""
    from engine import normalize_seen

    sess = get_session(user_key)
    seen = normalize_seen(sess.get("seen_riddles"))
    seen[level] = [int(i) for i in ids]
    save_session(user_key, seen_riddles=seen)
