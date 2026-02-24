"""Engrammar search daemon — keeps model warm, auto-exits after idle timeout.

Started lazily on first hook call. Shuts down after 15 minutes of inactivity.
Hooks communicate via Unix socket for ~20ms latency instead of ~300ms cold start.
"""

import json
import os
import signal
import socket
import subprocess
import sys
import time

ENGRAMMAR_HOME = os.environ.get("ENGRAMMAR_HOME", os.path.expanduser("~/.engrammar"))
sys.path.insert(0, ENGRAMMAR_HOME)

SOCKET_PATH = os.path.join(ENGRAMMAR_HOME, ".daemon.sock")
PID_PATH = os.path.join(ENGRAMMAR_HOME, ".daemon.pid")
LOG_PATH = os.path.join(ENGRAMMAR_HOME, ".daemon.log")
VENV_PYTHON = os.path.join(ENGRAMMAR_HOME, "venv", "bin", "python")
CLI_PATH = os.path.join(ENGRAMMAR_HOME, "cli.py")
IDLE_TIMEOUT = 15 * 60  # 15 minutes


def _log(msg):
    try:
        with open(LOG_PATH, "a") as f:
            ts = time.strftime("%H:%M:%S")
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


class EngrammarDaemon:
    def __init__(self):
        self.last_activity = time.time()
        self.start_time = time.time()
        self.running = True
        self.extract_proc = None
        self.evaluate_proc = None
        self._pending_turns = {}  # {session_id: transcript_path} — coalesced per session

    @staticmethod
    def _is_running(proc):
        return proc is not None and proc.poll() is None

    def _spawn_cli_job(self, job_name, cli_args):
        """Start a CLI background job if not already running."""
        proc_attr = f"{job_name}_proc"
        proc = getattr(self, proc_attr)

        if self._is_running(proc):
            return {"started": False, "status": "already_running", "pid": proc.pid}

        env = os.environ.copy()
        env["ENGRAMMAR_INTERNAL_RUN"] = "1"

        with open(LOG_PATH, "a") as log:
            new_proc = subprocess.Popen(
                [VENV_PYTHON, CLI_PATH] + cli_args,
                stdout=log,
                stderr=log,
                start_new_session=True,
                env=env,
            )

        setattr(self, proc_attr, new_proc)
        _log(f"Started {job_name} job (pid={new_proc.pid})")
        return {"started": True, "status": "started", "pid": new_proc.pid}

    def _drain_pending_turns(self):
        """If extraction finished and turns are pending, start the next one."""
        if not self._pending_turns:
            return
        if self._is_running(self.extract_proc):
            return

        # Peek first pending session (dict preserves insertion order)
        session_id, transcript_path = next(iter(self._pending_turns.items()))

        try:
            result = self._spawn_cli_job("extract", [
                "process-turn", "--session", session_id,
                "--transcript", transcript_path,
            ])
            # Only remove after successful spawn
            del self._pending_turns[session_id]
            self.last_activity = time.time()
            _log(f"Drained turn for {session_id[:12]} (remaining: {len(self._pending_turns)}, {result.get('status')})")
        except Exception as e:
            _log(f"Drain spawn failed for {session_id[:12]}: {e}")

    def _warm_up(self):
        """Pre-load the embedding model so first search is fast."""
        from engrammar.embeddings import get_model

        _log("Warming up model...")
        t0 = time.perf_counter()
        get_model()
        t1 = time.perf_counter()
        _log(f"Model ready in {(t1-t0)*1000:.0f}ms")

    def _handle_request(self, data):
        """Process a request and return response dict."""
        self.last_activity = time.time()
        req_type = data.get("type", "")

        if req_type == "search":
            from engrammar.search import search

            results = search(
                data.get("query", ""),
                category_filter=data.get("category_filter"),
                top_k=data.get("top_k"),
            )
            return {"results": _serialize(results)}

        elif req_type == "tool_context":
            from engrammar.search import search_for_tool_context

            results = search_for_tool_context(
                data.get("tool_name", ""),
                data.get("tool_input", {}),
            )
            return {"results": _serialize(results)}

        elif req_type == "pinned":
            from engrammar.db import get_pinned_engrams, get_tag_relevance_with_evidence
            from engrammar.environment import check_structural_prerequisites, detect_environment

            env = detect_environment()
            env_tags = env.get("tags", [])
            pinned = get_pinned_engrams()
            matching = []
            for p in pinned:
                if not check_structural_prerequisites(p.get("prerequisites"), env):
                    continue
                if env_tags:
                    avg_score, total_evals = get_tag_relevance_with_evidence(p["id"], env_tags)
                    if total_evals >= 3 and avg_score < -0.1:
                        continue
                matching.append(p)
            return {"results": _serialize(matching)}

        elif req_type == "ping":
            return {
                "status": "ok",
                "uptime": round(time.time() - self.start_time, 1),
                "idle": round(time.time() - self.last_activity, 1),
            }

        elif req_type == "shutdown":
            self.running = False
            return {"status": "shutting_down"}

        elif req_type == "process_turn":
            session_id = data.get("session_id")
            transcript_path = data.get("transcript_path")
            if not session_id or not transcript_path:
                return {"error": "missing session_id or transcript_path"}

            # Try to start immediately; if busy, queue for later
            if self._is_running(self.extract_proc):
                self._pending_turns[session_id] = transcript_path
                _log(f"Queued turn for {session_id[:12]} (pending: {len(self._pending_turns)})")
                return {"status": "queued", "pending": len(self._pending_turns)}

            result = self._spawn_cli_job("extract", [
                "process-turn", "--session", session_id,
                "--transcript", transcript_path,
            ])
            return {"status": "ok", "job": result}

        elif req_type == "run_maintenance":
            extract = self._spawn_cli_job("extract", ["extract"])
            evaluate_args = ["evaluate"]
            limit = data.get("evaluate_limit")
            if isinstance(limit, int) and limit > 0:
                evaluate_args.extend(["--limit", str(limit)])
            evaluate = self._spawn_cli_job("evaluate", evaluate_args)
            return {"status": "ok", "extract": extract, "evaluate": evaluate}

        return {"error": f"unknown request type: {req_type}"}

    def _handle_connection(self, conn):
        """Handle a single client connection."""
        try:
            data = b""
            while True:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                data += chunk
                if b"\n" in data:
                    break

            if data:
                request = json.loads(data.decode().strip())
                response = self._handle_request(request)
                conn.sendall(json.dumps(response).encode() + b"\n")
        except Exception as e:
            _log(f"Error handling connection: {e}")
            try:
                conn.sendall(json.dumps({"error": str(e)}).encode() + b"\n")
            except Exception:
                pass
        finally:
            conn.close()

    def run(self):
        """Main daemon loop."""
        # Check if another daemon is already running
        if os.path.exists(SOCKET_PATH):
            try:
                test = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                test.connect(SOCKET_PATH)
                test.close()
                _log("Another daemon is already running, exiting.")
                return
            except (ConnectionRefusedError, OSError):
                os.unlink(SOCKET_PATH)

        # Write PID
        with open(PID_PATH, "w") as f:
            f.write(str(os.getpid()))

        # Warm up embedding model
        self._warm_up()

        # Create socket
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(SOCKET_PATH)
        server.listen(5)
        server.settimeout(5.0)  # Check idle every 5 seconds

        _log(f"Daemon started (pid={os.getpid()}, idle_timeout={IDLE_TIMEOUT}s)")

        def cleanup(signum=None, frame=None):
            self.running = False

        signal.signal(signal.SIGTERM, cleanup)
        signal.signal(signal.SIGINT, cleanup)

        try:
            while self.running:
                has_pending_work = (
                    self._pending_turns
                    or self._is_running(self.extract_proc)
                )
                if not has_pending_work and time.time() - self.last_activity > IDLE_TIMEOUT:
                    _log("Idle timeout reached, shutting down.")
                    break

                try:
                    conn, _ = server.accept()
                    self._handle_connection(conn)
                except socket.timeout:
                    self._drain_pending_turns()
                    continue
                except OSError:
                    break
                self._drain_pending_turns()
        finally:
            server.close()
            for path in (SOCKET_PATH, PID_PATH):
                if os.path.exists(path):
                    try:
                        os.unlink(path)
                    except OSError:
                        pass
            _log("Daemon stopped.")


def _serialize(results):
    """Convert sqlite Row objects to plain dicts for JSON serialization."""
    serialized = []
    for r in results:
        d = dict(r) if hasattr(r, "keys") else r
        serialized.append(d)
    return serialized


def main():
    daemon = EngrammarDaemon()
    daemon.run()


if __name__ == "__main__":
    main()
