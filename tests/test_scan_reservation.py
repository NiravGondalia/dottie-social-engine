import threading
import time
from unittest.mock import Mock

from core.orchestrator import Orchestrator


def test_concurrent_scan_all_calls_run_inner_scan_once():
    callers_ready = threading.Barrier(2)

    class RacingOrchestrator(Orchestrator):
        @property
        def _paused(self):
            callers_ready.wait(timeout=5)
            return False

    orch = RacingOrchestrator.__new__(RacingOrchestrator)
    orch._scan_running = False
    orch._scan_status = {
        "state": "idle",
        "message": "",
        "started_at": None,
        "finished_at": None,
        "opportunities": None,
    }
    orch._state_lock = threading.Lock()
    orch.rate_limiter = Mock()
    orch.rate_limiter.is_active_hours.return_value = True
    orch.rate_limiter.should_take_random_break.return_value = False
    orch.db = Mock()
    orch.db.get_pending_opportunities.return_value = []

    inner_calls = 0
    inner_lock = threading.Lock()

    def scan_inner(*, force=False):
        nonlocal inner_calls
        with inner_lock:
            inner_calls += 1
        time.sleep(0.05)

    orch._Orchestrator__scan_all_inner = scan_inner

    callers = [threading.Thread(target=orch._scan_all) for _ in range(2)]
    for caller in callers:
        caller.start()
    for caller in callers:
        caller.join(timeout=5)

    assert all(not caller.is_alive() for caller in callers)
    assert inner_calls == 1
