from polla.audit import detect_changes
from polla.audit import apply_deadline_policy
from polla.models import AuditChange, MatchResult, Prediction
from datetime import datetime
from zoneinfo import ZoneInfo


def test_detects_changed_prediction_field():
    previous = {
        "Alex|M001|Mexico|South Africa": {
            "participant": "Alex",
            "match_id": "M001",
            "goals_a_pred": 1,
            "goals_b_pred": 0,
            "winner_pred": "Mexico",
        }
    }
    current = {
        "Alex|M001|Mexico|South Africa": {
            "participant": "Alex",
            "match_id": "M001",
            "goals_a_pred": 2,
            "goals_b_pred": 0,
            "winner_pred": "Mexico",
        }
    }
    changes = detect_changes(previous, current, "2026-06-12T00:00:00-05:00")
    assert len(changes) == 1
    assert changes[0].field == "goals_a_pred"
    assert changes[0].old_value == 1
    assert changes[0].new_value == 2


def test_late_change_invalidates_prediction():
    pred = Prediction(
        participant="Alex",
        match_id="M001",
        team_a="Mexico",
        team_b="South Africa",
        goals_a_pred=2,
        goals_b_pred=0,
    )
    change = AuditChange(
        detected_at="2026-06-11T15:01:00-05:00",
        participant="Alex",
        match_id="M001",
        field="goals_a_pred",
        old_value=1,
        new_value=2,
        status="changed",
    )
    schedule = [
        MatchResult(
            match_id="M001",
            team_a="Mexico",
            team_b="South Africa",
            kickoff_at=datetime(2026, 6, 11, 14, 0, tzinfo=ZoneInfo("America/Bogota")),
        )
    ]
    guarded, changes = apply_deadline_policy(
        [pred],
        [change],
        schedule,
        datetime(2026, 6, 11, 15, 1, tzinfo=ZoneInfo("America/Bogota")),
    )
    assert guarded[0].valid is False
    assert changes[0].status == "invalid"
