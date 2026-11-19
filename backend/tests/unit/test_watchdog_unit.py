"""
Unit Tests for Read-Only Watchdog Agent & Observability (README.revised.md §12).
Verifies:
1. Safe fallback when GPU or nvidia-smi is missing.
2. Incident logging when Ollama AI engine is down, with 0 subprocess restart commands.
3. Incident logging when Redis is down, with 0 subprocess restart commands.
4. Webhook notifier and check methods.
"""

import pytest
from unittest.mock import patch, MagicMock

from watchdog.agent import AutonomousWatchdogAgent
from watchdog.alert_webhook import WatchdogWebhookNotifier

pytestmark = pytest.mark.unit


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


def test_watchdog_ollama_down_logs_incident_no_subprocess():
    """
    Verifies that when Ollama is unreachable, watchdog logs an incident
    and executes ZERO mutating subprocess commands (no restart, no kill).
    """
    agent = AutonomousWatchdogAgent()

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

        assert telemetry["ai_engine"]["status"] == "STANDBY / UNREACHABLE"

        mock_log.assert_any_call(
            incident_type="AI_ENGINE_OFFLINE",
            severity="INFO",
            target_service="ollama",
            action_taken="Read-only telemetry logged; deterministic fallback active",
            status="STANDBY",
            error_payload=telemetry["ai_engine"]
        )

        for call_item in mock_subproc_run.call_args_list:
            cmd = call_item[0][0] if call_item[0] else []
            cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
            assert "restart" not in cmd_str, f"Mutating restart called: {cmd_str}"
            assert "kill" not in cmd_str, f"Mutating kill called: {cmd_str}"
            assert "stop" not in cmd_str, f"Mutating stop called: {cmd_str}"
        mock_subproc_call.assert_not_called()


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

        assert telemetry["status"] == "DEGRADED"
        assert telemetry["services"]["redis"] == "DOWN"

        mock_log.assert_any_call(
            incident_type="SERVICE_DEGRADED",
            severity="WARNING",
            target_service="redis",
            action_taken="Read-only telemetry logged; self-healing delegated to Docker restart policy",
            status="DEGRADED",
            error_payload={"status": "DOWN", "service": "Redis 7", "error": "Connection refused"}
        )

        for call_item in mock_subproc_run.call_args_list:
            cmd = call_item[0][0] if call_item[0] else []
            cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
            assert "restart" not in cmd_str, f"Mutating restart called: {cmd_str}"
            assert "kill" not in cmd_str, f"Mutating kill called: {cmd_str}"
            assert "stop" not in cmd_str, f"Mutating stop called: {cmd_str}"
        mock_subproc_call.assert_not_called()


def test_watchdog_check_methods_mocked():
    """Unit test for check_postgres, check_redis, check_fastapi error paths."""
    agent = AutonomousWatchdogAgent()

    with patch("psycopg2.connect", side_effect=Exception("DB down")):
        res_db = agent.check_postgres()
        assert res_db["status"] == "DOWN"

    with patch("redis.Redis", side_effect=Exception("Redis down")):
        res_redis = agent.check_redis()
        assert res_redis["status"] == "DOWN"

    with patch("urllib.request.urlopen", side_effect=Exception("FastAPI down")):
        res_api = agent.check_fastapi()
        assert res_api["status"] == "DOWN"


def test_watchdog_webhook_notifier_simulated():
    """Unit test for WatchdogWebhookNotifier without active webhook URL."""
    notifier = WatchdogWebhookNotifier()
    notifier.discord_webhook_url = ""
    res = notifier.send_discord_alert("Test Alert", "Test Description", "HIGH")
    assert res is False
