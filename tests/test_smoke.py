import io
import time
import zipfile

import openpyxl
import pytest

from sanitization_v2 import config as cfg
from sanitization_v2 import rules as rules_module
from sanitization_v2.app import app


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
    rules_module.reload_bad_patterns()
    app.config.update(TESTING=True)
    yield
    cfg.SESSIONS.clear()


def wait_for_job(client, job_id, timeout=15):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        response = client.get(f"/status/{job_id}")
        assert response.status_code == 200
        last = response.get_json()
        if last["status"] in ("Done", "Failed"):
            return last
        time.sleep(0.05)
    pytest.fail(f"job {job_id} did not finish; last status={last}")


def test_ui_health_and_button_contract():
    client = app.test_client()
    response = client.get("/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    for required in (
        'data-v="dashboard"',
        'data-v="sanitize"',
        'data-v="history"',
        'data-v="rules"',
        'id="browseBtn"',
        'id="folderBtn"',
        'id="clearBtn"',
        'id="startBtn"',
        'id="exportBtn"',
        'id="addRuleBtn"',
        'id="saveRulesBtn"',
        'id="clearRulesBtn"',
        'id="replaceRulesBtn"',
    ):
        assert required in html

    health = client.get("/health")
    assert health.status_code == 200
    data = health.get_json()
    assert data["status"] == "ok"
    assert data["version"] == "2.0"
    assert data["offline"] is True


def test_rule_management_endpoints():
    client = app.test_client()

    response = client.post("/rules/save", json={"lines": ["TESTSECRET"]})
    assert response.status_code == 200

    response = client.post("/rules/add", json={"rule": "NEWSECRET"})
    assert response.status_code == 200
    assert response.get_json()["count"] == 2

    response = client.post("/rules/edit", json={"index": 1, "line": "CHANGEDSECRET"})
    assert response.status_code == 200

    lines = client.get("/bad_words").get_json()["lines"]
    assert lines == ["TESTSECRET", "CHANGEDSECRET"]

    response = client.post("/rules/remove", json={"index": 1})
    assert response.status_code == 200
    assert client.get("/bad_words").get_json()["lines"] == ["TESTSECRET"]

    response = client.post("/rules/add", json={"rule": "["})
    assert response.status_code == 400
    assert "invalid regex" in response.get_json()["error"]


def test_multifile_folder_package_report_and_history():
    client = app.test_client()
    payload = {
        "file": [
            (io.BytesIO(b"alpha TESTSECRET omega\n"), "one.txt"),
            (io.BytesIO(b"second TESTSECRET value\n"), "two.log"),
        ],
        "relative_path": ["Case-A/one.txt", "Case-A/sub/two.log"],
    }
    response = client.post("/upload", data=payload, content_type="multipart/form-data")
    assert response.status_code == 200
    job_id = response.get_json()["job_id"]

    result = wait_for_job(client, job_id)
    assert result["status"] == "Done", result
    assert result["total_replacements"] >= 2
    assert result["download"]
    assert result["report_download"]

    package_response = client.get(result["download"])
    assert package_response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(package_response.data)) as package:
        names = package.namelist()
        assert "Sanitized_Files/Case-A/one.txt" in names
        assert "Sanitized_Files/Case-A/sub/two.log" in names
        assert any(name.endswith(f"Sanitization_Report_{job_id}.xlsx") for name in names)
        one = package.read("Sanitized_Files/Case-A/one.txt").decode("utf-8")
        two = package.read("Sanitized_Files/Case-A/sub/two.log").decode("utf-8")
        assert "TESTSECRET" not in one
        assert "TESTSECRET" not in two
        assert "X" in one and "X" in two

    report_response = client.get(result["report_download"])
    assert report_response.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(report_response.data), data_only=True)
    assert {"Summary", "Audit"}.issubset(wb.sheetnames)
    report_text = "\n".join(
        str(value or "")
        for sheet in wb.worksheets
        for row in sheet.iter_rows(values_only=True)
        for value in row
    )
    assert "TESTSECRET" not in report_text
    assert "Total Replacements" in report_text

    jobs = client.get("/jobs?limit=20").get_json()["jobs"]
    found = next(item for item in jobs if item["job_id"] == job_id)
    assert found["status"] == "Done"
    assert found["download_available"] is True
    assert found["report_available"] is True


def test_archive_path_traversal_becomes_failed_job():
    client = app.test_client()
    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(archive_bytes, "w") as zf:
        zf.writestr("../escape.txt", "TESTSECRET")
    archive_bytes.seek(0)

    response = client.post(
        "/upload",
        data={
            "file": [(archive_bytes, "unsafe.zip")],
            "relative_path": ["unsafe.zip"],
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    job_id = response.get_json()["job_id"]
    result = wait_for_job(client, job_id)
    assert result["status"] == "Failed"
    assert "Unsafe archive member path" in result["error"]

    jobs = client.get("/jobs?limit=20").get_json()["jobs"]
    found = next(item for item in jobs if item["job_id"] == job_id)
    assert found["status"] == "Failed"
    assert found["error"]
