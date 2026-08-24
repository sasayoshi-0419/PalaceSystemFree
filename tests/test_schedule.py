from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from palworld_discord_bot.config import RestartSchedule
from palworld_discord_bot.schedule import resolve_timezone, schedule_is_due


def test_unknown_timezone_has_windows_hint() -> None:
    try:
        resolve_timezone("Not/AZone")
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "tzdata" in str(exc)


def test_schedule_due_once_per_day() -> None:
    schedule = RestartSchedule(
        time="05:00",
        timezone="Asia/Tokyo",
        warn_seconds=120,
        message="restart",
    )
    now = datetime(2026, 8, 18, 5, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
    assert schedule_is_due(schedule, now=now, last_run_date=None)
    assert not schedule_is_due(schedule, now=now, last_run_date=now.date())


def test_schedule_uses_timezone() -> None:
    schedule = RestartSchedule(
        time="05:00",
        timezone="Asia/Tokyo",
        warn_seconds=60,
        message="restart",
    )
    utc_now = datetime(2026, 8, 17, 20, 0, tzinfo=timezone.utc)
    assert schedule_is_due(schedule, now=utc_now, last_run_date=None)
    later = datetime(2026, 8, 17, 20, 1, tzinfo=timezone.utc)
    assert not schedule_is_due(schedule, now=later, last_run_date=None)
