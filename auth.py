"""
auth.py — Thunder FC
Authentication helpers: rate limiting, session management.
CSRF is handled globally by Flask-WTF via app.config['WTF_CSRF_ENABLED'].
"""

from datetime import datetime, timedelta
from functools import wraps
from flask import session, redirect, url_for, flash, request, current_app
from db import get_db


# ── Role-based access decorators ─────────────────────────────────────────────

def login_required(role=None):
    """
    Flexible decorator — works in two ways:

        @login_required          — just checks login, any role
        @login_required()        — same, no role check
        @login_required('admin') — checks login + specific role
    """
    # Called WITHOUT parentheses: @login_required → role is the function itself
    if callable(role):
        f = role
        return _make_wrapper(f, required_role=None)
    # Called WITH parentheses: @login_required() or @login_required('admin')
    def decorator(f):
        return _make_wrapper(f, required_role=role)
    return decorator


def _make_wrapper(f, required_role):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if 'username' not in session:
            flash('Please log in to continue.', 'warning')
            return redirect(url_for('login'))
        if required_role and session.get('role') != required_role:
            current_app.logger.warning(
                'Access denied: user=%s role=%s required=%s path=%s',
                session.get('username'), session.get('role'),
                required_role, request.path
            )
            flash('Access denied.', 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return wrapper


def admin_required(f):
    return _make_wrapper(f, required_role='admin')


def coach_required(f):
    return _make_wrapper(f, required_role='coach')


def player_required(f):
    return _make_wrapper(f, required_role='player')


# ── Rate limiting (DB-backed, no Redis required) ──────────────────────────────

def _recent_failures(username, ip, window_minutes):
    """Count failed login attempts for username OR ip in the last window_minutes."""
    cutoff = (datetime.utcnow() - timedelta(minutes=window_minutes)).strftime('%Y-%m-%d %H:%M:%S')
    db = get_db()
    row = db.execute(
        """SELECT COUNT(*) FROM login_attempts
           WHERE (username=? OR ip_address=?) AND success=0 AND attempted_at > ?""",
        (username, ip, cutoff)
    ).fetchone()
    return row[0]


def is_rate_limited(username, ip):
    """Return True if this username/ip has too many recent failures."""
    cfg = current_app.config
    failures = _recent_failures(
        username, ip, cfg['LOGIN_LOCKOUT_MINUTES']
    )
    return failures >= cfg['LOGIN_MAX_ATTEMPTS']


def record_attempt(username, ip, success):
    """Log a login attempt to the DB."""
    db = get_db()
    db.execute(
        "INSERT INTO login_attempts (username, ip_address, success) VALUES (?,?,?)",
        (username, ip, 1 if success else 0)
    )
    db.commit()


def get_client_ip():
    """Get real client IP, respecting X-Forwarded-For if behind a proxy."""
    if request.headers.get('X-Forwarded-For'):
        return request.headers['X-Forwarded-For'].split(',')[0].strip()
    return request.remote_addr or '0.0.0.0'