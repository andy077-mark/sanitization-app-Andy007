"""Configuration, storage, database, certificate and local 7-Zip helpers."""
from __future__ import annotations

import json
import logging
import os
import platform
import secrets
import shutil
import sqlite3
import uuid
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import Lock, Semaphore

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def _on_pythonanywhere() -> bool:
    return bool(os.environ.get("PYTHONANYWHERE_DOMAIN") or os.environ.get("PYTHONANYWHERE_SITE"))


MAX_UPLOAD_MB = 100 if _on_pythonanywhere() else 2048
MAX_THREADS = 4 if _on_pythonanywhere() else 8
MAX_FILES = 100 if _on_pythonanywhere() else 10000
OUTPUT_RETENTION_DAYS = int(os.environ.get("SANIT_OUTPUT_RETENTION_DAYS", "1"))
HISTORY_RETENTION_DAYS = int(os.environ.get("SANIT_HISTORY_RETENTION_DAYS", "90"))
MAX_EXTRACTED_MB = int(os.environ.get("SANIT_MAX_EXTRACTED_MB", "4096"))
MAX_EXTRACTED_FILES = int(os.environ.get("SANIT_MAX_EXTRACTED_FILES", "10000"))
MAX_ARCHIVE_DEPTH = int(os.environ.get("SANIT_MAX_ARCHIVE_DEPTH", "5"))
ARCHIVE_TIMEOUT_SECONDS = int(os.environ.get("SANIT_ARCHIVE_TIMEOUT_SECONDS", "300"))
AUDIT_EXAMPLE_MAX = 260

ARCHIVE_EXTS = {
    ".zip", ".rar", ".7z", ".tar", ".tgz", ".tar.gz", ".bz2",
    ".tar.bz2", ".tbz2", ".gz", ".xz", ".tar.xz", ".lz", ".zst",
}
COMPOUND_ARCHIVE_SUFFIXES = (".tar.gz", ".tar.bz2", ".tar.xz", ".tbz2", ".tgz")
TEXT_EXTS = {".txt", ".log", ".csv"}
RULES_FILE = "bad_words.txt"

BASE = Path(__file__).resolve().parent.parent
UPLOAD = BASE / "uploads"
OUTPUT = BASE / "outputs"
LOGS = BASE / "logs"
TEMP = BASE / "temp"
DATA = BASE / "data"
TOOLS = BASE / "tools" / "7zip"
for directory in (UPLOAD, OUTPUT, LOGS, TEMP, DATA):
    directory.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA / "jobs.db"
SESSION_SECRET_FILE = DATA / "session_secret.key"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def max_upload_label() -> str:
    if MAX_UPLOAD_MB >= 1024 and MAX_UPLOAD_MB % 1024 == 0:
        return f"{MAX_UPLOAD_MB // 1024} GB"
    return f"{MAX_UPLOAD_MB} MB"


log_handler = RotatingFileHandler(LOGS / "processing.log", maxBytes=5 * 1024 * 1024, backupCount=3)
logging.basicConfig(
    handlers=[log_handler],
    level=logging.INFO,
    format="%(asctime)s %(levelname)s:%(message)s",
)

rules_lock = Lock()
db_lock = Lock()
sem = Semaphore(MAX_THREADS)
SESSIONS: dict[str, dict] = {}
SEVEN_ZIP_EXE: Path | None = None


