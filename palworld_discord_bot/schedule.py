from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from palworld_discord_bot.config import RestartSchedule


def resolve_timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(
            f"タイムゾーン '{name}' が使えません。"
            "Windows では IANA の時刻データが無いので `pip install tzdata` が必要です。"
        ) from exc


def schedule_is_due(
    schedule: RestartSchedule,
    *,
    now: datetime,
    last_run_date: date | None,
) -> bool:
    local = now.astimezone(resolve_timezone(schedule.timezone))
    if last_run_date == local.date():
        return False
    hour, minute = schedule.hour_minute
    return local.hour == hour and local.minute == minute
