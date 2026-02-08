"""Engrammar search daemon — keeps model warm, auto-exits after idle timeout.

Started lazily on first hook call. Shuts down after 15 minutes of inactivity.
Hooks communicate via Unix socket for ~20ms latency instead of ~300ms cold start.
"""

import json
import os
import signal
import socket
import sys
import time

ENGRAMMAR_HOME = os.environ.get("ENGRAMMAR_HOME", os.path.expanduser("~/.engrammar"))
sys.path.insert(0, ENGRAMMAR_HOME)

SOCKET_PATH = os.path.join(ENGRAMMAR_HOME, ".daemon.sock")
PID_PATH = os.path.join(ENGRAMMAR_HOME, ".daemon.pid")
LOG_PATH = os.path.join(ENGRAMMAR_HOME, ".daemon.log")
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
            from engrammar.db import get_pinned_lessons
            from engrammar.environment import check_prerequisites, detect_environment

            env = detect_environment()
            pinned = get_pinned_lessons()
            matching = [p for p in pinned if check_prerequisites(p.get("prerequisites"), env)]
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
                if time.time() - self.last_activity > IDLE_TIMEOUT:
                    _log("Idle timeout reached, shutting down.")
                    break

                try:
                    conn, _ = server.accept()
                    self._handle_connection(conn)
                except socket.timeout:
                    continue
                except OSError:
                    break
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
