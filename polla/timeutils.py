from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo


BOGOTA = ZoneInfo("America/Bogota")


def now_bogota() -> datetime:
    return datetime.now(tz=BOGOTA)


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.replace("Z", "+00:00")
    return datetime.fromisoformat(text)


def as_bogota(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(BOGOTA)
