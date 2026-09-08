"""Flask API/UI routes and CLI entry point for Sanitization Platform v2."""
from __future__ import annotations

import argparse
import io
import os
import shutil
import sys
import uuid
from datetime import datetime
from pathlib import Path
from threading import Thread

from flask import Flask, jsonify, render_template_string, request, send_file, send_from_directory

from . import config as cfg
from .jobs import process_file
from .rules import (
    parse_active_patterns,
    read_rules_file,
    validate_patterns,
    validate_patterns_in_lines,
    write_rules_file,
)
from .sanitize import sanitize_filename_windows


app = Flask(__name__)
app.secret_key = os.environ.get("SANIT_SECRET_KEY") or uuid.uuid4().hex
app.config["MAX_CONTENT_LENGTH"] = cfg.MAX_UPLOAD_MB * 1024 * 1024
cfg.init_db()


@app.errorhandler(413)
def handle_413(_):
    return jsonify(error=f"Upload request too large (max {cfg.max_upload_label()})"), 413


@app.route("/")
def index():
    html = (cfg.BASE / "templates" / "index.html").read_text("utf-8")
    return render_template_string(
        html,
        max_mb=cfg.MAX_UPLOAD_MB,
        max_files=cfg.MAX_FILES,
        max_label=cfg.max_upload_label(),
        year=datetime.now().year,
    )


@app.route("/health")
def health():
    return jsonify(
        status="ok",
        version="2.0",
        offline=True,
        seven_zip=bool(cfg.ensure_7zip(False)),
        max_upload=cfg.max_upload_label(),
        max_files=cfg.MAX_FILES,
    )


@app.route("/logo.png", strict_slashes=False)
def logo():
    logo_path = cfg.BASE / "templates" / "logo.png"
    if logo_path.exists():
        return send_file(logo_path, mimetype="image/png")
    svg = (
        b'<svg xmlns="http://www.w3.org/2000/svg" width="60" height="60" viewBox="0 0 60 60">'
        b'<rect width="60" height="60" rx="12" fill="#0b2633"/>'
        b'<path d="M30 10 46 18v12c0 10-6 17-16 21C20 47 14 40 14 30V18z" fill="none" stroke="#20e2bf" stroke-width="3"/>'
        b'<text x="30" y="35" font-family="Arial,sans-serif" font-size="13" fill="#20e2bf" text-anchor="middle" font-weight="bold">SOC</text></svg>'
    )
    return send_file(io.BytesIO(svg), mimetype="image/svg+xml")


@app.route("/upload", methods=["POST"])
def upload():
    cfg.purge_storage()
    files = request.files.getlist("file")
    if not files or len(files) > cfg.MAX_FILES:
        return jsonify(error=f"Select 1-{cfg.MAX_FILES} files"), 400

    relative_paths = request.form.getlist("relative_path")
    if len(relative_paths) != len(files):
        relative_paths = [f.filename or f"file_{i + 1}" for i, f in enumerate(files)]

    job_id = uuid.uuid4().hex[:8]
    token = cfg.new_job_token()
    original_names: list[str] = []
    upaths: list[Path] = []

    try:
        for idx, uploaded in enumerate(files):
            original = Path(uploaded.filename or f"file_{idx + 1}").name
            safe_base, _ = sanitize_filename_windows(original)
            storage = cfg.UPLOAD / f"{job_id}_{idx:05d}_{safe_base}"
            uploaded.save(storage)
            upaths.append(storage)
            original_names.append(original)
    except Exception:
        for path in upaths:
            Path(path).unlink(missing_ok=True)
        raise

    cfg.SESSIONS[job_id] = {
        "status": "Queued",
        "progress": 0,
        "token": token,
        "time": datetime.now(),
        "filenames": relative_paths,
    }
    cfg.db_create_job(job_id, relative_paths, request.remote_addr, token)

    Thread(
        target=process_file,
        args=(job_id, upaths, original_names, relative_paths, request.remote_addr, None),
        daemon=True,
    ).start()
    return jsonify(job_id=job_id, files=len(files))


