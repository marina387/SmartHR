from contextlib import closing
import json
import logging
from pathlib import Path
import sqlite3
import sys

from flask import Flask, jsonify
import pytest

from src.services.backup_service import create_backup, verify_backup, restore_backup, database_status
from src.services.diagnostics import install_diagnostics


@pytest.fixture
def source(tmp_path):
    database = tmp_path / 'source.db'
    with closing(sqlite3.connect(database)) as connection:
        connection.execute('CREATE TABLE example (id INTEGER PRIMARY KEY, value TEXT)')
        connection.execute('INSERT INTO example VALUES (1,?)', ('private candidate',))
        connection.commit()
    documents = tmp_path / 'documents'
    documents.mkdir()
    (documents / 'current.txt').write_text('Current policy', encoding='utf-8')
    (documents / 'old.txt').write_text('Previous version', encoding='utf-8')
    (documents / 'current.json').write_text('{"name":"Policy.txt"}', encoding='utf-8')
    (documents / 'library.json').write_text('{"policy":{"replacement":"current","versions":["old","current"]}}', encoding='utf-8')
    return database, documents


def test_full_backup_round_trip_preserves_database_catalog_and_versions(source,tmp_path):
    database, documents = source
    original = database.read_bytes()
    backup = create_backup(database,documents,tmp_path / 'backups')
    assert verify_backup(backup)['status']=='ok'
    target = tmp_path / 'restored'
    assert restore_backup(backup,target)['status']=='ok'
    for path in documents.iterdir():
        assert (target / 'documents' / path.name).read_bytes()==path.read_bytes()
    with closing(sqlite3.connect(target / 'database.sqlite3')) as connection:
        assert connection.execute('SELECT * FROM example').fetchall()==[(1,'private candidate')]
    assert database.read_bytes()==original
    assert database_status(target/'database.sqlite3')['status']=='ok'


def test_backup_includes_committed_wal_rows_without_sidecar_dependency(source,tmp_path):
    with closing(sqlite3.connect(source[0])) as writer:
        assert writer.execute('PRAGMA journal_mode=WAL').fetchone()[0]=='wal'
        writer.execute('INSERT INTO example VALUES (2,?)',('committed in WAL',))
        writer.commit()
        backup=create_backup(*source,tmp_path/'backups')
        assert verify_backup(backup)['status']=='ok'
        assert not list(backup.glob('database.sqlite3-*'))
        with closing(sqlite3.connect(backup/'database.sqlite3')) as restored:
            assert restored.execute('SELECT COUNT(*) FROM example').fetchone()[0]==2
            assert restored.execute('PRAGMA journal_mode').fetchone()[0]=='delete'


