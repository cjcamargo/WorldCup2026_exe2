from datetime import date, datetime

from app import _filter_detail_rows
from polla.models import MatchResult
from polla.timeutils import BOGOTA


def test_detail_rows_filter_by_participant_and_date():
    matches = [
        MatchResult("M001", "Colombia", "Japan", kickoff_at=datetime(2026, 6, 18, 14, 0, tzinfo=BOGOTA)),
        MatchResult("M002", "Germany", "Mexico", kickoff_at=datetime(2026, 6, 19, 14, 0, tzinfo=BOGOTA)),
    ]
    detail = [
        {"participant": "Alex", "match_id": "M001", "points": 3},
        {"participant": "Carlos", "match_id": "M001", "points": 2},
        {"participant": "Alex", "match_id": "M002", "points": 1},
    ]

    rows = _filter_detail_rows(detail, matches, "Alex", date(2026, 6, 18))

    assert rows == [{"participant": "Alex", "match_id": "M001", "points": 3}]


def test_detail_rows_allow_all_dates_and_participants():
    matches = [
        MatchResult("M001", "Colombia", "Japan", kickoff_at=datetime(2026, 6, 18, 14, 0, tzinfo=BOGOTA)),
    ]
    detail = [
        {"participant": "Carlos", "match_id": "M001", "points": 2},
        {"participant": "Alex", "match_id": "M001", "points": 3},
    ]

    rows = _filter_detail_rows(detail, matches, "Todos", None)

    assert [row["participant"] for row in rows] == ["Alex", "Carlos"]