def get_session_secret() -> str:
    """Return a stable session key suitable for multi-threaded WSGI restarts.

    Production may provide SANIT_SECRET_KEY. Otherwise a 256-bit key is created
    once under data/session_secret.key with owner-only permissions.
    """
    configured = os.environ.get("SANIT_SECRET_KEY", "").strip()
    if configured:
        if len(configured) < 32:
            raise RuntimeError("SANIT_SECRET_KEY must contain at least 32 characters")
        return configured

    SESSION_SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
    if SESSION_SECRET_FILE.exists():
        value = SESSION_SECRET_FILE.read_text("utf-8").strip()
        if len(value) >= 32:
            return value

    value = secrets.token_hex(32)
    try:
        fd = os.open(SESSION_SECRET_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(value + "\n")
    except FileExistsError:
        value = SESSION_SECRET_FILE.read_text("utf-8").strip()
    try:
        SESSION_SECRET_FILE.chmod(0o600)
    except OSError:
        pass
    if len(value) < 32:
        raise RuntimeError("Persistent session secret could not be initialized")
    return value


def db_connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    return con


def _column_names(con: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in con.execute(f"PRAGMA table_info({table})").fetchall()}


def init_db() -> None:
    """Initialize persistent jobs/users and close stale in-progress jobs after restart."""
    with db_lock, db_connect() as con:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT,
                filenames TEXT NOT NULL DEFAULT '[]',
                source_ip TEXT,
                token TEXT NOT NULL,
                total_replacements INTEGER NOT NULL DEFAULT 0,
                duration REAL NOT NULL DEFAULT 0,
                output_path TEXT,
                report_path TEXT,
                error TEXT,
                created_by TEXT NOT NULL DEFAULT ''
            )
            """
        )
        job_columns = _column_names(con, "jobs")
        if "created_by" not in job_columns:
            con.execute("ALTER TABLE jobs ADD COLUMN created_by TEXT NOT NULL DEFAULT ''")

        con.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('analyst','admin')),
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_login TEXT
            )
            """
        )
        con.execute("CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at DESC)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_jobs_created_by ON jobs(created_by)")
        now = now_iso()
        con.execute(
            "UPDATE jobs SET status='Failed', updated_at=?, completed_at=?, "
            "error=COALESCE(error, 'Interrupted by application restart') "
            "WHERE status IN ('Queued','Processing')",
            (now, now),
        )
        con.commit()