@pytest.mark.parametrize('damage',['changed','missing','extra','traversal','version','wrong_manifest'])
def test_invalid_backup_is_rejected_before_restore(source,tmp_path,damage):
    backup=create_backup(*source,tmp_path/'backups')
    manifest=json.loads((backup/'manifest.json').read_text(encoding='utf-8'))
    if damage=='changed':
        (backup/'documents/current.txt').write_text('Tampered')
    elif damage=='missing':
        (backup/'documents/current.txt').unlink()
    elif damage=='extra':
        (backup/'extra.txt').write_text('Unexpected')
    elif damage=='traversal':
        manifest['files']['../outside.txt']={'size':1,'sha256':'x'}
    elif damage=='version':
        manifest['format_version']=999
    else:
        manifest=[]
    if damage in {'traversal','version','wrong_manifest'}:
        (backup/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
    target=tmp_path/'restored'
    with pytest.raises(ValueError):
        restore_backup(backup,target)
    assert not target.exists()


def test_restore_never_overwrites_existing_data(source,tmp_path):
    backup=create_backup(*source,tmp_path/'backups')
    target=tmp_path/'working'
    target.mkdir()
    (target/'keep.txt').write_text('Keep')
    with pytest.raises(ValueError,match='новую папку'):
        restore_backup(backup,target)
    assert (target/'keep.txt').read_text()=='Keep'
    with pytest.raises(ValueError):
        restore_backup(backup,backup/'nested')


def test_backup_destination_cannot_recurse_into_library(source):
    with pytest.raises(ValueError):
        create_backup(*source,source[1]/'nested-backups')


@pytest.mark.parametrize('operation',['backup','restore'])
def test_transient_windows_directory_lock_does_not_lose_backup(source,tmp_path,monkeypatch,operation):
    backup=create_backup(*source,tmp_path/'backups') if operation=='restore' else None
    original=Path.rename
    blocked=[]
    def rename(path,target):
        if not blocked:
            blocked.append(path)
            error=PermissionError('temporary Windows directory lock')
            error.winerror=5
            raise error
        return original(path,target)
    monkeypatch.setattr(Path,'rename',rename)
    result=(create_backup(*source,tmp_path/'backups') if operation=='backup'
            else Path(restore_backup(backup,tmp_path/'restored')['restored_to']))
    assert blocked
    assert verify_backup(result)['status']=='ok'


def test_failed_copy_is_not_published_and_source_is_preserved(source,tmp_path,monkeypatch):
    import src.services.backup_service as service
    original=source[0].read_bytes()
    def fail(*args,**kwargs):
        raise OSError('injected copy failure')
    monkeypatch.setattr(service.shutil,'copyfile',fail)
    with pytest.raises(OSError):
        create_backup(*source,tmp_path/'backups')
    assert not list((tmp_path/'backups').glob('smarthr_*'))
    assert source[0].read_bytes()==original


def test_symlink_backup_cannot_escape(source,tmp_path):
    # No Windows symlink privileges needed: verify rejection before traversal.
    from unittest.mock import patch
    with patch.object(Path,'is_symlink',return_value=True):
        with pytest.raises(ValueError):
            create_backup(*source,tmp_path/'backups')


def test_unhealthy_database_can_be_saved_but_not_restored(source,tmp_path):
    with closing(sqlite3.connect(source[0])) as connection:
        connection.executescript('CREATE TABLE parent(id INTEGER PRIMARY KEY); '
                                 'CREATE TABLE child(id INTEGER REFERENCES parent(id)); '
                                 'INSERT INTO child VALUES (9);')
    backup=create_backup(*source,tmp_path/'backups')
    assert backup.exists()
    with pytest.raises(ValueError,match='целостности'):
        verify_backup(backup)
    assert database_status(tmp_path/'missing.db')['status']=='missing'
    assert not (tmp_path/'missing.db').exists()


def test_request_ids_logs_rotation_and_no_private_payload(tmp_path,monkeypatch):
    monkeypatch.setenv('SMARTHR_LOG_DIR',str(tmp_path/'logs'))
    app=Flask('diagnostics-test')
    install_diagnostics(app)
    @app.route('/error',methods=['POST'])
    def error():
        try:
            raise ValueError('private-exception-message')
        except ValueError:
            app.logger.exception('private-log-message')
        return jsonify(error='Не удалось выполнить операцию'),500
    with app.test_client() as client:
        response=client.post('/error?token=private-query',json={'resume':'private-resume'},
                             headers={'X-Request-ID':'untrusted-request-id'})
    request_id=response.headers['X-Request-ID']
    assert response.json['request_id']==request_id and len(request_id)==32
    assert request_id!='untrusted-request-id'
    log=(tmp_path/'logs/application.jsonl').read_text(encoding='utf-8')
    assert request_id in log
    assert 'private-' not in log
    records=[json.loads(line) for line in log.splitlines()]
    assert any(row.get('error_type')=='ValueError' for row in records)
    assert any(row.get('status')==500 for row in records)
    handler=next(h for h in app.logger.handlers if hasattr(h,'maxBytes'))
    handler.maxBytes=1
    app.logger.info('rotation',extra={'event':'rotation_check'})
    assert (tmp_path/'logs/application.jsonl.1').exists()
    for item in list(app.logger.handlers):
        item.close()
        app.logger.removeHandler(item)


def test_cli_backup_restore_diagnose_and_busy_server(source,tmp_path,monkeypatch,capsys):
    import run_smarthr as launcher
    monkeypatch.setattr(launcher,'ROOT',tmp_path)
    monkeypatch.setenv('SMARTHR_DATABASE',str(source[0]))
    monkeypatch.setenv('SMARTHR_DOCUMENTS',str(source[1]))
    class Probe:
        busy=False
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def settimeout(self,*args): pass
        def connect_ex(self,*args): return 0 if self.busy else 1
    monkeypatch.setattr(launcher.socket,'socket',Probe)
    monkeypatch.setattr(sys,'argv',['run_smarthr.py','--backup-only'])
    Probe.busy=True
    assert launcher.main()==1
    assert not (tmp_path/'data/backups').exists()
    Probe.busy=False
    assert launcher.main()==0
    backup=next((tmp_path/'data/backups').glob('smarthr_*'))
    monkeypatch.setattr(sys,'argv',['run_smarthr.py','--verify-backup',str(backup)])
    assert launcher.main()==0
    target=tmp_path/'restore'
    monkeypatch.setattr(sys,'argv',['run_smarthr.py','--restore',str(backup),'--restore-to',str(target)])
    assert launcher.main()==0
    monkeypatch.setattr(sys,'argv',['run_smarthr.py','--diagnose'])
    # A generic SQLite without migration metadata is not an initialized SmartHR DB.
    assert launcher.main()==1
    assert 'private candidate' not in capsys.readouterr().out


def test_health_is_read_only_and_reports_migration_mismatch(monkeypatch):
    from app import app
    from src.services import health_service
    with app.test_client() as client:
        response=client.get('/api/health')
        assert response.status_code==200 and response.json['status']=='ok'
        assert response.headers['X-Request-ID']
        monkeypatch.setattr(health_service,'expected_revisions',lambda:{'unknown-version'})
        response=client.get('/api/health')
        assert response.status_code==503
        assert response.json['checks']['schema']=='migration_required'
        assert 'request_id' in response.json
        assert 'database.sqlite' not in response.get_data(as_text=True)


def test_health_does_not_create_a_missing_database(tmp_path):
    from src.extensions import db
    from src.services.health_service import readiness
    app=Flask('missing-health-database')
    database=tmp_path/'must-not-be-created.db'
    app.config['SQLALCHEMY_DATABASE_URI']=f'sqlite:///{database.as_posix()}'
    db.init_app(app)
    with app.app_context():
        payload,status=readiness()
        assert status==503 and payload['checks']['database']=='unavailable'
        assert not database.exists()
        db.engine.dispose()
