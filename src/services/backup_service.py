"""Versioned local snapshots of SQLite and the document library (no model weights)."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import uuid
import time
from contextlib import closing


def database_status(path):
    path = Path(path).resolve()
    if not path.is_file():
        return {"status": "missing"}
    try:
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=5)) as connection:
            check = connection.execute('PRAGMA quick_check').fetchall()
            foreign_keys = len(connection.execute('PRAGMA foreign_key_check').fetchall())
            has_version = connection.execute("SELECT 1 FROM sqlite_master WHERE name='alembic_version'").fetchone()
            version = connection.execute('SELECT version_num FROM alembic_version').fetchone() if has_version else None
        return {"status": "ok" if check == [('ok',)] and not foreign_keys else "error",
                "quick_check": check == [('ok',)], "foreign_key_violations": foreign_keys,
                "schema_version": version[0] if version else None}
    except sqlite3.Error:
        return {"status": "error", "error": "unreadable_database"}


def _hash(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _publish(stage, target):
    """Publish a prepared directory; short retries for Windows scanner locks only."""
    if stage.parent.resolve() != target.parent.resolve():
        raise ValueError('Промежуточная и целевая папки должны иметь общего родителя')
    for attempt in range(10):
        if target.exists():
            raise ValueError('Целевая папка уже существует; исходные данные сохранены')
        try:
            stage.rename(target)
            return
        except PermissionError as exc:
            if getattr(exc, 'winerror', None) not in {5, 32, 33} or attempt == 9:
                raise
            time.sleep(0.1)


def _files(root):
    """Never follow symlinks or Windows junctions outside the selected directory."""
    if root.is_symlink() or root.is_junction():
        raise ValueError('Ссылки и junction в резервной копии не поддерживаются')
    result = []
    for path in root.rglob('*'):
        if path.is_symlink() or path.is_junction() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError('Обнаружен путь за пределами резервируемой папки')
        if path.is_file():
            result.append(path)
    return sorted(result)


def create_backup(database, documents, destination):
    """Caller must stop the application to snapshot database and files together."""
    for path in (database, documents, destination):
        if Path(path).is_symlink() or Path(path).is_junction():
            raise ValueError('Пути резервной копии не должны быть ссылками или junction')
    database, documents, destination = map(lambda p: Path(p).resolve(), (database, documents, destination))
    if not database.is_file():
        raise ValueError('База не найдена; сначала инициализируйте приложение')
    if destination.is_relative_to(documents):
        raise ValueError('Папка копий не должна находиться внутри библиотеки документов')
    destination.mkdir(parents=True, exist_ok=True)
    name = 'smarthr_' + datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
    stage = destination / ('.partial-' + uuid.uuid4().hex)
    stage.mkdir()
    target = destination / name
    # On failure leave the partial directory for diagnosis; never publish it as complete.
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as source:
        with closing(sqlite3.connect(stage / 'database.sqlite3')) as output:
            source.backup(output)
            # A portable bundle must not depend on WAL/SHM sidecar files.
            output.execute('PRAGMA journal_mode=DELETE').fetchone()
    library = stage / 'documents'
    library.mkdir()
    if documents.exists():
        before = {p.relative_to(documents).as_posix(): (p.stat().st_size, p.stat().st_mtime_ns)
                  for p in _files(documents)}
        for relative in before:
            source = documents / relative
            copied = library / relative
            copied.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, copied)
            if _hash(source) != _hash(copied):
                raise ValueError('Документы изменились во время копирования; остановите приложение')
        after = {p.relative_to(documents).as_posix(): (p.stat().st_size, p.stat().st_mtime_ns)
                 for p in _files(documents)}
        if before != after:
            raise ValueError('Документы изменились во время копирования; остановите приложение')
    manifest = {"format_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
                "database": database_status(stage / 'database.sqlite3'),
                "files": {p.relative_to(stage).as_posix(): {"size": p.stat().st_size, "sha256": _hash(p)}
                          for p in _files(stage)}}
    (stage / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    # Preserve even an unhealthy database as a diagnostic backup; verification reports it.
    if target.exists() or stage.parent.resolve() != destination:
        raise ValueError('Не удалось опубликовать резервную копию')
    _publish(stage,target)
    return target


def verify_backup(folder):
    if Path(folder).is_symlink() or Path(folder).is_junction():
        raise ValueError('Папка копии не должна быть ссылкой или junction')
    folder = Path(folder).resolve(strict=True)
    files = _files(folder)
    try:
        manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
        if manifest['format_version'] != 1 or not isinstance(manifest['files'], dict):
            raise ValueError
        expected = manifest['files']
        if 'database.sqlite3' not in expected:
            raise ValueError
        for relative, details in expected.items():
            path = PurePosixPath(relative)
            if (path.is_absolute() or '..' in path.parts or '\\' in relative
                    or relative != path.as_posix() or ':' in relative
                    or not (relative == 'database.sqlite3' or relative.startswith('documents/'))):
                raise ValueError
            file = folder / relative
            if not file.is_file() or file.stat().st_size != details['size'] or _hash(file) != details['sha256']:
                raise ValueError
        actual = {p.relative_to(folder).as_posix() for p in files}
        if actual != set(expected) | {'manifest.json'}:
            raise ValueError
    except (KeyError, TypeError, ValueError, OSError) as exc:
        raise ValueError('Резервная копия повреждена или её состав не соответствует манифесту') from exc
    status = database_status(folder / 'database.sqlite3')
    if status['status'] != 'ok':
        raise ValueError('База в копии не прошла проверку целостности; оригинал сохранён')
    return {"status": "ok", "files": len(expected), "database": status}


def restore_backup(folder, target):
    """Restore only to a new directory: never overwrite a working database/library."""
    if Path(folder).is_symlink() or Path(folder).is_junction():
        raise ValueError('Папка копии не должна быть ссылкой или junction')
    folder = Path(folder).resolve(strict=True)
    target = Path(target).resolve()
    verification = verify_backup(folder)
    if target.exists() or target.is_relative_to(folder):
        raise ValueError('Восстановление допускается только в новую папку вне резервной копии')
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = target.parent / ('.restore-' + uuid.uuid4().hex)
    stage.mkdir()
    (stage / 'documents').mkdir()
    for file in _files(folder):
        copied = stage / file.relative_to(folder)
        copied.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(file, copied)
    verify_backup(stage)
    if target.exists() or stage.parent.resolve() != target.parent:
        raise ValueError('Целевая папка уже существует; восстановление остановлено')
    _publish(stage,target)
    return {"restored_to": str(target), **verification}
