from __future__ import annotations

from datetime import date, datetime, time

from .models import MatchResult
from .timeutils import BOGOTA, as_bogota


DAILY_PREDICTION_CUTOFF = time(hour=11)


def prediction_lock_at(match: MatchResult) -> datetime | None:
    kickoff = as_bogota(match.kickoff_at)
    if kickoff is None:
        return None
    daily_cutoff = datetime.combine(kickoff.date(), DAILY_PREDICTION_CUTOFF, tzinfo=BOGOTA)
    return min(kickoff, daily_cutoff)


def prediction_is_locked(match: MatchResult, at: datetime) -> bool:
    lock_at = prediction_lock_at(match)
    if lock_at is None:
        return False
    current = as_bogota(at)
    return bool(current and current >= lock_at)


def predictions_visible_for_date(match_date: date, at: datetime) -> bool:
    current = as_bogota(at)
    if current is None:
        return False
    cutoff = datetime.combine(match_date, DAILY_PREDICTION_CUTOFF, tzinfo=BOGOTA)
    return current >= cutoff
