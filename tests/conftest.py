import os
import tempfile

import pytest

from core.database import Database


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "test.db")
    instance = Database(path)
    yield instance
    instance.close()
