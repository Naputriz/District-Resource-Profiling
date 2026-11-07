"""
Unit Tests for Read-Only Watchdog Agent & Observability (README.md §12).
Verifies:
1. Safe fallback when GPU or nvidia-smi is missing.
2. Incident logging when Ollama AI engine is down, with 0 subprocess restart commands.
3. Incident logging when Redis is down, with 0 subprocess restart commands.
4. Watchdog HTTP endpoints are strictly read-only GET.
"""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from watchdog.agent import AutonomousWatchdogAgent
from backend.app.main import app

@pytest.mark.unit
def test_watchdog_gpu_missing_safe_fallback():
    """Verifies that missing nvidia-smi / GPU returns safe default telemetry without crashing."""
    agent = AutonomousWatchdogAgent()

    with patch("subprocess.check_output", side_effect=FileNotFoundError("nvidia-smi: command not found")):
        gpu = agent.get_gpu_telemetry()
        assert gpu["status"] == "UNAVAILABLE"
        assert gpu["vram_used_mb"] == 0
        assert gpu["vram_total_mb"] == 0
        assert gpu["temperature_celsius"] == 0
        assert "nvidia-smi" in gpu["error"]


@pytest.mark.unit
def test_watchdog_ollama_down_logs_incident_no_subprocess():
    """
    Verifies that when Ollama is unreachable, watchdog logs an incident
    and executes ZERO mutating subprocess commands (no restart, no kill).
    """
    agent = AutonomousWatchdogAgent()

    # Disallow any mutating subprocess calls
    mock_subproc_run = MagicMock()
    mock_subproc_call = MagicMock()

    with patch("urllib.request.urlopen", side_effect=Exception("Connection refused")), \
         patch.object(agent, "check_postgres", return_value={"status": "HEALTHY", "service": "PostgreSQL"}), \
         patch.object(agent, "check_redis", return_value={"status": "HEALTHY", "service": "Redis 7"}), \
         patch.object(agent, "check_fastapi", return_value={"status": "HEALTHY", "service": "FastAPI"}), \
         patch("subprocess.run", mock_subproc_run), \
         patch("subprocess.call", mock_subproc_call), \
         patch.object(agent, "log_incident") as mock_log:

        telemetry = agent.run_health_cycle()

        # Telemetry should capture standby/unreachable status
        assert telemetry["ai_engine"]["status"] == "STANDBY / UNREACHABLE"

        # Verify an incident was logged for Ollama being offline
        mock_log.assert_any_call(
            incident_type="AI_ENGINE_OFFLINE",
            severity="INFO",
            target_service="ollama",
            action_taken="Read-only telemetry logged; deterministic fallback active",
            status="STANDBY",
            error_payload=telemetry["ai_engine"]
        )

        # STRICT ASSERTION: Zero mutating subprocess commands were called (no restart/kill/stop)
        for call_item in mock_subproc_run.call_args_list:
            cmd = call_item[0][0] if call_item[0] else []
            cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
            assert "restart" not in cmd_str, f"Mutating restart called: {cmd_str}"
            assert "kill" not in cmd_str, f"Mutating kill called: {cmd_str}"
            assert "stop" not in cmd_str, f"Mutating stop called: {cmd_str}"
        mock_subproc_call.assert_not_called()


@pytest.mark.unit
def test_watchdog_redis_down_logs_incident_no_subprocess():
    """
    Verifies that when Redis is down, watchdog marks system DEGRADED,
    logs an incident, and executes ZERO subprocess commands to restart containers.
    """
    agent = AutonomousWatchdogAgent()

    mock_subproc_run = MagicMock()
    mock_subproc_call = MagicMock()

    with patch.object(agent, "check_redis", return_value={"status": "DOWN", "service": "Redis 7", "error": "Connection refused"}), \
         patch.object(agent, "check_postgres", return_value={"status": "HEALTHY", "service": "PostgreSQL"}), \
         patch.object(agent, "check_fastapi", return_value={"status": "HEALTHY", "service": "FastAPI"}), \
         patch.object(agent, "get_ollama_ai_status", return_value={"status": "ONLINE", "service": "Ollama"}), \
         patch("subprocess.run", mock_subproc_run), \
         patch("subprocess.call", mock_subproc_call), \
         patch.object(agent, "log_incident") as mock_log:

        telemetry = agent.run_health_cycle()

        # Overall status should reflect degradation
        assert telemetry["status"] == "DEGRADED"
        assert telemetry["services"]["redis"] == "DOWN"

        # Verify incident was logged
        mock_log.assert_any_call(
            incident_type="SERVICE_DEGRADED",
            severity="WARNING",
            target_service="redis",
            action_taken="Read-only telemetry logged; self-healing delegated to Docker restart policy",
            status="DEGRADED",
            error_payload={"status": "DOWN", "service": "Redis 7", "error": "Connection refused"}
        )

        # STRICT ASSERTION: Zero mutating subprocess commands were called (no restart/kill/stop)
        for call_item in mock_subproc_run.call_args_list:
            cmd = call_item[0][0] if call_item[0] else []
            cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
            assert "restart" not in cmd_str, f"Mutating restart called: {cmd_str}"
            assert "kill" not in cmd_str, f"Mutating kill called: {cmd_str}"
            assert "stop" not in cmd_str, f"Mutating stop called: {cmd_str}"
        mock_subproc_call.assert_not_called()


@pytest.mark.db
def test_watchdog_endpoints_read_only_get():
    """Verifies all exposed watchdog HTTP endpoints are read-only GET with no mutation endpoints."""
    from backend.app.core.db import init_db_pool
    init_db_pool()
    client = TestClient(app)

    # 1. Telemetry GET returns 200
    res_tel = client.get("/api/v1/watchdog/telemetry")
    assert res_tel.status_code == 200
    tel_data = res_tel.json()
    assert "status" in tel_data
    assert "gpu" in tel_data
    assert "containers" in tel_data

    # 2. Incidents GET returns 200
    res_inc = client.get("/api/v1/watchdog/incidents")
    assert res_inc.status_code == 200
    inc_data = res_inc.json()
    assert "incidents" in inc_data

    # 3. POST / PUT / DELETE on telemetry is 405 Method Not Allowed
    res_post = client.post("/api/v1/watchdog/telemetry", json={})
    assert res_post.status_code == 405

    # 4. Prohibited trigger-restart endpoints do not exist (404 Not Found or 405 Method Not Allowed)
    res_restart = client.post("/api/v1/watchdog/restart", json={})
    assert res_restart.status_code in [404, 405]
