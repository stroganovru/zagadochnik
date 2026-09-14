# -*- coding: utf-8 -*-
"""WSGI entry point (gunicorn / Render)."""

import logging

import db
from web import app as application
from web import setup_telegram_webhook

db.init_db()
# webhook после импорта: gunicorn успеет открыть порт
try:
    setup_telegram_webhook()
except Exception:
    logging.getLogger("zagadochnik.web").exception("webhook setup")

# gunicorn wsgi:application --bind 0.0.0.0:$PORT --workers 1
app = application
