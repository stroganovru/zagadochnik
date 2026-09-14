# -*- coding: utf-8 -*-
"""Telegram-бот логических задач."""

from __future__ import annotations

import hashlib
import logging
import os
import re
from html import escape
from pathlib import Path

from dotenv import load_dotenv
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.error import BadRequest, TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    PreCheckoutQueryHandler,
    filters,
)

import db
from engine import counts, get_riddle, pick_random_riddle
from game_data import LEVEL_ORDER

_ROOT = Path(__file__).resolve().parent
load_dotenv(_ROOT / ".env")

_LOG_PATH = _ROOT / "data" / "bot.log"
_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(_LOG_PATH, encoding="utf-8"),
    ],
)
log = logging.getLogger("zagadochnik")

_COUNTS = counts()
_COUNT_LINE = (
    f"В базе: лёгких {_COUNTS.get('easy', 0)}, "
    f"средних {_COUNTS.get('medium', 0)}, "
    f"сложных {_COUNTS.get('hard', 0)}."
)

WELCOME = (
    "<b>Загадочник</b>\n"
    "Логические задачи — фольклор, Перельман, Кордемский, Смаллиан, кружки XX века.\n\n"
    f"{_COUNT_LINE}\n\n"
    "Ответ спрятан за кнопкой, следующая выпадает случайно.\n"
    "Выберите режим."
)

HELP = (
    "<b>Как играть</b>\n\n"
    "Выберите сложность — бот даст случайную задачу из собранной базы. "
    "Подумайте сами, затем «Ответ». «Следующая» — новая случайная "
    "без повторов до конца круга уровня; потом круг начнётся заново.\n\n"
    f"{_COUNT_LINE}\n\n"
    "<b>Поддержать.</b> Меню «Поддержать проект» или /donate — Telegram Stars."
)

STAR_PRESETS = (15, 50, 100, 250, 500, 1000)
STARS_MIN = 1
STARS_MAX = 10_000

DONATE_TEXT = (
    "⭐ <b>Поддержать проект</b>\n\n"
    "Загадочник — чат с базой логических задач, без рекламы. "
    "Любое число <b>Telegram Stars</b> — хоть одну.\n\n"
    "Пресет или «Своя сумма»."
)


def ukey(update: Update) -> str:
    return f"tg:{update.effective_user.id}"


def remember(update: Update) -> str:
    u = update.effective_user
    key = ukey(update)
    db.ensure_user(key, u.username, u.first_name)
    return key


def kb_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🧩 Задачи", callback_data="m:riddles")],
            [
                InlineKeyboardButton("📊 Статистика", callback_data="m:stats"),
                InlineKeyboardButton("ℹ️ Как играть", callback_data="m:help"),
            ],
            [InlineKeyboardButton("⭐ Поддержать проект", callback_data="m:donate")],
        ]
    )


def kb_levels() -> InlineKeyboardMarkup:
    e, m, h = _COUNTS.get("easy", 0), _COUNTS.get("medium", 0), _COUNTS.get("hard", 0)
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(f"🟢 Лёгкие ({e})", callback_data="lvl:easy")],
            [InlineKeyboardButton(f"🟡 Средние ({m})", callback_data="lvl:medium")],
            [InlineKeyboardButton(f"🔴 Сложные ({h})", callback_data="lvl:hard")],
            [InlineKeyboardButton("🔙 Меню", callback_data="m:home")],
        ]
    )


def kb_riddle(shown: bool) -> InlineKeyboardMarkup:
    row = []
    if not shown:
        row.append(InlineKeyboardButton("💡 Ответ", callback_data="r:answer"))
    row.append(InlineKeyboardButton("🎲 Следующая", callback_data="r:next"))
    return InlineKeyboardMarkup(
        [
            row,
            [
                InlineKeyboardButton("📶 Уровень", callback_data="m:riddles"),
                InlineKeyboardButton("🔙 Меню", callback_data="m:home"),
            ],
        ]
    )


