/**
 * panels/watchdog.js
 * Polls and renders real-time system health and watchdog telemetry:
 * GPU stats, LLM status badge, and container statuses (PostGIS, Redis).
 */

import { fetchWatchdogTelemetry, fetchHealthStatus } from "../api.js";

export function setWatchdogBadge(el, status) {
  if (!el) return;
  const s = String(status || "--").trim().toUpperCase();
  el.textContent = status || "--";
  if (s === "HEALTHY" || s === "ONLINE" || s === "UP") {
    el.style.background = "rgba(16, 185, 129, 0.2)";
    el.style.color = "#10b981";
    el.style.borderColor = "rgba(16, 185, 129, 0.4)";
  } else if (s === "WARNING" || s === "WARNING_OVERHEAT" || s.includes("STANDBY") || s === "DEGRADED") {
    el.style.background = "rgba(245, 158, 11, 0.2)";
    el.style.color = "#f59e0b";
    el.style.borderColor = "rgba(245, 158, 11, 0.4)";
  } else if (s === "DOWN" || s === "CRITICAL" || s === "ERROR" || s === "OFFLINE" || s === "UNHEALTHY") {
    el.style.background = "rgba(239, 68, 68, 0.2)";
    el.style.color = "#ef4444";
    el.style.borderColor = "rgba(239, 68, 68, 0.4)";
  } else {
    el.style.background = "rgba(107, 114, 128, 0.2)";
    el.style.color = "#9ca3af";
    el.style.borderColor = "rgba(107, 114, 128, 0.3)";
  }
}

export function setContainerStatusText(el, statusText) {
  if (!el) return;
  const s = statusText || "--";
  el.textContent = s;
  const lower = s.toLowerCase();
  if (lower.includes("unhealthy") || lower.includes("down") || lower.includes("fail") || lower.includes("exit")) {
    el.style.color = "#ef4444";
  } else if (lower.includes("healthy") || lower.startsWith("up")) {
    el.style.color = "#10b981";
  } else {
    el.style.color = "#9ca3af";
  }
}

export function resetWatchdogTelemetry(errorMessage = "Telemetri tidak dapat dimuat") {
  const errBanner = document.getElementById("watchdog-error-banner");
  if (errBanner) {
    if (errorMessage) {
      errBanner.textContent = errorMessage;
      errBanner.style.display = "block";
    } else {
      errBanner.textContent = "";
      errBanner.style.display = "none";
    }
  }

  const gpuName = document.getElementById("watchdog-gpu-name");
  if (gpuName) gpuName.textContent = "--";

  setWatchdogBadge(document.getElementById("watchdog-gpu-status"), "--");

  const vram = document.getElementById("watchdog-vram-usage");
  if (vram) vram.textContent = "--";

  const temp = document.getElementById("watchdog-gpu-temp");
  if (temp) temp.textContent = "--";

  setWatchdogBadge(document.getElementById("watchdog-ai-status"), "--");

  const aiModel = document.getElementById("watchdog-ai-model");
  if (aiModel) aiModel.textContent = "--";

  setContainerStatusText(document.getElementById("watchdog-postgis-status"), "--");
  setContainerStatusText(document.getElementById("watchdog-redis-status"), "--");
}

export async function loadHealthStatus() {
  try {
    const data = await fetchHealthStatus();
    if (!data) return;
    const model = data.llm_model || "LLM tidak aktif";
    const modelPill = document.getElementById("nav-llm-model");
    const chatTag = document.getElementById("chat-model-tag");
    const dot = document.getElementById("nav-llm-dot");
    const chatDot = document.getElementById("chat-header-dot");

    if (modelPill) modelPill.textContent = model;
    if (chatTag) chatTag.textContent = model;
    if (dot) {
      if (model === "LLM tidak aktif") {
        dot.style.background = "#6b7280";
        dot.style.boxShadow = "none";
      } else {
        dot.style.background = "#a855f7";
        dot.style.boxShadow = "0 0 8px #a855f7";
      }
    }
    if (chatDot) {
      if (model === "LLM tidak aktif") {
        chatDot.style.background = "#6b7280";
      } else {
        chatDot.style.background = "#a855f7";
      }
    }
  } catch (err) {
    console.warn("Health check error:", err);
  }
}

export async function loadWatchdogTelemetry() {
  try {
    const data = await fetchWatchdogTelemetry();
    if (!data || typeof data !== "object") {
      resetWatchdogTelemetry("Telemetri tidak dapat dimuat");
      return;
    }

    const errBanner = document.getElementById("watchdog-error-banner");
    if (errBanner) {
      errBanner.textContent = "";
      errBanner.style.display = "none";
    }

    const gpu = data.gpu || {};
    const gpuNameEl = document.getElementById("watchdog-gpu-name");
    if (gpuNameEl) {
      gpuNameEl.textContent = gpu.gpu_name || "tidak tersedia";
    }
    setWatchdogBadge(document.getElementById("watchdog-gpu-status"), gpu.status || "--");

    const vramEl = document.getElementById("watchdog-vram-usage");
    if (vramEl) {
      if (gpu.vram_total_mb && gpu.vram_total_mb > 0) {
        vramEl.textContent = `${gpu.vram_used_mb ?? 0} / ${gpu.vram_total_mb} MB (${gpu.vram_percent ?? 0}%)`;
      } else {
        vramEl.textContent = "--";
      }
    }

    const tempEl = document.getElementById("watchdog-gpu-temp");
    if (tempEl) {
      if (gpu.temperature_celsius != null && gpu.power_watts != null && gpu.status !== "UNAVAILABLE") {
        tempEl.textContent = `${gpu.temperature_celsius}°C • ${gpu.power_watts}W`;
      } else {
        tempEl.textContent = "--";
      }
    }

    const ai = data.ai_engine || {};
    setWatchdogBadge(document.getElementById("watchdog-ai-status"), ai.status || "--");
    const aiModelEl = document.getElementById("watchdog-ai-model");
    if (aiModelEl) {
      aiModelEl.textContent = ai.loaded_model || "--";
    }

    const containers = data.containers || {};
    setContainerStatusText(
      document.getElementById("watchdog-postgis-status"),
      containers.postgis || "--"
    );
    setContainerStatusText(
      document.getElementById("watchdog-redis-status"),
      containers.redis || "--"
    );
  } catch (err) {
    console.warn("Watchdog poller warning:", err);
    resetWatchdogTelemetry("Telemetri tidak dapat dimuat");
  }
}
