"""Transaction boundaries for SQL-backed HTTP operations."""
from functools import wraps

from flask import make_response

from src.storage.sql_storage import atomic_write


class _RejectedOperation(Exception):
    def __init__(self, response):
        self.response = response


def transactional_request(view):
    """Commit successful responses; roll back exceptions AND handled HTTP errors.

    Repository writes nest under atomic_write and only flush until this boundary.
    A route may catch an exception and return 400/500: that still must roll back.
    """
    @atomic_write
    def execute(*args, **kwargs):
        response = make_response(view(*args, **kwargs))
        if response.status_code >= 400:
            raise _RejectedOperation(response)
        return response

    @wraps(view)
    def wrapped(*args, **kwargs):
        try:
            return execute(*args, **kwargs)
        except _RejectedOperation as rejected:
            return rejected.response
    return wrapped