def _status_payload(job_id: str, info: dict) -> dict:
    payload = {
        "job_id": job_id,
        "status": info.get("status", "Unknown"),
        "progress": info.get("progress"),
        "current_file": info.get("current_file"),
    }
    if payload["status"] == "Done":
        payload.update(
            {
                "download": info.get("download"),
                "report_download": info.get("report_download"),
                "file_stats": info.get("file_stats", []),
                "duration": info.get("duration", 0),
                "total_replacements": info.get("total_replacements", 0),
            }
        )
    elif payload["status"] == "Failed":
        payload.update(
            {
                "error": info.get("error") or "Processing failed",
                "duration": info.get("duration", 0),
            }
        )
    return payload


@app.route("/status/<job_id>")
def status(job_id: str):
    info = cfg.SESSIONS.get(job_id)
    if info:
        return jsonify(_status_payload(job_id, info))

    row = cfg.db_get_job(job_id)
    if not row:
        return jsonify(error="Invalid Job ID"), 404
    public = cfg.public_job(row, include_token_links=True)
    return jsonify(
        {
            "job_id": job_id,
            "status": public["status"],
            "progress": 100 if public["status"] in ("Done", "Failed") else None,
            "download": public.get("download"),
            "report_download": public.get("report_download"),
            "duration": public.get("duration", 0),
            "total_replacements": public.get("total_replacements", 0),
            "error": public.get("error"),
            "file_stats": [],
        }
    )


@app.route("/jobs")
def jobs():
    cfg.purge_storage()
    try:
        limit = int(request.args.get("limit", "100"))
    except ValueError:
        limit = 100
    return jsonify(jobs=[cfg.public_job(row, include_token_links=True) for row in cfg.db_list_jobs(limit)])


def _authorized_job(job_id: str):
    token = request.args.get("token", "")
    row = cfg.db_get_job(job_id)
    if not row or not token or row.get("token") != token or row.get("status") != "Done":
        return None
    return row


@app.route("/download/<job_id>")
def download(job_id: str):
    row = _authorized_job(job_id)
    if not row:
        return "Forbidden", 403
    out = Path(row.get("output_path") or "")
    if not out.exists():
        return "Not Found", 404
    return send_from_directory(
        out.parent,
        out.name,
        as_attachment=True,
        download_name=f"Sanitized_Package_{job_id}.zip",
    )


@app.route("/download/report/<job_id>")
def download_report(job_id: str):
    row = _authorized_job(job_id)
    if not row:
        return "Forbidden", 403
    report = Path(row.get("report_path") or "")
    if not report.exists():
        return "Not Found", 404
    return send_from_directory(
        report.parent,
        report.name,
        as_attachment=True,
        download_name=f"Sanitization_Report_{job_id}.xlsx",
    )


@app.route("/bad_words")
def bad_words():
    return jsonify(lines=read_rules_file())


@app.route("/rules/save", methods=["POST"])
def rules_save():
    data = request.get_json(silent=True) or {}
    lines = data.get("lines")
    if not isinstance(lines, list):
        return jsonify(error="lines must be a list"), 400
    ok, err = validate_patterns_in_lines(lines)
    if not ok:
        return jsonify(error=err), 400
    write_rules_file(lines)
    return jsonify(status="Rules saved", count=len(parse_active_patterns(lines)))


@app.route("/rules/add", methods=["POST"])
def rules_add():
    data = request.get_json(silent=True) or {}
    rule = (data.get("rule") or "").strip()
    if not rule:
        return jsonify(error="Rule cannot be empty"), 400
    ok, err = validate_patterns([rule])
    if not ok:
        return jsonify(error=err), 400
    lines = read_rules_file()
    lines.append(rule)
    write_rules_file(lines)
    return jsonify(status="Rule added", count=len(parse_active_patterns(lines)))


@app.route("/rules/remove", methods=["POST"])
def rules_remove():
    data = request.get_json(silent=True) or {}
    index = data.get("index")
    if not isinstance(index, int):
        return jsonify(error="Missing or invalid index"), 400
    lines = read_rules_file()
    if index < 0 or index >= len(lines):
        return jsonify(error="Index out of range"), 400
    removed = lines.pop(index)
    write_rules_file(lines)
    return jsonify(status="Rule removed", removed=removed)


