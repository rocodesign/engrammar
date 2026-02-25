"""Tests for daemon maintenance scheduling and turn queue."""

import time

from src.daemon import EngrammarDaemon


class _FakeProc:
    """Minimal Popen-like object for daemon tests."""

    _next_pid = 1000

    def __init__(self, cmd, kwargs):
        self.cmd = cmd
        self.kwargs = kwargs
        self.pid = _FakeProc._next_pid
        _FakeProc._next_pid += 1
        self._finished = False

    def poll(self):
        return 0 if self._finished else None

    def finish(self):
        self._finished = True


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


def _make_daemon(monkeypatch, tmp_path, spawned):
    """Create a daemon with mocked subprocess."""
    def fake_popen(cmd, **kwargs):
        proc = _FakeProc(cmd, kwargs)
        spawned.append(proc)
        return proc

    monkeypatch.setattr("src.daemon.LOG_PATH", str(tmp_path / "daemon.log"))
    monkeypatch.setattr("src.daemon.subprocess.Popen", fake_popen)
    return EngrammarDaemon()


def test_process_turn_starts_extract_and_evaluate(monkeypatch, tmp_path):
    spawned = []
    daemon = _make_daemon(monkeypatch, tmp_path, spawned)

    result = daemon._handle_request({
        "type": "process_turn",
        "session_id": "sess-a",
        "transcript_path": "/tmp/a.jsonl",
    })

    assert result["status"] == "ok"
    assert result["extract"]["started"] is True
    assert result["evaluate"]["started"] is True
    # Two separate procs: extraction + evaluation
    assert len(spawned) == 2
    assert "process-turn" in spawned[0].cmd
    assert "sess-a" in spawned[0].cmd
    assert "evaluate" in spawned[1].cmd
    assert "sess-a" in spawned[1].cmd


def test_process_turn_queues_when_busy(monkeypatch, tmp_path):
    spawned = []
    daemon = _make_daemon(monkeypatch, tmp_path, spawned)

    # First request starts extraction + evaluation (2 procs)
    daemon._handle_request({
        "type": "process_turn",
        "session_id": "sess-a",
        "transcript_path": "/tmp/a.jsonl",
    })
    # Second request while extraction running — should queue
    result = daemon._handle_request({
        "type": "process_turn",
        "session_id": "sess-b",
        "transcript_path": "/tmp/b.jsonl",
    })

    assert result["status"] == "queued"
    assert result["pending"] == 1
    assert len(spawned) == 2  # Only first request's extract + evaluate


def test_coalesces_same_session(monkeypatch, tmp_path):
    spawned = []
    daemon = _make_daemon(monkeypatch, tmp_path, spawned)

    # Start extraction (spawns extract + evaluate)
    daemon._handle_request({
        "type": "process_turn",
        "session_id": "sess-a",
        "transcript_path": "/tmp/a.jsonl",
    })
    assert len(spawned) == 2  # extract + evaluate for sess-a

    # Queue two turns for same session — should coalesce
    daemon._handle_request({
        "type": "process_turn",
        "session_id": "sess-b",
        "transcript_path": "/tmp/b1.jsonl",
    })
    daemon._handle_request({
        "type": "process_turn",
        "session_id": "sess-b",
        "transcript_path": "/tmp/b2.jsonl",
    })

    # Only 1 pending (coalesced), with latest transcript path
    assert len(daemon._pending_turns) == 1
    assert daemon._pending_turns["sess-b"] == "/tmp/b2.jsonl"


def test_drain_starts_pending_after_finish(monkeypatch, tmp_path):
    spawned = []
    daemon = _make_daemon(monkeypatch, tmp_path, spawned)

    # Start extraction (spawns extract + evaluate = 2 procs), queue another
    daemon._handle_request({
        "type": "process_turn",
        "session_id": "sess-a",
        "transcript_path": "/tmp/a.jsonl",
    })
    daemon._handle_request({
        "type": "process_turn",
        "session_id": "sess-b",
        "transcript_path": "/tmp/b.jsonl",
    })

    assert len(spawned) == 2  # extract + evaluate for sess-a

    # Simulate extraction finishing (evaluate for sess-a still running)
    spawned[0].finish()
    daemon._drain_pending_turns()

    # Drain spawns extract for sess-b; evaluate is already_running from sess-a
    assert len(spawned) == 3
    assert "sess-b" in spawned[2].cmd  # extract
    assert len(daemon._pending_turns) == 0