def kb_reply() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            ["🧩 Задачи", "📊 Статистика"],
            ["ℹ️ Как играть", "⭐ Поддержать"],
        ],
        resize_keyboard=True,
    )


def kb_donate() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for n in STAR_PRESETS:
        row.append(InlineKeyboardButton(f"⭐ {n}", callback_data=f"don:{n}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("✏️ Своя сумма", callback_data="don:custom")])
    rows.append([InlineKeyboardButton("🔙 Меню", callback_data="m:home")])
    return InlineKeyboardMarkup(rows)


def fmt_riddle(r: dict, shown: bool) -> str:
    head = (
        f"🧩 <b>{escape(r['title'])}</b>\n\n"
        f"{escape(r['text'])}"
    )
    if shown:
        head += f"\n\n💡 <b>Ответ</b>\n{escape(r['answer'])}"
        if r.get("source"):
            head += f"\n\n<i>Источник: {escape(r['source'])}</i>"
    else:
        head += "\n\n<i>Ответ — по кнопке.</i>"
    return head


def fmt_stats(user: dict) -> str:
    stars = int(user.get("stars_donated") or 0)
    return (
        "📊 <b>Ваша статистика</b>\n\n"
        f"Задачи показаны: <b>{user['riddles_shown']}</b>\n"
        f"Ответы открыты: <b>{user['riddles_revealed']}</b>\n"
        f"⭐ Поддержали проект: <b>{stars}</b> зв.\n\n"
        f"{_COUNT_LINE}"
    )


def parse_stars(text: str) -> int | None:
    m = re.search(r"\d+", text.replace(" ", "").replace("\u00a0", ""))
    if not m:
        return None
    try:
        return int(m.group(0))
    except ValueError:
        return None


async def send_stars_invoice(
    update: Update, context: ContextTypes.DEFAULT_TYPE, amount: int
) -> None:
    chat = update.effective_chat
    user = update.effective_user
    if amount < STARS_MIN or amount > STARS_MAX:
        await update.effective_message.reply_text(
            f"Сумма — целое число от {STARS_MIN} до {STARS_MAX} звёзд.",
            reply_markup=kb_donate(),
        )
        return
    payload = f"donate:{user.id}:{amount}"
    try:
        await context.bot.send_invoice(
            chat_id=chat.id,
            title="Загадочник",
            description=f"Поддержка проекта · {amount} Telegram Stars",
            payload=payload,
            provider_token=None,
            currency="XTR",
            prices=[LabeledPrice(label="Донат", amount=amount)],
        )
    except TelegramError as exc:
        log.warning("invoice failed: %s", exc)
        await update.effective_message.reply_text(
            "Не вышло выставить счёт. Попробуйте другую сумму или позже.\n"
            f"<i>{escape(str(exc))}</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=kb_donate(),
        )


async def _send_text(message, text: str, markup: InlineKeyboardMarkup) -> None:
    try:
        await message.reply_text(
            text, parse_mode=ParseMode.HTML, reply_markup=markup
        )
        return
    except Exception as exc:
        log.warning("html reply failed: %s", exc)
    await message.reply_text(re.sub(r"<[^>]+>", "", text), reply_markup=markup)


async def show(update: Update, text: str, markup: InlineKeyboardMarkup) -> None:
    q = update.callback_query
    if q:
        try:
            await q.edit_message_text(
                text, parse_mode=ParseMode.HTML, reply_markup=markup
            )
            return
        except BadRequest as exc:
            if "not modified" in str(exc).lower():
                return
            log.warning("edit failed: %s", exc)
        except Exception as exc:
            log.warning("edit failed: %s", exc)
        target = q.message or update.effective_message
        if target is not None and hasattr(target, "reply_text"):
            await _send_text(target, text, markup)
        return
    await _send_text(update.effective_message, text, markup)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    key = remember(update)
    db.save_session(key, mode="menu", answer_shown=0)
    await show(update, WELCOME, kb_main())
    if update.effective_message:
        await update.effective_message.reply_text(
            "Если верхние кнопки не открываются — меню внизу экрана.",
            reply_markup=kb_reply(),
        )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    remember(update)
    await show(update, HELP, kb_main())


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    key = remember(update)
    await show(update, fmt_stats(db.get_user(key)), kb_main())


async def cmd_donate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    key = remember(update)
    db.save_session(key, mode="donate")
    args = context.args or []
    if args:
        n = parse_stars(" ".join(args))
        if n is None:
            await show(update, DONATE_TEXT, kb_donate())
            return
        await send_stars_invoice(update, context, n)
        return
    await show(update, DONATE_TEXT, kb_donate())


def start_riddle(key: str, level: str) -> tuple[str, InlineKeyboardMarkup]:
    sess = db.get_session(key)
    r, wrapped, shown = pick_random_riddle(level, sess["seen_riddles"])
    if not r:
        return "В этом уровне пока пусто.", kb_levels()
    new_shown = shown + [r["id"]]
    db.save_session(
        key,
        mode="riddle",
        difficulty=level,
        riddle_id=r["id"],
        danetka_id=None,
        answer_shown=0,
        hints_used=0,
    )
    db.set_level_seen(key, level, new_shown)
    db.bump(key, "riddles_shown")
    text = fmt_riddle(r, False)
    if wrapped:
        text = "🔁 <b>Круг пройден</b> — начинаем этот уровень заново.\n\n" + text
    return text, kb_riddle(False)


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    try:
        await q.answer()
    except Exception as exc:
        log.warning("answer failed: %s", exc)
    try:
        await _on_callback_body(update, context)
    except Exception:
        log.exception("callback %s", getattr(q, "data", None))
        try:
            await show(
                update,
                "Не получилось открыть. Нажмите /start или кнопку внизу.",
                kb_main(),
            )
        except Exception:
            pass


async def _on_callback_body(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    key = remember(update)
    data = q.data or ""
    sess = db.get_session(key)
    log.info("callback %s from %s", data, key)

    if data == "m:home":
        db.save_session(key, mode="menu")
        await show(update, WELCOME, kb_main())
        return
    if data == "m:help":
        await show(update, HELP, kb_main())
        return
    if data == "m:stats":
        await show(update, fmt_stats(db.get_user(key)), kb_main())
        return
    if data == "m:riddles":
        db.save_session(key, mode="riddle_levels")
        await show(
            update,
            "🧩 <b>Логические задачи</b>\n"
            "Классика, не сгенерированные клоны. Выберите уровень.",
            kb_levels(),
        )
        return
    if data == "m:donate":
        db.save_session(key, mode="donate")
        await show(update, DONATE_TEXT, kb_donate())
        return
    if data == "don:custom":
        db.save_session(key, mode="donate_amount")
        await show(
            update,
            "✏️ <b>Своя сумма</b>\n\n"
            f"Напишите целое число звёзд — от <b>{STARS_MIN}</b> до <b>{STARS_MAX}</b>.",
            kb_donate(),
        )
        return
    if data.startswith("don:"):
        n = parse_stars(data.split(":", 1)[1])
        if n is None:
            await update.effective_message.reply_text(
                "Некорректная сумма.", reply_markup=kb_donate()
            )
            return
        db.save_session(key, mode="donate")
        await send_stars_invoice(update, context, n)
        return
    if data.startswith("lvl:"):
        level = data.split(":", 1)[1]
        if level not in LEVEL_ORDER:
            return
        text, markup = start_riddle(key, level)
        await show(update, text, markup)
        return
    if data == "r:next":
        level = sess.get("difficulty") or "easy"
        text, markup = start_riddle(key, level)
        await show(update, text, markup)
        return
    if data == "r:answer":
        r = get_riddle(sess.get("riddle_id") or -1)
        if not r:
            await show(update, "Сначала выберите задачу.", kb_levels())
            return
        if not sess.get("answer_shown"):
            db.bump(key, "riddles_revealed")
            db.save_session(key, answer_shown=1)
        await show(update, fmt_riddle(r, True), kb_riddle(True))
        return


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message or not update.effective_message.text:
        return
    key = remember(update)
    sess = db.get_session(key)
    text = update.effective_message.text.strip()

    if sess.get("mode") == "donate_amount":
        n = parse_stars(text)
        if n is None:
            await update.effective_message.reply_text(
                f"Нужно целое число от {STARS_MIN} до {STARS_MAX}.",
                reply_markup=kb_donate(),
            )
            return
        db.save_session(key, mode="donate")
        await send_stars_invoice(update, context, n)
        return

    compact = (
        text.replace("🧩", "")
        .replace("📊", "")
        .replace("ℹ️", "")
        .replace("⭐", "")
        .strip()
        .lower()
    )
    if compact in {"задачи", "задача"}:
        db.save_session(key, mode="riddle_levels")
        await show(
            update,
            "🧩 <b>Логические задачи</b>\n"
            "Классика, не сгенерированные клоны. Выберите уровень.",
            kb_levels(),
        )
        return
    if compact == "статистика":
        await show(update, fmt_stats(db.get_user(key)), kb_main())
        return
    if compact in {"как играть", "помощь", "help"}:
        await show(update, HELP, kb_main())
        return
    if compact in {"поддержать", "поддержать проект", "донат", "donate"}:
        db.save_session(key, mode="donate")
        await show(update, DONATE_TEXT, kb_donate())
        return

    await update.effective_message.reply_text(
        "Откройте задачи кнопками ниже или меню внизу экрана.",
        reply_markup=kb_main(),
        parse_mode=ParseMode.HTML,
    )


async def on_precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.pre_checkout_query
    payload = q.invoice_payload or ""
    if not payload.startswith("donate:") or q.currency != "XTR":
        await q.answer(ok=False, error_message="Этот счёт не от Загадочника.")
        return
    amount = int(q.total_amount or 0)
    if amount < STARS_MIN or amount > STARS_MAX:
        await q.answer(ok=False, error_message="Сумма вне диапазона.")
        return
    await q.answer(ok=True)


async def on_successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    key = remember(update)
    pay = update.effective_message.successful_payment
    stars = int(pay.total_amount)
    charge = pay.telegram_payment_charge_id or pay.provider_payment_charge_id or ""
    fresh = db.record_donation(key, stars, charge, pay.invoice_payload or "")
    db.save_session(key, mode="menu")
    if fresh:
        text = (
            f"Спасибо. Дошло <b>{stars}</b> ⭐.\n"
            f"Всего от вас: <b>{int(db.get_user(key).get('stars_donated') or 0)}</b> ⭐"
        )
    else:
        text = "Этот платёж уже учтён. Спасибо ещё раз."
    await update.effective_message.reply_text(
        text, parse_mode=ParseMode.HTML, reply_markup=kb_main()
    )


def webhook_secret(token: str) -> str:
    return hashlib.sha256(f"zagadochnik:{token}".encode()).hexdigest()[:32]


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.exception("update failed: %s", context.error)


def build_application(*, webhook: bool = False) -> Application:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token or token.startswith("123456"):
        raise RuntimeError("Нет TELEGRAM_BOT_TOKEN")
    builder = Application.builder().token(token).concurrent_updates(False)
    if webhook:
        builder = builder.updater(None).job_queue(None)
    app = builder.build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("donate", cmd_donate))
    app.add_handler(PreCheckoutQueryHandler(on_precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, on_successful_payment))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_error_handler(on_error)
    return app


def main() -> None:
    db.init_db()
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token or token.startswith("123456"):
        raise SystemExit(
            "Нет токена. BotFather → /newbot, затем:\n"
            "  export TELEGRAM_BOT_TOKEN='...'\n"
            "  python bot.py"
        )
    app = build_application(webhook=False)
    log.info("Загадочник слушает Telegram… %s", _COUNT_LINE)
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
