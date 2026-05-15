from datetime import datetime, timezone

from bot_assessor.scheduler import scheduled_actions


def test_scheduler_sends_heartbeat_every_run() -> None:
    actions = scheduled_actions(datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc))

    assert actions.heartbeat is True
    assert actions.daily_assessment is False
    assert actions.weekly_optimizer is False


def test_scheduler_runs_daily_at_configured_hour() -> None:
    actions = scheduled_actions(datetime(2026, 5, 15, 6, 0, tzinfo=timezone.utc))

    assert actions.heartbeat is True
    assert actions.daily_assessment is True
    assert actions.weekly_optimizer is False


def test_scheduler_runs_weekly_optimizer_on_monday_daily_window() -> None:
    actions = scheduled_actions(datetime(2026, 5, 18, 6, 0, tzinfo=timezone.utc))

    assert actions.heartbeat is True
    assert actions.daily_assessment is True
    assert actions.weekly_optimizer is True