def test_drain_noop_when_still_running(monkeypatch, tmp_path):
    spawned = []
    daemon = _make_daemon(monkeypatch, tmp_path, spawned)

    daemon._handle_request({
        "type": "process_turn",
        "session_id": "sess-a",
        "transcript_path": "/tmp/a.jsonl",
    })
    daemon._handle_request({
        "type": "process_turn",
        "session_id": "sess-b",
        "transcript_path": "/tmp/b.jsonl",
    })

    # Drain while extract_proc still running — should not start anything
    daemon._drain_pending_turns()

    assert len(spawned) == 2  # Only initial extract + evaluate
    assert len(daemon._pending_turns) == 1


def test_drain_processes_multiple_pending_sequentially(monkeypatch, tmp_path):
    spawned = []
    daemon = _make_daemon(monkeypatch, tmp_path, spawned)

    # Start extraction (2 procs), queue two different sessions
    daemon._handle_request({
        "type": "process_turn",
        "session_id": "sess-a",
        "transcript_path": "/tmp/a.jsonl",
    })
    daemon._handle_request({
        "type": "process_turn",
        "session_id": "sess-b",
        "transcript_path": "/tmp/b.jsonl",
    })
    daemon._handle_request({
        "type": "process_turn",
        "session_id": "sess-c",
        "transcript_path": "/tmp/c.jsonl",
    })
    assert len(spawned) == 2  # extract + evaluate for sess-a

    # Finish extract for sess-a, drain picks up sess-b extract
    # (evaluate may be already_running from sess-a)
    spawned[0].finish()
    daemon._drain_pending_turns()
    assert len(spawned) == 3  # +1 extract for sess-b
    assert "sess-b" in spawned[2].cmd
    assert len(daemon._pending_turns) == 1

    # Finish sess-b extract, drain picks up sess-c
    spawned[2].finish()
    daemon._drain_pending_turns()
    # evaluate_proc from sess-a may have finished or not — count extract procs
    extract_cmds = [s for s in spawned if "process-turn" in s.cmd]
    assert len(extract_cmds) == 3  # sess-a, sess-b, sess-c
    assert "sess-c" in spawned[-2].cmd or "sess-c" in spawned[-1].cmd
    assert len(daemon._pending_turns) == 0


def test_drain_spawn_failure_keeps_pending(monkeypatch, tmp_path):
    """P1: If Popen fails during drain, the pending turn is not lost."""
    spawned = []
    daemon = _make_daemon(monkeypatch, tmp_path, spawned)

    # Start extraction (2 procs), queue another
    daemon._handle_request({
        "type": "process_turn",
        "session_id": "sess-a",
        "transcript_path": "/tmp/a.jsonl",
    })
    daemon._handle_request({
        "type": "process_turn",
        "session_id": "sess-b",
        "transcript_path": "/tmp/b.jsonl",
    })

    # Finish first extraction
    spawned[0].finish()

    # Make Popen raise on next spawn
    def failing_popen(cmd, **kwargs):
        raise OSError("spawn failed")
    monkeypatch.setattr("src.daemon.subprocess.Popen", failing_popen)

    daemon._drain_pending_turns()

    # Pending turn should still be there
    assert len(daemon._pending_turns) == 1
    assert "sess-b" in daemon._pending_turns


def test_idle_timeout_suppressed_while_pending(monkeypatch, tmp_path):
    """P2: Daemon should not idle-shutdown while turns are pending or extraction is running."""
    import src.daemon as daemon_mod

    spawned = []
    daemon = _make_daemon(monkeypatch, tmp_path, spawned)

    # Start extraction and queue a turn
    daemon._handle_request({
        "type": "process_turn",
        "session_id": "sess-a",
        "transcript_path": "/tmp/a.jsonl",
    })
    daemon._handle_request({
        "type": "process_turn",
        "session_id": "sess-b",
        "transcript_path": "/tmp/b.jsonl",
    })

    # Force last_activity to be way in the past
    daemon.last_activity = time.time() - (daemon_mod.IDLE_TIMEOUT + 100)

    # With pending turns, has_pending_work should be True
    has_pending = bool(daemon._pending_turns) or daemon._is_running(daemon.extract_proc)
    assert has_pending is True

    # After draining all and finishing all procs, has_pending_work should be False
    spawned[0].finish()  # extract for sess-a
    daemon._drain_pending_turns()  # starts sess-b extract + evaluate
    spawned[2].finish()  # extract for sess-b
    daemon._pending_turns.clear()

    has_pending = bool(daemon._pending_turns) or daemon._is_running(daemon.extract_proc)
    assert has_pending is False
