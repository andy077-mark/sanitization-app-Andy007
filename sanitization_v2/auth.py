"""Local authentication, RBAC, CSRF and user-management helpers."""
from __future__ import annotations

import secrets
from functools import wraps

from flask import g, jsonify, request, session
from werkzeug.security import check_password_hash, generate_password_hash

from . import config as cfg

VALID_ROLES = {"analyst", "admin"}
MIN_PASSWORD_LENGTH = 12


def normalize_username(username: str) -> str:
    value = (username or "").strip().lower()
    if not value or len(value) > 64:
        raise ValueError("Username must be between 1 and 64 characters")
    if not all(ch.isalnum() or ch in "._-@" for ch in value):
        raise ValueError("Username contains unsupported characters")
    return value


def validate_password(password: str) -> None:
    if len(password or "") < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")


def create_user(username: str, password: str, role: str = "analyst", enabled: bool = True, replace: bool = False) -> dict:
    username = normalize_username(username)
    role = (role or "").strip().lower()
    if role not in VALID_ROLES:
        raise ValueError("Role must be analyst or admin")
    validate_password(password)
    now = cfg.now_iso()
    password_hash = generate_password_hash(password, method="scrypt")
    with cfg.db_lock, cfg.db_connect() as con:
        existing = con.execute("SELECT username FROM users WHERE username=?", (username,)).fetchone()
        if existing and not replace:
            raise ValueError("User already exists")
        if existing:
            con.execute(
                "UPDATE users SET password_hash=?, role=?, enabled=?, updated_at=? WHERE username=?",
                (password_hash, role, 1 if enabled else 0, now, username),
            )
        else:
            con.execute(
                "INSERT INTO users (username,password_hash,role,enabled,created_at,updated_at) VALUES (?,?,?,?,?,?)",
                (username, password_hash, role, 1 if enabled else 0, now, now),
            )
        con.commit()
    return get_user(username) or {}


def get_user(username: str) -> dict | None:
    try:
        username = normalize_username(username)
    except ValueError:
        return None
    with cfg.db_lock, cfg.db_connect() as con:
        row = con.execute(
            "SELECT username,role,enabled,created_at,updated_at,last_login FROM users WHERE username=?",
            (username,),
        ).fetchone()
    return dict(row) if row else None


def list_users() -> list[dict]:
    with cfg.db_lock, cfg.db_connect() as con:
        rows = con.execute(
            "SELECT username,role,enabled,created_at,updated_at,last_login FROM users ORDER BY username"
        ).fetchall()
    return [dict(row) for row in rows]


def has_admin_user() -> bool:
    with cfg.db_lock, cfg.db_connect() as con:
        row = con.execute("SELECT 1 FROM users WHERE role='admin' AND enabled=1 LIMIT 1").fetchone()
    return bool(row)


def set_password(username: str, password: str) -> None:
    username = normalize_username(username)
    validate_password(password)
    password_hash = generate_password_hash(password, method="scrypt")
    with cfg.db_lock, cfg.db_connect() as con:
        cur = con.execute(
            "UPDATE users SET password_hash=?, updated_at=? WHERE username=?",
            (password_hash, cfg.now_iso(), username),
        )
        con.commit()
    if cur.rowcount != 1:
        raise ValueError("User not found")


def set_enabled(username: str, enabled: bool) -> None:
    username = normalize_username(username)
    with cfg.db_lock, cfg.db_connect() as con:
        cur = con.execute(
            "UPDATE users SET enabled=?, updated_at=? WHERE username=?",
            (1 if enabled else 0, cfg.now_iso(), username),
        )
        con.commit()
    if cur.rowcount != 1:
        raise ValueError("User not found")


def authenticate(username: str, password: str) -> dict | None:
    try:
        username = normalize_username(username)
    except ValueError:
        return None
    with cfg.db_lock, cfg.db_connect() as con:
        row = con.execute(
            "SELECT username,password_hash,role,enabled,created_at,updated_at,last_login FROM users WHERE username=?",
            (username,),
        ).fetchone()
        if not row or not row["enabled"] or not check_password_hash(row["password_hash"], password or ""):
            return None
        now = cfg.now_iso()
        con.execute("UPDATE users SET last_login=?, updated_at=? WHERE username=?", (now, now, username))
        con.commit()
    return {
        "username": row["username"],
        "role": row["role"],
        "enabled": bool(row["enabled"]),
        "last_login": now,
    }


def current_user() -> dict | None:
    username = session.get("username")
    if not username:
        return None
    user = get_user(username)
    if not user or not user.get("enabled"):
        session.clear()
        return None
    session["role"] = user["role"]
    return user


def establish_session(user: dict) -> None:
    session.clear()
    session.permanent = True
    session["username"] = user["username"]
    session["role"] = user["role"]
    session["csrf_token"] = secrets.token_urlsafe(32)


def ensure_csrf_token() -> str:
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def csrf_is_valid() -> bool:
    expected = session.get("csrf_token") or ""
    supplied = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token") or ""
    return bool(expected and supplied and secrets.compare_digest(expected, supplied))


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user:
            return jsonify(error="Authentication required"), 401
        g.current_user = user
        return view(*args, **kwargs)
    return wrapped


def role_required(role: str):
    if role not in VALID_ROLES:
        raise ValueError("Invalid role")

    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = current_user()
            if not user:
                return jsonify(error="Authentication required"), 401
            if user.get("role") != role:
                return jsonify(error="Administrator access required"), 403
            g.current_user = user
            return view(*args, **kwargs)
        return wrapped
    return decorator


def csrf_protected(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not csrf_is_valid():
            return jsonify(error="Invalid or missing CSRF token"), 403
        return view(*args, **kwargs)
    return wrapped
