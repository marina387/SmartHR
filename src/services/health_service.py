"""Read-only readiness check, without starting inference or model training."""
from functools import lru_cache
from pathlib import Path
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from src.extensions import db


@lru_cache(maxsize=1)
def expected_revisions():
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    config = Config()
    config.set_main_option('script_location', str(Path(__file__).resolve().parents[2] / 'migrations'))
    return set(ScriptDirectory.from_config(config).get_heads())


def readiness():
    checks = {"database": "unavailable", "schema": "unavailable"}
    try:
        database = db.engine.url.database
        if (db.engine.dialect.name == 'sqlite' and database not in {None, '', ':memory:'}
                and not Path(database).is_file()):
            return {"status": "degraded", "checks": checks,
                    "error": "База данных не найдена. Выполните инициализацию или восстановление."}, 503
        db.session.execute(text('SELECT 1'))
        checks['database'] = 'ok'
        actual = set(db.session.execute(text('SELECT version_num FROM alembic_version')).scalars())
        checks['schema'] = 'ok' if actual == expected_revisions() else 'migration_required'
    except (SQLAlchemyError, OSError):
        db.session.rollback()
    ready = all(value == 'ok' for value in checks.values())
    payload = {"status": "ok" if ready else "degraded", "checks": checks}
    if not ready:
        payload['error'] = 'База данных не готова. Проверьте диагностику и миграции.'
    return payload, 200 if ready else 503
