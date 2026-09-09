import re

import pytest

from sanitization_v2 import auth
from sanitization_v2 import config as cfg
from sanitization_v2 import rules as rules_module
from sanitization_v2.app import app
from sanitization_v2.ui_extension import register_ui_extension

register_ui_extension(app)

ADMIN_PASSWORD = "Admin-Dashboard-Test-123!"
ANALYST_PASSWORD = "Analyst-Dashboard-Test-123!"


@pytest.fixture(autouse=True)
def isolated_runtime(tmp_path, monkeypatch):
    paths = {
        "UPLOAD": tmp_path / "uploads",
        "OUTPUT": tmp_path / "outputs",
        "LOGS": tmp_path / "logs",
        "TEMP": tmp_path / "temp",
        "DATA": tmp_path / "data",
    }
    for name, path in paths.items():
        path.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(cfg, name, path)
    monkeypatch.setattr(cfg, "DB_PATH", paths["DATA"] / "jobs.db")
    rules_file = tmp_path / "bad_words.txt"
    rules_file.write_text("TESTSECRET\n", encoding="utf-8")
    monkeypatch.setattr(cfg, "RULES_FILE", str(rules_file))
    cfg.SESSIONS.clear()
    cfg.init_db()
    auth.create_user("admin", ADMIN_PASSWORD, role="admin")
    auth.create_user("analyst", ANALYST_PASSWORD, role="analyst")
    rules_module.reload_bad_patterns()
    app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
    yield
    cfg.SESSIONS.clear()


def login(client, username="admin", password=ADMIN_PASSWORD):
    page = client.get("/login").get_data(as_text=True)
    token = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
    response = client.post(
        "/login",
        data={"username": username, "password": password, "csrf_token": token, "next": "/"},
    )
    assert response.status_code == 302
    return client.get("/api/session").get_json()["csrf_token"]


def test_visual_flow_system_overview_and_admin_controls_are_wired():
    client = app.test_client()
    csrf = login(client)

    html = client.get("/").get_data(as_text=True)
    for expected in (
        'data-view="dashboard"',
        'data-view="sanitize"',
        'data-view="history"',
        'data-view="rules"',
        'data-view="users"',
        'data-view="logs"',
        'data-view="about"',
        'id="browse"',
        'id="browseFolder"',
        'id="clear"',
        'id="start"',
        'id="refreshJobs"',
        'id="exportJobs"',
        'id="healthBtn"',
        'id="createUser"',
        'id="refreshUsers"',
        'id="refreshLogs"',
        'id="sysHost"',
        'id="sysPlatform"',
        'id="sysPython"',
        'id="sysCpu"',
        'id="sysCpus"',
        'id="sysMemory"',
        'id="sysDisk"',
        'id="sysUtil"',
    ):
        assert expected in html

    health = client.get("/health")
    assert health.status_code == 200
    system_response = client.get("/system-info")
    assert system_response.status_code == 200
    system = system_response.get_json()
    assert {
        "host",
        "platform",
        "python",
        "cpu",
        "logical_cpus",
        "memory_total",
        "memory_available",
        "free_disk",
        "disk_total",
        "disk_utilization",
    }.issubset(system)

    users = client.get("/admin/users")
    assert users.status_code == 200
    assert {u["username"] for u in users.get_json()["users"]} == {"admin", "analyst"}

    created = client.post(
        "/admin/users/create",
        json={"username": "newanalyst", "password": "New-Analyst-Password-123!", "role": "analyst"},
        headers={"X-CSRF-Token": csrf},
    )
    assert created.status_code == 201

    disabled = client.post(
        "/admin/users/toggle",
        json={"username": "newanalyst", "enabled": False},
        headers={"X-CSRF-Token": csrf},
    )
    assert disabled.status_code == 200
    assert disabled.get_json()["user"]["enabled"] == 0

    reset = client.post(
        "/admin/users/reset-password",
        json={"username": "newanalyst", "password": "Replacement-Password-123!"},
        headers={"X-CSRF-Token": csrf},
    )
    assert reset.status_code == 200

    log_file = cfg.LOGS / "processing.log"
    log_file.write_text("2026-09-09 INFO UI test entry\n", encoding="utf-8")
    logs = client.get("/admin/logs?limit=20")
    assert logs.status_code == 200
    assert "UI test entry" in "\n".join(logs.get_json()["lines"])

    analyst = app.test_client()
    login(analyst, "analyst", ANALYST_PASSWORD)
    analyst_html = analyst.get("/").get_data(as_text=True)
    assert 'data-view="users"' not in analyst_html
    assert 'data-view="logs"' not in analyst_html
    assert analyst.get("/admin/users").status_code == 403
    assert analyst.get("/admin/logs").status_code == 403
