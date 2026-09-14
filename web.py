# -*- coding: utf-8 -*-
"""Веб-демо логических задач."""

from __future__ import annotations

import hmac
import logging
import os
import secrets
from pathlib import Path

from flask import Flask, abort, jsonify, render_template_string, request, session

import db
from engine import counts, get_riddle, pick_random_riddle

log = logging.getLogger("zagadochnik.web")
_tg_app = None


def _flask_secret() -> str:
    env = os.getenv("FLASK_SECRET", "").strip()
    if env:
        return env
    path = Path(__file__).resolve().parent / "data" / "flask_secret"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        stored = path.read_text(encoding="utf-8").strip()
        if stored:
            return stored
    token = secrets.token_hex(16)
    path.write_text(token, encoding="utf-8")
    return token


app = Flask(__name__)
app.secret_key = _flask_secret()


def setup_telegram_webhook() -> None:
    """Подключить Telegram к тому же gunicorn (Render Web Service)."""
    global _tg_app
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token or token.startswith("123456"):
        log.info("Telegram webhook: нет TELEGRAM_BOT_TOKEN — только веб")
        return
    base = (os.getenv("RENDER_EXTERNAL_URL") or os.getenv("WEBHOOK_URL") or "").rstrip("/")
    if not base:
        log.info("Telegram webhook: нет RENDER_EXTERNAL_URL / WEBHOOK_URL")
        return
    from asgiref.sync import async_to_sync

    from bot import build_application, webhook_secret

    _tg_app = build_application(webhook=True)
    async_to_sync(_tg_app.initialize)()
    async_to_sync(_tg_app.start)()
    url = f"{base}/tg/{webhook_secret(token)}"
    async_to_sync(_tg_app.bot.set_webhook)(url=url, drop_pending_updates=True)
    log.info("Telegram webhook включён: %s/tg/…", base)


@app.post("/tg/<secret>")
def telegram_webhook(secret: str):
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if _tg_app is None or not token:
        abort(404)
    from bot import webhook_secret

    if not hmac.compare_digest(secret, webhook_secret(token)):
        abort(403)
    data = request.get_json(force=True, silent=True)
    if not data:
        abort(400)
    from asgiref.sync import async_to_sync
    from telegram import Update

    update = Update.de_json(data, _tg_app.bot)
    if update:
        async_to_sync(_tg_app.process_update)(update)
    return "ok"


def key() -> str:
    if "sid" not in session:
        session["sid"] = secrets.token_hex(8)
    k = "web:" + session["sid"]
    db.ensure_user(k, "web", "Игрок")
    return k


