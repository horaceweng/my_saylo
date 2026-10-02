import logging

import pytest

from app.main import _QuietPolling


def _record(method: str, path: str, status: int) -> logging.LogRecord:
    # The shape uvicorn gives its access-log records: (client, method, path, http version, status)
    return logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d',
                             ("127.0.0.1:5000", method, path, "1.1", status), None)


@pytest.mark.parametrize("path", ["/api/health", "/api/media", "/api/media?kind=video", "/api/media/12/updates?known=3&missing_from=1"])
def test_successful_polling_is_hidden(path):
    assert not _QuietPolling().filter(_record("GET", path, 200))


@pytest.mark.parametrize("method, path, status", [
    ("GET", "/api/health", 500),              # a failing poll still shows
    ("GET", "/api/media/12", 200),            # opening one item is a real action
    ("POST", "/api/media", 200),              # adding a video
    ("GET", "/api/phrases", 200),
    ("GET", "/api/healthz", 200),
])
def test_everything_else_still_shows(method, path, status):
    assert _QuietPolling().filter(_record(method, path, status))


def test_records_of_another_shape_pass_through():
    assert _QuietPolling().filter(logging.LogRecord("uvicorn.access", logging.INFO, "", 0, "plain message", None, None))
