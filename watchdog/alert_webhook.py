"""
Autonomous Watchdog Webhook Notifier.
Sends one-way formatted telemetry alerts for Discord / Telegram webhooks.
Strictly non-interactive, read-only notification channel (disabled when no URL is configured).
"""

import os
import json
import logging
import urllib.request
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class WatchdogWebhookNotifier:
    def __init__(self):
        self.discord_webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "")
        self.telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID", "")

    def send_discord_alert(
        self,
        title: str,
        description: str,
        severity: str = "HIGH",
        fields: Optional[Dict[str, str]] = None
    ) -> bool:
        """Sends rich embed to Discord webhook channel."""
        if not self.discord_webhook_url:
            logger.info(f"[SIMULATED WEBHOOK ALERT] {severity} - {title}: {description}")
            return False

        color_map = {
            "LOW": 3066993,     # Green
            "MEDIUM": 15844367, # Yellow/Gold
            "HIGH": 15105570,   # Orange
            "CRITICAL": 15158332# Red
        }

        embed_fields = []
        if fields:
            for k, v in fields.items():
                embed_fields.append({"name": k, "value": str(v), "inline": True})

        payload = {
            "username": "District Resource Profiling Watchdog",
            "avatar_url": "https://img.icons8.com/color/96/shield.png",
            "embeds": [
                {
                    "title": f"[{severity}] {title}",
                    "description": description,
                    "color": color_map.get(severity.upper(), 15105570),
                    "fields": embed_fields,
                    "footer": {"text": "District Resource Profiling Read-Only Observability"}
                }
            ]
        }

        try:
            req = urllib.request.Request(
                self.discord_webhook_url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status == 204
        except Exception as e:
            logger.warning(f"Failed to deliver Discord webhook: {e}")
            return False
