from datetime import timedelta

import polla.results as results_module
from polla.models import MatchResult
from polla.results import update_results_from_sources
from polla.timeutils import now_bogota


def test_reversed_source_candidate_scores_are_saved_in_schedule_order(monkeypatch):
    kickoff = now_bogota() - timedelta(hours=3)
    schedule = [
        MatchResult(
            match_id="M007",
            team_a="Haiti",
            team_b="Scotland",
            phase="Group C",
            kickoff_at=kickoff,
        )
    ]
    cfg = {
        "group_stage_expected_minutes": 120,
        "knockout_expected_minutes": 180,
        "result_first_check_minutes_after_expected_end": 5,
        "result_timeout_hours_after_kickoff": 24,
        "sources": [{"name": "test_source", "type": "sbnation_schedule", "enabled": True}],
    }

    def fake_fetch(_source_cfg):
        return [
            MatchResult(
                match_id="scotland_vs_haiti",
                team_a="Scotland",
                team_b="Haiti",
                goals_a_real=2,
                goals_b_real=1,
                source="test_source",
                confirmed=True,
            )
        ]

    monkeypatch.setattr(results_module, "fetch_sbnation_schedule_results", fake_fetch)

    updated, warnings = update_results_from_sources(schedule, [], cfg)

    assert warnings == []
    assert len(updated) == 1
    assert updated[0].match_id == "M007"
    assert updated[0].team_a == "Haiti"
    assert updated[0].team_b == "Scotland"
    assert updated[0].goals_a_real == 1
    assert updated[0].goals_b_real == 2
