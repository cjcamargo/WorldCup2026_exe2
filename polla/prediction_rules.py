from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, time, timedelta

from .models import MatchResult
from .timeutils import BOGOTA, as_bogota


DAILY_PREDICTION_CUTOFF = time(hour=14)
FIRST_KICKOFF_GRACE_PERIOD = timedelta(minutes=1)


def prediction_lock_at(match: MatchResult, schedule: Iterable[MatchResult] | None = None) -> datetime | None:
    kickoff = as_bogota(match.kickoff_at)
    if kickoff is None:
        return None
    return prediction_lock_for_date(kickoff.date(), schedule or [match])


def prediction_is_locked(match: MatchResult, at: datetime, schedule: Iterable[MatchResult] | None = None) -> bool:
    lock_at = prediction_lock_at(match, schedule)
    if lock_at is None:
        return False
    current = as_bogota(at)
    return bool(current and current >= lock_at)


def predictions_visible_for_date(match_date: date, at: datetime, schedule: Iterable[MatchResult] | None = None) -> bool:
    current = as_bogota(at)
    if current is None:
        return False
    cutoff = prediction_lock_for_date(match_date, schedule)
    if cutoff is None:
        return False
    return current >= cutoff


def prediction_lock_for_date(match_date: date, schedule: Iterable[MatchResult] | None = None) -> datetime | None:
    daily_cutoff = datetime.combine(match_date, DAILY_PREDICTION_CUTOFF, tzinfo=BOGOTA)
    kickoffs = [
        kickoff
        for match in schedule or []
        if (kickoff := as_bogota(match.kickoff_at)) is not None and kickoff.date() == match_date
    ]
    if not kickoffs:
        return daily_cutoff
    first_kickoff_cutoff = min(kickoffs) + FIRST_KICKOFF_GRACE_PERIOD
    return min(first_kickoff_cutoff, daily_cutoff)
