import io
import re
import time
import zipfile

import openpyxl
import pytest

from sanitization_v2 import auth
from sanitization_v2 import config as cfg
from sanitization_v2 import rules as rules_module
from sanitization_v2.app import app

PASSWORD = "Output-Mode-Testing-Password-123!"


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
    monkeypatch.setattr(cfg, "SEVEN_ZIP_EXE", None)

    cfg.SESSIONS.clear()
    cfg.init_db()
    auth.create_user("analyst", PASSWORD, role="analyst")
    rules_module.reload_bad_patterns()
    app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
    yield
    cfg.SESSIONS.clear()


def login(client):
    page = client.get("/login").get_data(as_text=True)
    token = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
    response = client.post(
        "/login",
        data={"username": "analyst", "password": PASSWORD, "csrf_token": token, "next": "/"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    return client.get("/api/session").get_json()["csrf_token"]


def wait_for_job(client, job_id, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        response = client.get(f"/status/{job_id}")
        assert response.status_code == 200
        data = response.get_json()
        if data["status"] in ("Done", "Failed"):
            return data
        time.sleep(0.05)
    pytest.fail(f"job {job_id} timed out")


def test_one_selected_file_downloads_directly_with_separate_excel_report():
    client = app.test_client()
    csrf = login(client)
    response = client.post(
        "/upload",
        data={
            "file": [(io.BytesIO(b"alpha TESTSECRET omega\n"), "security.log")],
            "relative_path": ["security.log"],
        },
        content_type="multipart/form-data",
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 200
    result = wait_for_job(client, response.get_json()["job_id"])
    assert result["status"] == "Done", result
    assert result["output_type"] == "file"

    sanitized = client.get(result["download"])
    assert sanitized.status_code == 200
    disposition = sanitized.headers.get("Content-Disposition", "")
    assert "security_SANITIZED.log" in disposition
    text = sanitized.get_data(as_text=True)
    assert "TESTSECRET" not in text
    assert "X" in text
    assert not sanitized.data.startswith(b"PK")

    report = client.get(result["report_download"])
    assert report.status_code == 200
    workbook = openpyxl.load_workbook(io.BytesIO(report.data), data_only=True)
    audit_values = [
        str(value or "")
        for row in workbook["Audit"].iter_rows(values_only=True)
        for value in row
    ]
    assert "Keywords" in audit_values
    assert "TESTSECRET" in audit_values


def test_nested_folder_structure_is_preserved_inside_batch_zip():
    client = app.test_client()
    csrf = login(client)
    response = client.post(
        "/upload",
        data={
            "file": [
                (io.BytesIO(b"outer TESTSECRET\n"), "outer.log"),
                (io.BytesIO(b"inner TESTSECRET\n"), "inner.log"),
            ],
            "relative_path": [
                "Case-01/Logs/outer.log",
                "Case-01/Logs/Windows/Security/inner.log",
            ],
        },
        content_type="multipart/form-data",
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 200
    result = wait_for_job(client, response.get_json()["job_id"])
    assert result["status"] == "Done", result
    assert result["output_type"] == "package"

    package_response = client.get(result["download"])
    assert package_response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(package_response.data)) as package:
        names = set(package.namelist())
        assert "Sanitized_Files/Case-01/Logs/outer.log" in names
        assert "Sanitized_Files/Case-01/Logs/Windows/Security/inner.log" in names
        assert "TESTSECRET" not in package.read(
            "Sanitized_Files/Case-01/Logs/Windows/Security/inner.log"
        ).decode("utf-8")


def test_one_file_selected_through_folder_upload_stays_packaged():
    client = app.test_client()
    csrf = login(client)
    response = client.post(
        "/upload",
        data={
            "file": [(io.BytesIO(b"folder TESTSECRET\n"), "only.log")],
            "relative_path": ["Case-02/Subfolder/only.log"],
        },
        content_type="multipart/form-data",
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 200
    result = wait_for_job(client, response.get_json()["job_id"])
    assert result["status"] == "Done", result
    assert result["output_type"] == "package"

    package_response = client.get(result["download"])
    with zipfile.ZipFile(io.BytesIO(package_response.data)) as package:
        assert "Sanitized_Files/Case-02/Subfolder/only.log" in package.namelist()
