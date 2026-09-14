# -*- coding: utf-8 -*-
"""WSGI entry point (gunicorn / Render)."""

import db
from web import app as application
from web import setup_telegram_webhook

db.init_db()
setup_telegram_webhook()

# gunicorn wsgi:application --bind 0.0.0.0:$PORT --workers 1
app = application
