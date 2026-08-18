import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from core.database import Database


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "test.db")
    instance = Database(path)
    yield instance
    instance.close()


@pytest.fixture
def fake_orch(db):
    orch = SimpleNamespace()
    orch.db = db
    orch._scan_running = False
    orch._state_lock = threading.Lock()
    orch._scan_status = {
        "state": "idle",
        "message": "",
        "started_at": None,
        "finished_at": None,
        "opportunities": 0,
        "job_id": None,
    }
    orch.projects = [
        {"project": {"name": "dottie", "url": "https://dottie.app"}},
    ]
    orch.settings = {
        "web_dashboard": {"port": 8420},
        "bot": {"scan_interval_minutes": 12, "version": "test"},
    }
    orch.get_scan_status = MagicMock(side_effect=lambda: {
        **orch._scan_status,
        "running": orch._scan_running,
    })
    orch._scan_all_safe = MagicMock()
    orch.content_gen = SimpleNamespace(
        generate_reddit_comment=MagicMock(return_value="generated comment"),
    )
    orch.llm = SimpleNamespace(
        generate=MagicMock(return_value="revised comment"),
    )
    orch.account_mgr = SimpleNamespace(
        get_next_account=MagicMock(return_value=None),
    )
    orch._get_reddit_bot = MagicMock()
    return orch
