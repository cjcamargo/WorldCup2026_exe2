from datetime import datetime

from polla.models import MatchResult
from polla.prediction_rules import prediction_is_locked, prediction_lock_at, predictions_visible_for_date
from polla.timeutils import BOGOTA


def test_prediction_locks_at_first_kickoff_plus_one_before_two_pm():
    match = MatchResult(
        "M001",
        "Colombia",
        "Japan",
        kickoff_at=datetime(2026, 6, 17, 13, 0, tzinfo=BOGOTA),
    )
    later_match = MatchResult(
        "M002",
        "Germany",
        "Mexico",
        kickoff_at=datetime(2026, 6, 17, 17, 0, tzinfo=BOGOTA),
    )
    schedule = [match, later_match]

    assert prediction_lock_at(later_match, schedule) == datetime(2026, 6, 17, 13, 1, tzinfo=BOGOTA)
    assert not prediction_is_locked(later_match, datetime(2026, 6, 17, 13, 0, tzinfo=BOGOTA), schedule)
    assert prediction_is_locked(later_match, datetime(2026, 6, 17, 13, 1, tzinfo=BOGOTA), schedule)


def test_prediction_locks_at_two_pm_when_first_kickoff_is_later():
    match = MatchResult(
        "M001",
        "Colombia",
        "Japan",
        kickoff_at=datetime(2026, 6, 17, 17, 0, tzinfo=BOGOTA),
    )

    assert prediction_lock_at(match, [match]) == datetime(2026, 6, 17, 14, 0, tzinfo=BOGOTA)


def test_daily_predictions_are_visible_from_daily_lock():
    match_date = datetime(2026, 6, 17, tzinfo=BOGOTA).date()
    schedule = [
        MatchResult(
            "M001",
            "Colombia",
            "Japan",
            kickoff_at=datetime(2026, 6, 17, 15, 0, tzinfo=BOGOTA),
        )
    ]

    assert not predictions_visible_for_date(match_date, datetime(2026, 6, 17, 13, 59, tzinfo=BOGOTA), schedule)
    assert predictions_visible_for_date(match_date, datetime(2026, 6, 17, 14, 0, tzinfo=BOGOTA), schedule)
