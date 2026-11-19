"""
System test shared fixtures.
Starts a live uvicorn server from the current working tree on an ephemeral free port.
Ensures system tests never target stale containers on :18000.
"""

import os
import socket
import subprocess
import sys
import time
import httpx
import pytest


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def live_server_url():
    """
    Starts uvicorn on an ephemeral free port for the system test session.
    Guarantees tests run against the current working tree code.
    Terminates cleanly in session teardown.
    """
    port = find_free_port()
    env = os.environ.copy()
    env["PYTHONPATH"] = "."
    if "AUTH_JWT_SECRET" not in env:
        env["AUTH_JWT_SECRET"] = "system-test-session-secret-123456"

    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "backend.app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    url = f"http://127.0.0.1:{port}"
    healthy = False

    for _ in range(40):
        try:
            with httpx.Client(timeout=1.5) as client:
                res = client.get(f"{url}/health")
                if res.status_code == 200:
                    healthy = True
                    break
        except Exception:
            time.sleep(0.25)

    if not healthy:
        proc.terminate()
        proc.wait()
        raise RuntimeError(f"Live uvicorn failed to start on port {port} within 10 seconds.")

    yield url

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
