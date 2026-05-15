from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from bot_assessor.config import BotConfig
from bot_assessor.review import Recommendation


def build_railway_variable_plan(
    bot: BotConfig,
    recommendations: list[Recommendation],
    overlays: list[dict[str, Any]],
    *,
    generated_at: datetime,
) -> dict[str, Any]:
    allowed = set(bot.managed_railway_variables)
    plan: dict[str, Any] = {
        "schema_version": "1.0",
        "bot_id": bot.id,
        "bot_name": bot.name,
        "railway_service": bot.railway_service,
        "railway_environment": bot.railway_environment,
        "generated_at": generated_at.astimezone(timezone.utc).isoformat(),
        "mode": "proposal_only",
        "approval_required": True,
        "allowed_variables": sorted(allowed),
        "proposals": [],
        "blocked": [],
    }
    if not allowed:
        return plan

    recommendations_by_title = {item.title: item for item in recommendations}
    for overlay in overlays:
        mapping_key = _mapping_key(overlay)
        variable = bot.railway_variable_mappings.get(mapping_key) or bot.railway_variable_mappings.get(str(overlay.get("type", "")))
        if not variable:
            plan["blocked"].append({"overlay": _safe_overlay(overlay), "reason": f"No railway_variable_mappings entry for {mapping_key}"})
            continue
        if variable not in allowed:
            plan["blocked"].append({"overlay": _safe_overlay(overlay), "variable": variable, "reason": "Variable is not in managed_railway_variables"})
            continue
        value = _proposed_value(overlay)
        if value is None:
            plan["blocked"].append({"overlay": _safe_overlay(overlay), "variable": variable, "reason": "Overlay does not contain a concrete value"})
            continue
        recommendation = recommendations_by_title.get(str(overlay.get("reason", "")))
        plan["proposals"].append(
            {
                "action": "set",
                "variable": variable,
                "value_preview": _preview(value),
                "reason": overlay.get("reason") or (recommendation.title if recommendation else "bot-assessor recommendation"),
                "source_overlay": _safe_overlay(overlay),
                "requires_manual_approval": True,
            }
        )
    return plan


def _mapping_key(overlay: dict[str, Any]) -> str:
    overlay_type = str(overlay.get("type", ""))
    target = str(overlay.get("target", "global"))
    return f"{overlay_type}:{target}"


def _proposed_value(overlay: dict[str, Any]) -> Any:
    if "value" in overlay:
        return overlay["value"]
    if overlay.get("type") == "threshold_adjustment":
        direction = overlay.get("direction")
        max_step = overlay.get("max_step")
        if direction and max_step is not None:
            return {"direction": direction, "max_step": max_step}
    return None


def _safe_overlay(overlay: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in overlay.items() if key not in {"secret", "token", "password"}}


def _preview(value: Any) -> str:
    text = str(value)
    if len(text) <= 120:
        return text
    return text[:117] + "..."