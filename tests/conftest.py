from datetime import datetime, timedelta, timezone

import pytest

from ember.store import Mind


class Clock:
    """A clock the tests can move. The mind never takes a time from anyone else."""

    def __init__(self):
        self.t = datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.t

    def forward(self, **kw):
        self.t += timedelta(**kw)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture(params=["fts5", "like"])
def mind(tmp_path, clock, request):
    """Every unit test runs twice: once with FTS5 search, once with the LIKE fallback."""
    return Mind(tmp_path / "mind.db", now=clock, fts=request.param == "fts5")