@app.route("/rules/edit", methods=["POST"])
def rules_edit():
    data = request.get_json(silent=True) or {}
    index = data.get("index")
    line = data.get("line")
    if not isinstance(index, int) or line is None:
        return jsonify(error="Missing or invalid index/line"), 400
    lines = read_rules_file()
    if index < 0 or index >= len(lines):
        return jsonify(error="Index out of range"), 400
    ok, err = validate_patterns_in_lines([line])
    if not ok:
        return jsonify(error=err.replace("Line 1:", f"Line {index + 1}:")), 400
    lines[index] = line
    write_rules_file(lines)
    return jsonify(status="Line updated", count=len(parse_active_patterns(lines)))


@app.route("/rules/clear", methods=["POST"])
def rules_clear():
    write_rules_file([])
    return jsonify(status="All rules cleared")


@app.route("/rules/upload", methods=["POST"])
def rules_upload():
    uploaded = request.files.get("file")
    if not uploaded or not uploaded.filename:
        return jsonify(error="No file uploaded"), 400
    try:
        content = uploaded.read().decode("utf-8")
    except UnicodeDecodeError:
        return jsonify(error="File must be UTF-8 text"), 400
    lines = content.splitlines()
    ok, err = validate_patterns_in_lines(lines)
    if not ok:
        return jsonify(error=err), 400
    write_rules_file(lines)
    return jsonify(status="Rules file uploaded and replaced", count=len(parse_active_patterns(lines)))


def run_cli(path: str, rules: list[str] | None = None) -> int:
    cfg.purge_storage()
    source = Path(path)
    if not source.is_file():
        print("Error: file not found", file=sys.stderr)
        return 1
    job_id = uuid.uuid4().hex[:8]
    token = cfg.new_job_token()
    safe, _ = sanitize_filename_windows(source.name)
    up = cfg.UPLOAD / f"{job_id}_00000_{safe}"
    shutil.copy2(source, up)
    cfg.SESSIONS[job_id] = {
        "status": "Queued",
        "progress": 0,
        "token": token,
        "time": datetime.now(),
    }
    cfg.db_create_job(job_id, [source.name], "CLI", token)
    process_file(job_id, [up], [source.name], [source.name], "CLI", rules)
    info = cfg.SESSIONS[job_id]
    print("Job ID:", job_id)
    print("Status:", info.get("status"))
    if info.get("status") == "Done":
        print(f"Duration: {info.get('duration', 0):.2f}s")
        print("Total Replacements:", info.get("total_replacements", 0))
        print("Output package:", info.get("output_path", ""))
        print("Audit report:", info.get("report_path", ""))
        return 0
    print("Error:", info.get("error", "Unknown error"), file=sys.stderr)
    return 2


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve", action="store_true", help="Run HTTPS server")
    parser.add_argument("file", nargs="?", help="CLI input file")
    parser.add_argument("--rules", nargs="*", help="Inline regex rules")
    parser.add_argument("--rules-file", help="Load regex rules from file")
    args = parser.parse_args()

    cfg.ensure_selfsigned_certs()
    cfg.ensure_7zip(verbose=args.serve)

    if args.serve:
        print("Starting SOC Data Sanitization Platform v2.0", flush=True)
        print("Open https://localhost:8443 in your browser (accept the local certificate warning).", flush=True)
        app.run(
            host="0.0.0.0",
            port=8443,
            ssl_context=(str(cfg.BASE / "certs" / "cert.pem"), str(cfg.BASE / "certs" / "key.pem")),
            threaded=True,
            debug=False,
        )
    elif args.file:
        active_rules = None
        if args.rules_file:
            active_rules = parse_active_patterns(Path(args.rules_file).read_text("utf-8").splitlines())
        elif args.rules:
            active_rules = args.rules
        raise SystemExit(run_cli(args.file, active_rules))
    else:
        parser.print_help()
