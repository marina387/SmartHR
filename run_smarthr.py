"""Локальный запуск SmartHR, проверка окружения и резервная копия SQLite."""
import argparse
import importlib.metadata
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
from datetime import datetime

ROOT = Path(__file__).resolve().parent


def backup_database(path):
    if not path.exists():
        return None
    folder = ROOT / "data" / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / ("smarthr_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".db")
    with sqlite3.connect(path) as source, sqlite3.connect(target) as destination:
        source.backup(destination)
    return target


def main():
    parser = argparse.ArgumentParser(description="Start SmartHR locally")
    parser.add_argument("--check", action="store_true", help="Check runtime without starting or changing data")
    parser.add_argument("--backup-only", action="store_true")
    args = parser.parse_args()
    os.chdir(ROOT)
    database = Path(os.getenv("SMARTHR_DATABASE", str(ROOT / "data" / "smarthr.db")))
    if args.backup_only:
        print(backup_database(database) or "Database does not exist yet")
        return 0
    required = ["flask", "Flask-SQLAlchemy", "Flask-Migrate", "scikit-learn", "python-docx", "PyPDF2", "rapidfuzz"]
    if (ROOT / "models" / "chat_model_real" / "smarthr_model_metadata.json").exists():
        required += ["torch", "transformers", "peft", "accelerate"]
    missing = []
    for package in required:
        try:
            importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            missing.append(package)
    if missing:
        print("Missing dependencies: " + ", ".join(missing))
        print("Run: python -m pip install -r requirements.txt -r requirements-chat.txt")
        return 1
    if args.check:
        print("Runtime OK: " + sys.executable)
        return 0
    host = os.getenv("FLASK_HOST", "127.0.0.1")
    port = int(os.getenv("FLASK_PORT", "5000"))
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", port)) == 0:
            print(f"Port {port} is already in use. Open http://localhost:{port} if SmartHR is running.")
            return 0
    backup = backup_database(database)
    if backup:
        print("Database backup: " + str(backup), flush=True)
    subprocess.run([sys.executable, "-m", "flask", "--app", "app", "db", "upgrade"], check=True)
    print(f"Open http://localhost:{port} . Press Ctrl+C to stop.", flush=True)
    return subprocess.call([sys.executable, "app.py"])


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, subprocess.CalledProcessError) as exc:
        print("SmartHR could not start: " + str(exc), file=sys.stderr)
        raise SystemExit(1)
