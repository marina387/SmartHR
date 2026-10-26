"""Локальный запуск SmartHR, проверка окружения и резервная копия SQLite."""
import argparse
import importlib.metadata
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import json
from datetime import datetime
from src.services.backup_service import create_backup, verify_backup, restore_backup, database_status

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
    commands = parser.add_mutually_exclusive_group()
    commands.add_argument("--check", action="store_true", help="Check runtime without starting or changing data")
    commands.add_argument("--backup-only", action="store_true", help="Back up database AND document library; stop the server first")
    commands.add_argument("--verify-backup", type=Path)
    commands.add_argument("--restore", type=Path, help="Restore a complete backup into a NEW directory")
    commands.add_argument("--diagnose", action="store_true", help="Read-only offline diagnostics")
    parser.add_argument("--restore-to", type=Path)
    args = parser.parse_args()
    os.chdir(ROOT)
    database = Path(os.getenv("SMARTHR_DATABASE", str(ROOT / "data" / "smarthr.db")))
    documents = Path(os.getenv("SMARTHR_DOCUMENTS", ROOT / "data/documents"))
    if args.restore_to and not args.restore:
        parser.error('--restore-to requires --restore')
    if args.verify_backup:
        print(json.dumps(verify_backup(args.verify_backup), ensure_ascii=False, indent=2))
        return 0
    if args.restore:
        if not args.restore_to:
            parser.error('--restore requires --restore-to NEW_DIRECTORY')
        print(json.dumps(restore_backup(args.restore, args.restore_to), ensure_ascii=False, indent=2))
        return 0
    if args.diagnose:
        status = database_status(database)
        report = {"database": status, "documents_present": documents.is_dir(),
                  "log_directory": str(Path(os.getenv('SMARTHR_LOG_DIR', ROOT / 'data/logs')).resolve())}
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if status['status'] == 'ok' and status.get('schema_version') else 1
    if args.backup_only:
        with socket.socket() as probe:
            probe.settimeout(1)
            if probe.connect_ex(('127.0.0.1', int(os.getenv('FLASK_PORT', '5000')))) == 0:
                print('Stop the server before backing up database and documents together.', file=sys.stderr)
                return 1
        if not database.exists():
            print('Database does not exist yet', file=sys.stderr)
            return 1
        backup = create_backup(database, documents, ROOT / 'data/backups')
        print('Complete backup: ' + str(backup), flush=True)
        verify_backup(backup)
        print('Backup verification: OK')
        return 0
    required = ["flask", "Flask-SQLAlchemy", "Flask-Migrate", "scikit-learn", "python-docx", "pypdf", "rapidfuzz"]
    model = Path(os.getenv('CHAT_MODEL_PATH', ROOT / 'models/chat_model_real'))
    if (model / "smarthr_model_metadata.json").exists():
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
    backup = create_backup(database, documents, ROOT / 'data/backups') if database.exists() else None
    if backup:
        print("Complete backup: " + str(backup), flush=True)
        verify_backup(backup)
    subprocess.run([sys.executable, "-m", "flask", "--app", "app", "db", "upgrade"], check=True)
    print(f"Open http://localhost:{port} . Press Ctrl+C to stop.", flush=True)
    return subprocess.call([sys.executable, "app.py"])


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, sqlite3.Error, subprocess.CalledProcessError) as exc:
        print("SmartHR operation failed: " + str(exc), file=sys.stderr)
        raise SystemExit(1)
