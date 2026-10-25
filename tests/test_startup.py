"""Fresh-database startup and page/API smoke checks, without a running server."""
from pathlib import Path
import os

import pytest
from sqlalchemy import text

from app import app
from src.chat.models import MockChatModel
from src.extensions import db
from src.routes import main as routes


@pytest.mark.parametrize('url',['/','/candidates','/chat','/documents','/vacancies','/templates','/interviews','/analytics'])
def test_application_pages_open_on_migrated_database(url):
    with app.test_client() as client:
        response = client.get(url)
    assert response.status_code == 200
    assert response.mimetype == 'text/html'


def test_test_session_is_isolated_and_database_migrations_are_current():
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    root = Path(__file__).resolve().parents[1]
    config = Config()
    config.set_main_option('script_location', str(root / 'migrations'))
    expected = ScriptDirectory.from_config(config).get_current_head()
    database = Path(os.environ['SMARTHR_DATABASE']).resolve()
    assert database.is_relative_to((root / 'data/test-runs').resolve())
    assert isinstance(routes.chat_model, MockChatModel)
    with app.app_context():
        assert db.session.execute(text('SELECT version_num FROM alembic_version')).scalar() == expected
        assert db.session.execute(text('PRAGMA foreign_keys')).scalar() == 1
        assert db.session.execute(text('PRAGMA foreign_key_check')).all() == []
        assert db.session.execute(text('PRAGMA quick_check')).scalar() == 'ok'


def test_application_json_api_opens_on_fresh_database():
    with app.test_client() as client:
        for url in ['/api/candidates','/api/vacancies','/api/interviews','/api/chat/conversations']:
            response = client.get(url)
            assert response.status_code == 200 and response.is_json
