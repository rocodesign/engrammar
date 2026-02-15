"""Tests for daemon maintenance scheduling."""

from src.daemon import EngrammarDaemon


class _FakeProc:
    """Minimal Popen-like object for daemon tests."""

    _next_pid = 1000

    def __init__(self, cmd, kwargs):
        self.cmd = cmd
        self.kwargs = kwargs
        self.pid = _FakeProc._next_pid
        _FakeProc._next_pid += 1

    def poll(self):
        return None


def test_run_maintenance_single_flight(monkeypatch, tmp_path):
    spawned = []

    def fake_popen(cmd, **kwargs):
        proc = _FakeProc(cmd, kwargs)
        spawned.append(proc)
        return proc

    monkeypatch.setattr("src.daemon.LOG_PATH", str(tmp_path / "daemon.log"))
    monkeypatch.setattr("src.daemon.subprocess.Popen", fake_popen)

    daemon = EngrammarDaemon()

    first = daemon._handle_request({"type": "run_maintenance", "evaluate_limit": 7})
    second = daemon._handle_request({"type": "run_maintenance", "evaluate_limit": 7})

    assert len(spawned) == 2
    assert first["extract"]["started"] is True
    assert first["evaluate"]["started"] is True
    assert second["extract"]["status"] == "already_running"
    assert second["evaluate"]["status"] == "already_running"

    assert spawned[0].cmd[-1] == "extract"
    assert spawned[1].cmd[-3:] == ["evaluate", "--limit", "7"]
    assert spawned[0].kwargs["env"]["ENGRAMMAR_INTERNAL_RUN"] == "1"
    assert spawned[1].kwargs["env"]["ENGRAMMAR_INTERNAL_RUN"] == "1"
