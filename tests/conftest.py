"""Safe default test session: isolated SQLite, local files and no model downloads."""
import os
from pathlib import Path
import tempfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
TRAINING_TOOL_FILES = {
    "test_chat_training.py", "test_chat_dataset.py", "test_real_dataset_collection.py",
    "test_synthetic_chat_dataset.py", "test_rag_chat_dataset.py",
}


def pytest_addoption(parser):
    parser.addoption("--training-tools", action="store_true", default=False,
                     help="Also collect optional dataset/training utility checks (not model training)")


def pytest_ignore_collect(collection_path, config):
    if collection_path.name in TRAINING_TOOL_FILES and not config.getoption("--training-tools"):
        return True


def pytest_configure(config):
    folder = ROOT / "data" / "test-runs"
    folder.mkdir(parents=True, exist_ok=True)
    config._smarthr_run = Path(tempfile.mkdtemp(prefix="application-", dir=folder))
    run = config._smarthr_run
    environment = {
        "SMARTHR_DATABASE": str(run / "application.db"),
        "SMARTHR_DOCUMENTS": str(run / "documents"),
        "CHAT_MODEL_PATH": str(run / "no-chat-artifact"),
        "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "RAG_BACKEND": "tfidf",
        "SMARTHR_LOG_DIR": str(run / "logs"),
    }
    config._smarthr_environment = {key: os.environ.get(key) for key in environment}
    os.environ.update(environment)
    if not config.option.basetemp:
        config.option.basetemp = str(run / "temporary")
    if os.name == "nt":
        # pytest's optional 'current' temp symlink can hang on restricted Windows hosts.
        # Temp directories and all test assertions remain intact.
        import _pytest.pathlib
        config._smarthr_symlink = _pytest.pathlib._force_symlink
        _pytest.pathlib._force_symlink = lambda *args, **kwargs: None


def pytest_collection_modifyitems(items):
    for item in items:
        item.add_marker("training_tools" if item.path.name in TRAINING_TOOL_FILES else "application")


def pytest_report_header(config):
    return f"SmartHR: isolated DB/files in {config._smarthr_run}; training utilities opt-in"


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    if not config.getoption("--training-tools"):
        terminalreporter.write_line('Application suite: 5 dataset/training-tool modules excluded (opt-in --training-tools).')
    terminalreporter.write_line(f'Test data: {config._smarthr_run}')


@pytest.fixture(scope="session", autouse=True)
def isolated_application(request):
    from app import app
    from flask_migrate import upgrade
    from src.extensions import db
    from src.routes import main as routes
    # Session configuration runs before test imports, so all Flask app instances use
    # this disposable database instead of the user's SMARTHR_DATABASE.
    run = request.config._smarthr_run
    app.config.update(TESTING=True)
    with app.app_context():
        upgrade(directory=str(ROOT / "migrations"))
    from src.services.diagnostics import configure_logging
    configure_logging(app)
    original = (routes.UPLOAD_DOCS_DIR, routes.rag_pipeline, routes.DOCUMENTS)
    from src.core.rag_pipeline import RagPipeline
    routes.UPLOAD_DOCS_DIR = run / "documents"
    routes.rag_pipeline = RagPipeline(backend="tfidf")
    routes.rag_pipeline.build_index(routes._library_documents())
    routes.DOCUMENTS = routes._load_documents()
    try:
        yield
    finally:
        routes.UPLOAD_DOCS_DIR, routes.rag_pipeline, routes.DOCUMENTS = original
        with app.app_context():
            db.session.remove()
            db.engine.dispose()


def pytest_unconfigure(config):
    for key, value in getattr(config, "_smarthr_environment", {}).items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    if hasattr(config, "_smarthr_symlink"):
        import _pytest.pathlib
        _pytest.pathlib._force_symlink = config._smarthr_symlink