def db_create_job(
    job_id: str,
    filenames: list[str],
    ip: str | None,
    token: str,
    created_by: str = "",
) -> None:
    now = now_iso()
    with db_lock, db_connect() as con:
        con.execute(
            """
            INSERT OR REPLACE INTO jobs
            (job_id,status,created_at,updated_at,filenames,source_ip,token,created_by)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (job_id, "Queued", now, now, json.dumps(filenames), ip or "", token, created_by or ""),
        )
        con.commit()


def db_update_job(job_id: str, **fields) -> None:
    allowed = {
        "status", "completed_at", "filenames", "total_replacements", "duration",
        "output_path", "report_path", "error", "source_ip", "token", "created_by",
    }
    clean = {k: v for k, v in fields.items() if k in allowed}
    clean["updated_at"] = now_iso()
    columns = ", ".join(f"{k}=?" for k in clean)
    values = list(clean.values()) + [job_id]
    with db_lock, db_connect() as con:
        con.execute(f"UPDATE jobs SET {columns} WHERE job_id=?", values)
        con.commit()


def db_get_job(job_id: str) -> dict | None:
    with db_lock, db_connect() as con:
        row = con.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
    return dict(row) if row else None


def db_list_jobs(limit: int = 100) -> list[dict]:
    limit = max(1, min(int(limit or 100), 500))
    with db_lock, db_connect() as con:
        rows = con.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def public_job(row: dict | None, include_token_links: bool = True) -> dict | None:
    if not row:
        return None
    try:
        filenames = json.loads(row.get("filenames") or "[]")
    except Exception:
        filenames = []
    out_path = Path(row["output_path"]) if row.get("output_path") else None
    report_path = Path(row["report_path"]) if row.get("report_path") else None
    token = row.get("token") or ""
    result = {
        "job_id": row.get("job_id"),
        "status": row.get("status"),
        "created_at": row.get("created_at"),
        "completed_at": row.get("completed_at"),
        "created_by": row.get("created_by") or "",
        "filenames": filenames,
        "total_replacements": int(row.get("total_replacements") or 0),
        "duration": float(row.get("duration") or 0),
        "error": row.get("error"),
        "download_available": bool(out_path and out_path.exists()),
        "report_available": bool(report_path and report_path.exists()),
    }
    if include_token_links and token:
        if result["download_available"]:
            result["download"] = f"/download/{row['job_id']}?token={token}"
        if result["report_available"]:
            result["report_download"] = f"/download/report/{row['job_id']}?token={token}"
    return result


def purge_storage() -> None:
    file_cutoff = datetime.now() - timedelta(days=OUTPUT_RETENTION_DAYS)
    for folder in (OUTPUT, UPLOAD, TEMP):
        if not folder.exists():
            continue
        for item in folder.iterdir():
            try:
                if datetime.fromtimestamp(item.stat().st_mtime) < file_cutoff:
                    if item.is_dir():
                        shutil.rmtree(item, ignore_errors=True)
                    else:
                        item.unlink(missing_ok=True)
            except OSError:
                pass

    history_cutoff = (datetime.now() - timedelta(days=HISTORY_RETENTION_DAYS)).isoformat(timespec="seconds")
    with db_lock, db_connect() as con:
        con.execute("DELETE FROM jobs WHERE created_at < ?", (history_cutoff,))
        con.commit()

    session_cutoff = datetime.now() - timedelta(days=OUTPUT_RETENTION_DAYS)
    for key in [k for k, v in SESSIONS.items() if v.get("time") and v["time"] < session_cutoff]:
        SESSIONS.pop(key, None)


def ensure_selfsigned_certs() -> None:
    cert_dir = BASE / "certs"
    cert_dir.mkdir(exist_ok=True)
    crt = cert_dir / "cert.pem"
    key = cert_dir / "key.pem"
    if crt.exists() and key.exists():
        return
    logging.info("Generating self-signed development certificate")
    key_obj = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "SanitizationAppDevCert")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key_obj.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.utcnow())
        .not_valid_after(datetime.utcnow() + timedelta(days=3650))
        .sign(key_obj, hashes.SHA256())
    )
    key.write_bytes(
        key_obj.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    crt.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    try:
        key.chmod(0o600)
        crt.chmod(0o644)
    except OSError:
        pass


def _mark_executable(path: Path) -> None:
    try:
        path.chmod(path.stat().st_mode | 0o111)
    except OSError:
        pass


def find_7z() -> Path | None:
    if TOOLS.exists():
        for name in ("7z.exe", "7za.exe", "7zz", "7za", "7z"):
            for candidate in TOOLS.rglob(name):
                if candidate.is_file():
                    if platform.system() != "Windows":
                        _mark_executable(candidate)
                    return candidate
    for name in ("7z", "7za", "7zz"):
        found = shutil.which(name)
        if found:
            return Path(found)
    if platform.system() == "Windows":
        for root in (Path(r"C:\Program Files\7-Zip"), Path(r"C:\Program Files (x86)\7-Zip")):
            exe = root / "7z.exe"
            if exe.exists():
                return exe
    return None


def ensure_7zip(verbose: bool = False) -> Path | None:
    """Find an existing/bundled 7-Zip binary. Never downloads from the internet."""
    global SEVEN_ZIP_EXE
    if SEVEN_ZIP_EXE and Path(SEVEN_ZIP_EXE).exists():
        return Path(SEVEN_ZIP_EXE)
    SEVEN_ZIP_EXE = find_7z()
    if verbose:
        if SEVEN_ZIP_EXE:
            print(f"7-Zip ready: {SEVEN_ZIP_EXE}", flush=True)
        else:
            print(
                "7-Zip not found. ZIP/TAR/GZ/BZ2/XZ still work using Python; "
                "RAR/7Z require a local 7-Zip installation.",
                flush=True,
            )
    return SEVEN_ZIP_EXE


def new_job_token() -> str:
    return uuid.uuid4().hex
