# -*- coding: utf-8 -*-
"""WSGI entry point (gunicorn / Render)."""

import db
from web import app as application

db.init_db()

# gunicorn wsgi:application
# gunicorn wsgi:app
app = application
