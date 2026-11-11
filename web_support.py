"""Configuración externa y CSRF para las nuevas escrituras web."""
import os
import secrets
import hmac

from flask import current_app, session, request
from database import DEFAULT_PATH


def configure_web(app):
    app.config.update(
        SECRET_KEY=os.environ.get('SECRET_KEY'),
        DATABASE=os.environ.get('JOURNAL_DATABASE', str(DEFAULT_PATH)),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_SECURE=os.environ.get('SESSION_COOKIE_SECURE', '').lower() in ('1', 'true'),
    )


def csrf_token():
    if not current_app.secret_key:
        raise RuntimeError('SECRET_KEY requerida.')
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_urlsafe(32)
    return session['csrf_token']


def valid_csrf():
    supplied = request.headers.get('X-CSRF-Token') or request.form.get('csrf_token', '')
    expected = session.get('csrf_token')
    return isinstance(expected, str) and isinstance(supplied, str) and hmac.compare_digest(expected.encode(), supplied.encode())
