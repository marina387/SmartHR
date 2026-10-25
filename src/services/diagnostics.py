"""Small rotating operational logs: no bodies, query strings, SQL values or secrets."""
from datetime import datetime, timezone
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import time
import uuid

from flask import g, has_request_context, request

ROOT = Path(__file__).resolve().parents[2]


class OperationalFormatter(logging.Formatter):
    def format(self, record):
        entry = {"timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
                 "level": record.levelname, "event": getattr(record, 'event', 'application_log')}
        for key in ('request_id', 'method', 'endpoint', 'status', 'duration_ms'):
            value = getattr(record, key, None)
            if value is not None:
                entry[key] = value
        if has_request_context():
            entry.setdefault('request_id', getattr(g, 'request_id', None))
            entry.setdefault('endpoint', request.endpoint)
        if record.exc_info:
            entry['error_type'] = record.exc_info[0].__name__
            trace = record.exc_info[2]
            while trace and trace.tb_next:
                trace = trace.tb_next
            if trace:
                entry['location'] = {"file": Path(trace.tb_frame.f_code.co_filename).name,
                                     "function": trace.tb_frame.f_code.co_name, "line": trace.tb_lineno}
        # Deliberately do not serialize getMessage(), exception text, URL, or payload.
        return json.dumps(entry, ensure_ascii=False)


def configure_logging(app):
    folder = Path(os.getenv('SMARTHR_LOG_DIR', ROOT / 'data/logs')).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    filename = str(folder / 'application.jsonl')
    from flask.logging import default_handler
    app.logger.removeHandler(default_handler)
    if not any(getattr(handler, 'baseFilename', None) == filename for handler in app.logger.handlers):
        handler = RotatingFileHandler(filename, maxBytes=1024 * 1024, backupCount=3,
                                      encoding='utf-8', delay=True)
        handler.setFormatter(OperationalFormatter())
        app.logger.addHandler(handler)
    app.logger.disabled = False
    app.logger.propagate = False
    app.logger.setLevel(logging.INFO)


def install_diagnostics(app):
    configure_logging(app)

    @app.before_request
    def begin_request():
        g.request_id = uuid.uuid4().hex
        g.request_started = time.monotonic()

    @app.after_request
    def finish_request(response):
        request_id = getattr(g, 'request_id', uuid.uuid4().hex)
        response.headers['X-Request-ID'] = request_id
        if response.status_code >= 400 and response.is_json:
            payload = response.get_json(silent=True)
            if isinstance(payload, dict) and 'error' in payload:
                payload['request_id'] = request_id
                response.set_data(json.dumps(payload, ensure_ascii=False))
                response.content_type = 'application/json'
        duration = round((time.monotonic() - getattr(g, 'request_started', time.monotonic())) * 1000, 2)
        app.logger.log(logging.ERROR if response.status_code >= 500 else logging.INFO,
                       'request complete', extra={"event": "request_complete", "request_id": request_id,
                       "method": request.method, "endpoint": request.endpoint, "status": response.status_code,
                       "duration_ms": duration})
        return response
