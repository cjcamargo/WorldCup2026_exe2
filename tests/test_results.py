from datetime import timedelta

import polla.results as results_module
from polla.models import MatchResult
from polla.results import update_results_from_sources
from polla.results import _parse_score_lines
from polla.schedule import norm_text
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


def test_espn_scoreboard_result_updates_due_match(monkeypatch):
    kickoff = now_bogota() - timedelta(hours=3)
    schedule = [
        MatchResult(
            match_id="M008",
            team_a="Australia",
            team_b="Türkiye",
            phase="Group D",
            kickoff_at=kickoff,
        )
    ]
    cfg = {
        "group_stage_expected_minutes": 120,
        "knockout_expected_minutes": 180,
        "result_first_check_minutes_after_expected_end": 5,
        "result_timeout_hours_after_kickoff": 24,
        "sources": [{"name": "espn_test", "type": "espn_scoreboard", "url": "https://example.test"}],
    }

    def fake_fetch(_source_cfg, _due):
        return [
            MatchResult(
                match_id="australia_vs_turkiye",
                team_a="Australia",
                team_b="Türkiye",
                goals_a_real=2,
                goals_b_real=0,
                source="espn_test",
                confirmed=True,
            )
        ]

    monkeypatch.setattr(results_module, "fetch_espn_scoreboard_results", fake_fetch)

    updated, warnings = update_results_from_sources(schedule, [], cfg)

    assert warnings == []
    assert len(updated) == 1
    assert updated[0].match_id == "M008"
    assert updated[0].goals_a_real == 2
    assert updated[0].goals_b_real == 0


def test_wikipedia_parser_canonicalizes_turkey_to_turkiye():
    parsed = _parse_score_lines("Australia 2 - 0 Turkey", "wiki_test", "https://example.test")

    assert len(parsed) == 1
    assert parsed[0].team_a == "Australia"
    assert norm_text(parsed[0].team_b) == "turkiye"
    assert parsed[0].goals_a_real == 2
    assert parsed[0].goals_b_real == 0
