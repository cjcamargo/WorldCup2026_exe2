from pathlib import Path

from polla.config import load_json
from polla.knockout import bracket_matches, derive_final_results, matches_for_mode, merge_knockout_schedule
from polla.models import FinalPicks, MatchResult, Prediction
from polla.results import _parse_espn_event
from polla.scoring import score_predictions
from polla.models import GroupMembership, PollaGroup
from scripts.update_app_backend import _score_rows_by_group


POINTS = {
    "exact_score": 2,
    "winner": 3,
    "team_goals": 1,
    "goal_difference": 1,
    "champion": 18,
    "runner_up": 15,
    "third_place": 12,
}


def _bracket_payload():
    return load_json(Path(__file__).parents[1] / "config" / "calendario_eliminatorias.json")


def test_knockout_calendar_has_all_32_matches_and_bogota_times():
    matches = bracket_matches(_bracket_payload())

    assert len(matches) == 32
    assert [match.match_id for match in matches] == [f"M{number:03d}" for number in range(73, 105)]
    assert matches[0].team_a == "South Africa"
    assert matches[0].team_b == "Canada"
    assert matches[0].kickoff_at.isoformat() == "2026-06-28T14:00:00-05:00"
    assert matches[-1].team_a == "Winner M101"
    assert matches[-1].team_b == "Winner M102"


def test_bracket_propagates_winner_and_loser():
    results = [
        MatchResult("M101", "Brazil", "France", 1, 1, phase="Semi-finals", confirmed=True, qualified_team="Brazil"),
        MatchResult("M102", "Colombia", "Spain", 0, 0, phase="Semi-finals", confirmed=True, qualified_team="Colombia"),
    ]

    matches, changed = merge_knockout_schedule([], _bracket_payload(), results)
    by_id = {match.match_id: match for match in matches}

    assert changed
    assert (by_id["M103"].team_a, by_id["M103"].team_b) == ("France", "Spain")
    assert (by_id["M104"].team_a, by_id["M104"].team_b) == ("Brazil", "Colombia")


def test_competition_modes_separate_group_and_knockout_matches():
    matches = [
        MatchResult("M001", "A", "B", phase="Group A"),
        MatchResult("M073", "C", "D", phase="Round of 32"),
    ]

    assert [match.match_id for match in matches_for_mode(matches, "group_stage")] == ["M001"]
    assert [match.match_id for match in matches_for_mode(matches, "knockout")] == ["M073"]


def test_knockout_score_uses_120_minute_result_and_qualifier():
    prediction = Prediction(
        "Alex", "M073", "South Africa", "Canada", 2, 2,
        winner_pred="Canada", qualified_team_pred="Canada",
    )
    result = MatchResult(
        "M073", "South Africa", "Canada", 1, 1,
        phase="Round of 32", confirmed=True, qualified_team="Canada",
        final_goals_a=2, final_goals_b=2,
    )

    ranking, detail = score_predictions([prediction], [result], [FinalPicks("Alex")], {}, POINTS)

    assert ranking[0]["points"] == 8
    assert detail[0]["exact_score_points"] == 2
    assert detail[0]["winner_points"] == 3
    assert "2-2 (120 min)" in detail[0]["real_score"]
    assert "Clasifica Canada" in detail[0]["real_score"]


def test_espn_parser_separates_regulation_extra_time_and_penalties():
    event = {
        "competitions": [{
            "status": {"period": 5, "type": {"completed": True}},
            "competitors": [
                {
                    "homeAway": "home", "winner": True, "score": "2", "shootoutScore": "4",
                    "team": {"id": "1", "displayName": "Brazil"},
                },
                {
                    "homeAway": "away", "winner": False, "score": "2", "shootoutScore": "3",
                    "team": {"id": "2", "displayName": "France"},
                },
            ],
            "details": [
                {"scoringPlay": True, "shootout": False, "scoreValue": 1, "clock": {"value": 1200}, "team": {"id": "1"}},
                {"scoringPlay": True, "shootout": False, "scoreValue": 1, "clock": {"value": 4500}, "team": {"id": "2"}},
                {"scoringPlay": True, "shootout": False, "scoreValue": 1, "clock": {"value": 6500}, "team": {"id": "1"}},
                {"scoringPlay": True, "shootout": False, "scoreValue": 1, "clock": {"value": 7000}, "team": {"id": "2"}},
                {"scoringPlay": True, "shootout": True, "scoreValue": 1, "clock": {"value": 7200}, "team": {"id": "1"}},
            ],
        }]
    }

    result = _parse_espn_event(event, "espn", "https://example.test")

    assert result is not None
    assert (result.goals_a_real, result.goals_b_real) == (1, 1)
    assert (result.final_goals_a, result.final_goals_b) == (2, 2)
    assert (result.penalties_a, result.penalties_b) == (4, 3)
    assert result.qualified_team == "Brazil"
    assert result.decision == "penalties"


def test_group_rankings_do_not_mix_group_stage_and_knockout_points():
    groups = [
        PollaGroup("groups-id", "Exe2", "EXE2", "admin", competition_mode="group_stage"),
        PollaGroup("ko-id", "Exe2 Knockout", "EXE2KO", "admin", competition_mode="knockout"),
    ]
    memberships = [
        GroupMembership("groups-id", "Alex", status="active"),
        GroupMembership("ko-id", "Alex", status="active"),
    ]
    predictions = [
        Prediction("Alex", "M001", "A", "B", 1, 0, group_id="groups-id"),
        Prediction("Alex", "M073", "C", "D", 0, 0, winner_pred="D", group_id="ko-id", qualified_team_pred="D"),
    ]
    matches = [
        MatchResult("M001", "A", "B", phase="Group A"),
        MatchResult("M073", "C", "D", phase="Round of 32"),
    ]
    results = [
        MatchResult("M001", "A", "B", 1, 0, phase="Group A", confirmed=True),
        MatchResult("M073", "C", "D", 0, 0, phase="Round of 32", confirmed=True, qualified_team="D"),
    ]

    ranking, detail = _score_rows_by_group(
        groups, memberships, predictions, results, [], {}, [], matches, POINTS,
    )

    points_by_group = {row["group_id"]: row["points"] for row in ranking}
    assert points_by_group == {"groups-id": 8, "ko-id": 8}
    assert {row["group_id"] for row in detail} == {"groups-id", "ko-id"}


def test_final_results_are_derived_from_third_place_and_final():
    results = [
        MatchResult("M103", "France", "Spain", 2, 1, confirmed=True, qualified_team="France"),
        MatchResult("M104", "Brazil", "Colombia", 1, 1, confirmed=True, qualified_team="Colombia"),
    ]

    assert derive_final_results(results) == {
        "champion": "Colombia",
        "runner_up": "Brazil",
        "third_place": "France",
    }
