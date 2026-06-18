from datetime import datetime

from polla.models import MatchResult
from polla.prediction_rules import prediction_is_locked, prediction_lock_at, predictions_visible_for_date
from polla.timeutils import BOGOTA


def test_prediction_locks_at_eleven_before_afternoon_kickoff():
    match = MatchResult(
        "M001",
        "Colombia",
        "Japan",
        kickoff_at=datetime(2026, 6, 17, 14, 0, tzinfo=BOGOTA),
    )

    assert prediction_lock_at(match) == datetime(2026, 6, 17, 11, 0, tzinfo=BOGOTA)
    assert not prediction_is_locked(match, datetime(2026, 6, 17, 10, 59, tzinfo=BOGOTA))
    assert prediction_is_locked(match, datetime(2026, 6, 17, 11, 0, tzinfo=BOGOTA))


def test_prediction_locks_at_kickoff_when_match_is_before_eleven():
    match = MatchResult(
        "M001",
        "Colombia",
        "Japan",
        kickoff_at=datetime(2026, 6, 17, 9, 0, tzinfo=BOGOTA),
    )

    assert prediction_lock_at(match) == datetime(2026, 6, 17, 9, 0, tzinfo=BOGOTA)


def test_daily_predictions_are_visible_from_eleven():
    match_date = datetime(2026, 6, 17, tzinfo=BOGOTA).date()

    assert not predictions_visible_for_date(match_date, datetime(2026, 6, 17, 10, 59, tzinfo=BOGOTA))
    assert predictions_visible_for_date(match_date, datetime(2026, 6, 17, 11, 0, tzinfo=BOGOTA))
