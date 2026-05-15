from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class ScheduledActions:
    heartbeat: bool
    daily_assessment: bool
    weekly_optimizer: bool


def scheduled_actions(now: datetime | None = None) -> ScheduledActions:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    daily_hour = _env_int("BOT_ASSESSOR_DAILY_UTC_HOUR", 6)
    weekly_day = _env_int("BOT_ASSESSOR_WEEKLY_UTC_DAY", 0)
    daily_enabled = _env_bool("BOT_ASSESSOR_RUN_DAILY_ASSESSMENT", True)
    optimizer_enabled = _env_bool("BOT_ASSESSOR_RUN_WEEKLY_OPTIMIZER", True)
    should_run_daily = daily_enabled and current.hour == daily_hour
    return ScheduledActions(
        heartbeat=True,
        daily_assessment=should_run_daily,
        weekly_optimizer=optimizer_enabled and should_run_daily and current.weekday() == weekly_day,
    )


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default