"""Client for communicating with the Engrammar daemon.

Handles lazy daemon startup and automatic reconnection.
"""

import json
import os
import socket
import subprocess
import time

ENGRAMMAR_HOME = os.environ.get("ENGRAMMAR_HOME", os.path.expanduser("~/.engrammar"))
SOCKET_PATH = os.path.join(ENGRAMMAR_HOME, ".daemon.sock")
DAEMON_MODULE = os.path.join(ENGRAMMAR_HOME, "engrammar", "daemon.py")
VENV_PYTHON = os.path.join(ENGRAMMAR_HOME, "venv", "bin", "python")
LOG_PATH = os.path.join(ENGRAMMAR_HOME, ".daemon.log")


def _connect(timeout=5.0):
    """Connect to daemon socket. Raises on failure."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    sock.connect(SOCKET_PATH)
    return sock


def _start_daemon():
    """Start daemon in background, wait for it to be ready."""
    with open(LOG_PATH, "a") as log:
        subprocess.Popen(
            [VENV_PYTHON, DAEMON_MODULE],
            stdout=log,
            stderr=log,
            start_new_session=True,
        )

    # Poll for socket to appear (model warm-up takes ~200ms)
    for _ in range(30):  # Up to 3 seconds
        time.sleep(0.1)
        if os.path.exists(SOCKET_PATH):
            try:
                return _connect()
            except (ConnectionRefusedError, OSError):
                continue

    return None


def _start_daemon_background():
    """Start daemon without waiting. Used by session_start to avoid blocking."""
    with open(LOG_PATH, "a") as log:
        subprocess.Popen(
            [VENV_PYTHON, DAEMON_MODULE],
            stdout=log,
            stderr=log,
            start_new_session=True,
        )


def send_request(request, timeout=5.0):
    """Send a request to the daemon, starting it if needed.

    Returns the response dict, or None on failure.
    """
    sock = None

    # Try connecting to existing daemon
    try:
        sock = _connect(timeout=timeout)
    except (ConnectionRefusedError, FileNotFoundError, OSError):
        # Clean up stale socket if needed
        if os.path.exists(SOCKET_PATH):
            try:
                os.unlink(SOCKET_PATH)
            except OSError:
                pass
        # Start daemon and wait for it
        sock = _start_daemon()
        if sock is None:
            return None

    try:
        sock.sendall(json.dumps(request).encode() + b"\n")

        data = b""
        while True:
            chunk = sock.recv(8192)
            if not chunk:
                break
            data += chunk
            if b"\n" in data:
                break

        if data:
            return json.loads(data.decode().strip())
        return None
    except Exception:
        return None
    finally:
        if sock:
            sock.close()
