from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from bot_assessor.config import BotConfig
from bot_assessor.review import Recommendation


def build_safe_overlays(bot: BotConfig, recommendations: list[Recommendation], *, generated_at: datetime) -> list[dict[str, Any]]:
    if not bot.allow_parameter_overlays:
        return []
    allowed = set(bot.allowed_overlay_types)
    overlays: list[dict[str, Any]] = []
    for recommendation in recommendations:
        raw = recommendation.overlay
        if not raw or raw.get("type") not in allowed:
            continue
        overlay = dict(raw)
        overlay.setdefault("source", "bot-assessor")
        overlay.setdefault("reason", recommendation.title)
        overlay.setdefault("severity", recommendation.severity)
        overlay.setdefault("generated_at", generated_at.astimezone(timezone.utc).isoformat())
        ttl_hours = float(overlay.pop("ttl_hours", 72))
        overlay["expires_at"] = (generated_at.astimezone(timezone.utc) + timedelta(hours=ttl_hours)).isoformat()
        overlays.append(overlay)
    return overlays


def overlay_payload(bot: BotConfig, overlays: list[dict[str, Any]], *, generated_at: datetime) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "bot_id": bot.id,
        "bot_name": bot.name,
        "generated_at": generated_at.astimezone(timezone.utc).isoformat(),
        "safety_mode": "parameter_only",
        "enabled_for_bot": bool(bot.allow_parameter_overlays),
        "overlays": overlays,
    }