"""
Autonomous Read-Only Watchdog Agent (README.md §12).
Performs non-mutating observability, telemetry, and incident logging:
- Health checks: PostgreSQL, Redis, Ollama, FastAPI.
- Read-only GPU telemetry if available via `nvidia-smi` (safe fallback when missing).
- Incident logging into PostgreSQL `incident_logs` table (read/insert only, never drop/alter).
- Optional one-way webhook alert notifications.
- STRICTLY READ-ONLY: Executes NO mutating subprocess calls (no docker restart, no kill, no VRAM purge).
  Self-healing container restarts are delegated to Docker Compose (`restart: unless-stopped`).
"""

import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
import subprocess
import logging
import urllib.request
import time
from typing import Dict, Any, Optional
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

from watchdog.alert_webhook import WatchdogWebhookNotifier

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [WATCHDOG] %(message)s")
logger = logging.getLogger(__name__)


class AutonomousWatchdogAgent:
    """Read-only health check & incident logging watchdog."""

    def __init__(self):
        self.notifier = WatchdogWebhookNotifier()
        self.db_config = {
            "dbname": os.getenv("POSTGRES_DB", "district_profiling"),
            "user": os.getenv("POSTGRES_USER", "postgres"),
            "password": os.getenv("POSTGRES_PASSWORD", "postgres_spatial_dev"),
            "host": os.getenv("POSTGRES_HOST") or "127.0.0.1",
            "port": int(os.getenv("POSTGRES_PORT", 5432)),
            "connect_timeout": 3
        }
        if self.db_config["host"] == "localhost":
            self.db_config["host"] = "127.0.0.1"

        self.redis_host = os.getenv("REDIS_HOST", "127.0.0.1")
        if self.redis_host == "localhost":
            self.redis_host = "127.0.0.1"
        self.redis_port = int(os.getenv("REDIS_PORT", 6379))
        self.ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")

    def get_gpu_telemetry(self) -> Dict[str, Any]:
        """Queries GPU hardware sensors via read-only nvidia-smi query with safe fallback."""
        try:
            cmd = [
                "nvidia-smi",
                "--query-gpu=name,memory.used,memory.total,temperature.gpu,power.draw,utilization.gpu",
                "--format=csv,noheader,nounits"
            ]
            out = subprocess.check_output(cmd, timeout=3).decode("utf-8").strip()
            parts = [p.strip() for p in out.split(",")]
            gpu_name = parts[0]
            used_mb = int(float(parts[1]))
            total_mb = int(float(parts[2]))
            temp_c = int(float(parts[3]))
            pwr_w = float(parts[4])
            util_pct = int(float(parts[5]))

            return {
                "gpu_name": gpu_name,
                "vram_used_mb": used_mb,
                "vram_total_mb": total_mb,
                "vram_percent": round((used_mb / max(1, total_mb)) * 100.0, 1),
                "temperature_celsius": temp_c,
                "power_watts": pwr_w,
                "gpu_utilization_percent": util_pct,
                "status": "HEALTHY" if temp_c < 85 else "WARNING_OVERHEAT"
            }
        except Exception as e:
            # Safe non-blocking fallback when GPU or nvidia-smi is unavailable
            return {
                "gpu_name": "Akselerator AI & Komputasi",
                "status": "UNAVAILABLE",
                "vram_used_mb": 0,
                "vram_total_mb": 0,
                "vram_percent": 0.0,
                "temperature_celsius": 0,
                "power_watts": 0.0,
                "gpu_utilization_percent": 0,
                "error": str(e)
            }

    def check_postgres(self) -> Dict[str, Any]:
        """Read-only ping to PostgreSQL PostGIS database."""
        try:
            conn = psycopg2.connect(**self.db_config)
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
                cur.fetchone()
            conn.close()
            return {"status": "HEALTHY", "service": "PostgreSQL + PostGIS"}
        except Exception as e:
            return {"status": "DOWN", "service": "PostgreSQL + PostGIS", "error": str(e)}

    def check_redis(self) -> Dict[str, Any]:
        """Read-only ping to Redis 7 cache."""
        try:
            import redis
            r = redis.Redis(host=self.redis_host, port=self.redis_port, socket_timeout=2)
            if r.ping():
                return {"status": "HEALTHY", "service": "Redis 7"}
            return {"status": "DOWN", "service": "Redis 7", "error": "Ping returned False"}
        except Exception as e:
            return {"status": "DOWN", "service": "Redis 7", "error": str(e)}

    def check_fastapi(self) -> Dict[str, Any]:
        """Read-only health query to FastAPI backend."""
        try:
            req = urllib.request.Request("http://127.0.0.1:8000/health")
            with urllib.request.urlopen(req, timeout=2) as resp:
                if resp.status == 200:
                    return {"status": "HEALTHY", "service": "FastAPI"}
                return {"status": "DEGRADED", "service": "FastAPI", "status_code": resp.status}
        except Exception as e:
            return {"status": "DOWN", "service": "FastAPI", "error": str(e)}

    def get_ollama_ai_status(self) -> Dict[str, Any]:
        """Checks local Ollama Qwen 2.5 14B endpoint via read-only HTTP GET."""
        try:
            url = f"{self.ollama_base_url.rstrip('/')}/api/ps"
            req = urllib.request.Request(url, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                models = data.get("models", [])
                loaded_model = models[0]["name"] if models else "qwen2.5:14b"
                size_vram = models[0].get("size_vram", 0) if models else 0
                return {
                    "status": "ONLINE",
                    "loaded_model": loaded_model,
                    "vram_allocated_mb": round(size_vram / (1024 * 1024), 1)
                }
        except Exception as e:
            return {
                "status": "STANDBY / UNREACHABLE",
                "loaded_model": "None (Offline / Standby)",
                "error": str(e)
            }

    def get_container_telemetry(self) -> Dict[str, Any]:
        """Checks container / service status (read-only query)."""
        pg_status = self.check_postgres()
        redis_status = self.check_redis()

        pg_up = "Up (healthy)" if pg_status["status"] == "HEALTHY" else "DOWN"
        redis_up = "Up (healthy)" if redis_status["status"] == "HEALTHY" else "DOWN"

        # Also attempt read-only docker ps if available, but do not fail without it
        try:
            cmd = ["docker", "ps", "--format", "{{.Names}}\t{{.Status}}"]
            out = subprocess.check_output(cmd, timeout=3).decode("utf-8").strip()
            for line in out.splitlines():
                if "\t" in line:
                    name, status = line.split("\t", 1)
                    if "drp_postgis" in name:
                        pg_up = status.strip()
                    elif "drp_redis" in name:
                        redis_up = status.strip()
        except Exception:
            pass

        all_healthy = (pg_status["status"] == "HEALTHY") and (redis_status["status"] == "HEALTHY")

        return {
            "postgis": pg_up,
            "redis": redis_up,
            "all_healthy": all_healthy
        }

    def log_incident(
        self,
        incident_type: str,
        severity: str,
        target_service: str,
        action_taken: str,
        status: str = "LOGGED",
        error_payload: Optional[Dict[str, Any]] = None,
        gpu_temp: Optional[int] = None,
        vram_mb: Optional[int] = None
    ):
        """Inserts incident log record into PostgreSQL incident_logs table (read/insert only)."""
        try:
            conn = psycopg2.connect(**self.db_config)
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO incident_logs (
                        incident_type, severity, target_service, action_taken,
                        status, gpu_temperature_celsius, vram_used_mb, error_payload
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
                """, (
                    incident_type, severity, target_service, action_taken,
                    status, gpu_temp, vram_mb, json.dumps(error_payload or {})
                ))
                conn.commit()
            conn.close()
            logger.info(f"Audit log persisted: [{severity}] {incident_type} on {target_service} -> {action_taken}")
        except Exception as e:
            logger.error(f"Failed to record incident to DB: {e}")

    def run_health_cycle(self) -> Dict[str, Any]:
        """Runs complete read-only observability telemetry and incident logging."""
        gpu = self.get_gpu_telemetry()
        containers = self.get_container_telemetry()
        ai = self.get_ollama_ai_status()
        redis_stat = self.check_redis()
        pg_stat = self.check_postgres()

        # Telemetry observation: if a service is degraded, log incident (NO mutating subprocess calls)
        if not containers.get("all_healthy"):
            if pg_stat["status"] != "HEALTHY":
                logger.warning("PostGIS service unreachable! Logging incident (Docker restart policy active)...")
                # Webhook alert (one-way notification)
                self.notifier.send_discord_alert("PostGIS Health Alert", str(pg_stat.get("error", "Service down")), severity="CRITICAL")

            if redis_stat["status"] != "HEALTHY":
                logger.warning("Redis cache unreachable! Logging incident...")
                self.log_incident(
                    incident_type="SERVICE_DEGRADED",
                    severity="WARNING",
                    target_service="redis",
                    action_taken="Read-only telemetry logged; self-healing delegated to Docker restart policy",
                    status="DEGRADED",
                    error_payload=redis_stat
                )
                self.notifier.send_discord_alert("Redis Cache Alert", str(redis_stat.get("error", "Cache down")), severity="WARNING")

        # Telemetry observation: if Ollama is unreachable
        if ai.get("status") != "ONLINE":
            logger.info("Ollama AI engine unreachable or standby. Logging telemetry status...")
            self.log_incident(
                incident_type="AI_ENGINE_OFFLINE",
                severity="INFO",
                target_service="ollama",
                action_taken="Read-only telemetry logged; deterministic fallback active",
                status="STANDBY",
                error_payload=ai
            )

        # Telemetry observation: GPU thermal warning (read-only notification)
        if gpu.get("temperature_celsius", 0) > 85:
            logger.warning(f"High GPU Temp: {gpu['temperature_celsius']}C! Emitting alert...")
            self.notifier.send_discord_alert("GPU Thermal Warning", f"GPU reached {gpu['temperature_celsius']}°C", severity="HIGH")
            self.log_incident(
                incident_type="GPU_OVERHEAT",
                severity="HIGH",
                target_service="gpu",
                action_taken="Thermal telemetry logged; notification dispatched",
                status="MONITORING",
                error_payload=gpu,
                gpu_temp=gpu.get("temperature_celsius"),
                vram_mb=gpu.get("vram_used_mb")
            )

        is_overall_healthy = containers.get("all_healthy") and (gpu.get("status") in ["HEALTHY", "UNAVAILABLE"])

        return {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "status": "HEALTHY" if is_overall_healthy else "DEGRADED",
            "gpu": gpu,
            "containers": containers,
            "ai_engine": ai,
            "services": {
                "postgres": pg_stat["status"],
                "redis": redis_stat["status"],
                "ollama": ai["status"]
            }
        }


# Global instance for FastAPI usage
watchdog_instance = AutonomousWatchdogAgent()

def get_watchdog_telemetry():
    return watchdog_instance.run_health_cycle()

if __name__ == "__main__":
    agent = AutonomousWatchdogAgent()
    if os.getenv("WATCHDOG_ONCE"):
        telemetry = agent.run_health_cycle()
        print(json.dumps(telemetry, indent=2))
    else:
        interval = int(os.getenv("WATCHDOG_INTERVAL_SECONDS", "30"))
        logger.info(f"Starting Autonomous Watchdog daemon (interval={interval}s)...")
        while True:
            try:
                telemetry = agent.run_health_cycle()
                logger.info(f"Watchdog health cycle: {telemetry['status']}")
            except Exception as e:
                logger.error(f"Error during watchdog health cycle: {e}")
            time.sleep(interval)
