"""Dashboard system overview and administrator UI API routes.

These routes extend the core sanitization API without adding third-party
runtime dependencies. They are registered by both main.py and wsgi.py.
"""
from __future__ import annotations

import logging
import os
import platform
import shutil
import socket
from pathlib import Path

from flask import Blueprint, g, jsonify, request

from . import auth
from . import config as cfg

bp = Blueprint("ui_extension", __name__)


def _read_os_release() -> dict[str, str]:
    values: dict[str, str] = {}
    path = Path("/etc/os-release")
    if not path.exists():
        return values
    try:
        for raw in path.read_text("utf-8", errors="replace").splitlines():
            if "=" in raw:
                key, value = raw.split("=", 1)
                values[key] = value.strip().strip('"')
    except OSError:
        return {}
    return values


def _cpu_model() -> str:
    path = Path("/proc/cpuinfo")
    if path.exists():
        try:
            for raw in path.read_text("utf-8", errors="replace").splitlines():
                if raw.lower().startswith("model name") and ":" in raw:
                    model = raw.split(":", 1)[1].strip()
                    if model:
                        return model
        except OSError:
            pass
    return platform.processor() or platform.machine() or "Unknown"


def _memory_info() -> tuple[int, int]:
    total_kb = available_kb = 0
    path = Path("/proc/meminfo")
    if path.exists():
        try:
            for raw in path.read_text("utf-8", errors="replace").splitlines():
                if raw.startswith("MemTotal:"):
                    total_kb = int(raw.split()[1])
                elif raw.startswith("MemAvailable:"):
                    available_kb = int(raw.split()[1])
        except (OSError, ValueError, IndexError):
            pass
    return total_kb * 1024, available_kb * 1024


def _human_bytes(value: int | float) -> str:
    value = float(max(0, value or 0))
    units = ("B", "KB", "MB", "GB", "TB")
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} TB"


def system_overview() -> dict:
    os_release = _read_os_release()
    memory_total, memory_available = _memory_info()
    disk = shutil.disk_usage(cfg.BASE)
    disk_used = max(0, disk.total - disk.free)
    disk_utilization = round((disk_used / disk.total * 100), 1) if disk.total else 0.0
    platform_label = os_release.get("PRETTY_NAME") or (
        f"{os_release.get('NAME', platform.system())} {os_release.get('VERSION_ID', '')}".strip()
    )
    return {
        "host": socket.gethostname(),
        "platform": platform_label,
        "python": platform.python_version(),
        "cpu": _cpu_model(),
        "logical_cpus": os.cpu_count() or 0,
        "memory_total": _human_bytes(memory_total) if memory_total else "Unknown",
        "memory_available": _human_bytes(memory_available) if memory_available else "Unknown",
        "free_disk": _human_bytes(disk.free),
        "disk_total": _human_bytes(disk.total),
        "disk_utilization": disk_utilization,
    }


@bp.route("/system-info")
@auth.login_required
def system_info():
    return jsonify(system_overview())


@bp.route("/admin/users")
@auth.role_required("admin")
def admin_users():
    return jsonify(users=auth.list_users())


@bp.route("/admin/users/create", methods=["POST"])
@auth.role_required("admin")
@auth.csrf_protected
def admin_users_create():
    data = request.get_json(silent=True) or {}
    try:
        user = auth.create_user(
            data.get("username", ""),
            data.get("password", ""),
            role=data.get("role", "analyst"),
        )
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    logging.info(
        "Administrator %s created user %s (%s)",
        g.current_user["username"],
        user["username"],
        user["role"],
    )
    return jsonify(status="User created", user=user), 201


@bp.route("/admin/users/toggle", methods=["POST"])
@auth.role_required("admin")
@auth.csrf_protected
def admin_users_toggle():
    data = request.get_json(silent=True) or {}
    username = data.get("username", "")
    enabled = data.get("enabled")
    if not isinstance(enabled, bool):
        return jsonify(error="enabled must be true or false"), 400
    target = auth.get_user(username)
    if not target:
        return jsonify(error="User not found"), 404
    if target["username"] == g.current_user["username"] and not enabled:
        return jsonify(error="You cannot disable your own active administrator account"), 400
    if target.get("role") == "admin" and target.get("enabled") and not enabled:
        enabled_admins = [
            user
            for user in auth.list_users()
            if user.get("role") == "admin" and user.get("enabled")
        ]
        if len(enabled_admins) <= 1:
            return jsonify(error="The last enabled administrator cannot be disabled"), 400
    try:
        auth.set_enabled(username, enabled)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    logging.info(
        "Administrator %s set user %s enabled=%s",
        g.current_user["username"],
        username,
        enabled,
    )
    return jsonify(status="User status updated", user=auth.get_user(username))


@bp.route("/admin/users/reset-password", methods=["POST"])
@auth.role_required("admin")
@auth.csrf_protected
def admin_users_reset_password():
    data = request.get_json(silent=True) or {}
    username = data.get("username", "")
    password = data.get("password", "")
    try:
        auth.set_password(username, password)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    logging.info(
        "Administrator %s reset password for %s",
        g.current_user["username"],
        username,
    )
    return jsonify(status="Password reset")


@bp.route("/admin/logs")
@auth.role_required("admin")
def admin_logs():
    try:
        limit = max(20, min(int(request.args.get("limit", "200")), 500))
    except ValueError:
        limit = 200
    log_file = cfg.LOGS / "processing.log"
    if not log_file.exists():
        return jsonify(lines=[], source=str(log_file))
    try:
        lines = log_file.read_text("utf-8", errors="replace").splitlines()[-limit:]
    except OSError as exc:
        return jsonify(error=f"Unable to read application log: {exc}"), 500
    return jsonify(lines=lines, source=str(log_file))


def register_ui_extension(app) -> None:
    """Register UI support routes exactly once on the supplied Flask app."""
    if bp.name not in app.blueprints:
        app.register_blueprint(bp)
