import os
from pathlib import Path

from flask import Flask

from src.extensions import db, migrate
from src.services.parsing import extract_requirements
from src.services.scoring import get_status_decision

app = Flask(__name__, template_folder='src/templates', static_folder='src/static')
app.config["SECRET_KEY"] = os.getenv("SMARTHR_SECRET_KEY", "smarthr-local-development-key")
database_path = Path(os.getenv("SMARTHR_DATABASE", Path(__file__).resolve().parent / "data" / "smarthr.db"))
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{database_path.as_posix()}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024
db.init_app(app)
migrate.init_app(app, db)

from src import models  # noqa: E402,F401
from src.routes.main import main_bp  # noqa: E402

app.register_blueprint(main_bp)

# Unknown routes and methods are resolved before a blueprint is selected.
from src.services.api_validation import api_http_error
app.register_error_handler(404, api_http_error)
app.register_error_handler(405, api_http_error)

@app.errorhandler(413)
def upload_too_large(error):
    from flask import jsonify, request, redirect, url_for
    if request.path.startswith("/api/"):
        return jsonify({"error": "Размер запроса превышает 16 МБ."}), 413
    return redirect(url_for("main.documents_page", error="Размер файла превышает 16 МБ."))


if __name__ == '__main__':
    app.run(
        debug=os.getenv("FLASK_DEBUG", "0") == "1",
        host=os.getenv("FLASK_HOST", "127.0.0.1"),
        port=int(os.getenv("FLASK_PORT", "5000")),
        use_reloader=False,
    )
