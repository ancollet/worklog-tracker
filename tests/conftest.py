import pytest

from worklog import db as db_module


@pytest.fixture
def conn():
    """In-memory SQLite connection with full schema applied."""
    c = db_module.connect(":memory:")
    yield c
    c.close()