PAGE = r"""
<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Загадочник — логические задачи</title>
<style>
  :root { --bg:#0c0b10; --card:#16141c; --ink:#f3eadc; --muted:#a89f91; --gold:#d4a657; --gold2:#f0d59a; --line:#2a261f; }
  * { box-sizing: border-box; }
  html, body { margin:0; background:var(--bg); color:var(--ink); font-family: Georgia, serif; }
  body { min-height:100vh; background: radial-gradient(1200px 500px at 10% -10%, #2a2114 0%, transparent 50%), var(--bg); }
  .wrap { max-width:760px; margin:0 auto; padding:28px 18px 80px; }
  header { text-align:center; margin-bottom:24px; }
  .eyebrow { letter-spacing:.28em; text-transform:uppercase; color:var(--gold); font-size:11px; font-family:system-ui,sans-serif; }
  h1 { font-size:42px; margin:8px 0 6px; }
  .sub { color:var(--muted); font-size:17px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:18px; padding:22px; }
  .meta { font-family:system-ui,sans-serif; font-size:12px; color:var(--gold); letter-spacing:.12em; text-transform:uppercase; margin-bottom:10px; }
  .title { font-size:26px; margin:0 0 12px; }
  .body { font-size:18px; line-height:1.55; white-space:pre-wrap; }
  .answer { margin-top:16px; padding:14px 16px; border-left:3px solid var(--gold); background:#1e1b14; border-radius:0 12px 12px 0; display:none; }
  .answer.show { display:block; }
  .src { color:var(--muted); font-size:14px; margin-top:8px; font-style:italic; }
  .row, .levels { display:flex; flex-wrap:wrap; gap:8px; margin-top:16px; }
  button.btn { font-family:system-ui,sans-serif; border:1px solid var(--line); background:#211e28; color:var(--ink); padding:10px 14px; border-radius:999px; cursor:pointer; font-size:14px; }
  button.btn.gold { background:#3a2e16; border-color:#6a5424; color:var(--gold2); }
  button.btn:hover { border-color:var(--gold); }
  .stats { color:var(--muted); font-family:system-ui,sans-serif; font-size:13px; text-align:center; margin-top:22px; }
  .banner { display:none; margin:12px 0 0; padding:10px 12px; border-radius:10px; background:#3a2e16; color:var(--gold2); font-family:system-ui,sans-serif; font-size:14px; }
  .banner.show { display:block; }
  .left { color:var(--muted); font-size:14px; margin-top:12px; font-style:italic; }
  #riddleBox { display:none; margin-top:8px; }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="eyebrow">собранная классика · без генератора</div>
    <h1>Загадочник</h1>
    <p class="sub">Логические задачи: фольклор, Перельман, Кордемский, Смаллиан, кружки. Ответ — отдельной кнопкой.</p>
  </header>
  <div class="card">
    <div class="levels">
      <button class="btn gold" onclick="loadRiddle('easy')">🟢 Лёгкие</button>
      <button class="btn gold" onclick="loadRiddle('medium')">🟡 Средние</button>
      <button class="btn gold" onclick="loadRiddle('hard')">🔴 Сложные</button>
    </div>
    <div id="riddleBox">
      <div class="banner" id="rBanner"></div>
      <h3 class="title" id="rTitle"></h3>
      <div class="body" id="rText"></div>
      <div class="answer" id="rAnswer"></div>
      <div class="row">
        <button class="btn gold" id="rAnsBtn" onclick="showRiddleAnswer()">💡 Ответ</button>
        <button class="btn" onclick="nextRiddle()">🎲 Следующая</button>
      </div>
    </div>
  </div>
  <p class="stats" id="stats"></p>
</div>
<script>
let level = 'easy';
async function loadRiddle(lv) {
  level = lv;
  const r = await (await fetch('/api/riddle?level=' + lv)).json();
  document.getElementById('riddleBox').style.display = 'block';
  document.getElementById('rTitle').textContent = r.title;
  document.getElementById('rText').textContent = r.text;
  const ban = document.getElementById('rBanner');
  if (r.wrapped) {
    ban.textContent = 'Круг пройден — начинаем этот уровень заново.';
    ban.classList.add('show');
  } else {
    ban.textContent = '';
    ban.classList.remove('show');
  }
  const a = document.getElementById('rAnswer');
  a.classList.remove('show'); a.innerHTML = '';
  document.getElementById('rAnsBtn').style.display = 'inline-block';
}
function nextRiddle() { loadRiddle(level); }
async function showRiddleAnswer() {
  const r = await (await fetch('/api/riddle/answer')).json();
  const a = document.getElementById('rAnswer');
  a.innerHTML = r.answer.replace(/</g,'&lt;') + (r.source ? '<div class="src">Источник: ' + r.source.replace(/</g,'&lt;') + '</div>' : '');
  a.classList.add('show');
  document.getElementById('rAnsBtn').style.display = 'none';
  refreshStats();
}
async function refreshStats() {
  const s = await (await fetch('/api/stats')).json();
  document.getElementById('stats').textContent =
    'Показано: ' + s.riddles_shown + ' · открыто ответов: ' + s.riddles_revealed +
    '  ·  в базе лёгких ' + s.counts.easy + ', средних ' + s.counts.medium + ', сложных ' + s.counts.hard;
}
refreshStats();
</script>
</body>
</html>
"""


@app.after_request
def cors(resp):
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.get("/")
def index():
    key()
    return render_template_string(PAGE)


@app.get("/api/stats")
def api_stats():
    u = db.get_user(key())
    u["counts"] = counts()
    return jsonify(u)


@app.get("/api/riddle")
def api_riddle():
    k = key()
    level = request.args.get("level", "easy")
    if level not in ("easy", "medium", "hard"):
        level = "easy"
    sess = db.get_session(k)
    r, wrapped, shown = pick_random_riddle(level, sess["seen_riddles"])
    if not r:
        return jsonify({"error": "empty level"}), 404
    new_shown = shown + [r["id"]]
    db.save_session(
        k, mode="riddle", difficulty=level, riddle_id=r["id"], danetka_id=None, answer_shown=0
    )
    db.set_level_seen(k, level, new_shown)
    db.bump(k, "riddles_shown")
    return jsonify(
        {
            "id": r["id"],
            "title": r["title"],
            "text": r["text"],
            "wrapped": wrapped,
        }
    )


@app.get("/api/riddle/answer")
def api_riddle_answer():
    k = key()
    sess = db.get_session(k)
    r = get_riddle(sess.get("riddle_id") or -1)
    if not r:
        return jsonify({"error": "no riddle"}), 400
    if not sess.get("answer_shown"):
        db.bump(k, "riddles_revealed")
        db.save_session(k, answer_shown=1)
    return jsonify({"answer": r["answer"], "source": r.get("source") or ""})


if __name__ == "__main__":
    db.init_db()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")), debug=False)
