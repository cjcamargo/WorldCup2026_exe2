from polla.models import FinalPicks, GroupPick, MatchResult, Prediction
from polla.scoring import score_group_picks, score_predictions


POINTS = {
    "exact_score": 2,
    "winner": 3,
    "team_goals": 1,
    "goal_difference": 1,
    "champion": 18,
    "runner_up": 9,
    "third_place": 5,
    "group_first": 5,
    "group_second": 3,
    "group_third": 2,
}


def test_exact_score_accumulates_all_match_points():
    predictions = [
        Prediction(
            participant="Alex",
            match_id="M001",
            team_a="Mexico",
            team_b="South Africa",
            goals_a_pred=2,
            goals_b_pred=1,
        )
    ]
    results = [
        MatchResult(
            match_id="M001",
            team_a="Mexico",
            team_b="South Africa",
            goals_a_real=2,
            goals_b_real=1,
            confirmed=True,
        )
    ]
    ranking, detail = score_predictions(predictions, results, [FinalPicks("Alex")], {}, POINTS)
    assert ranking[0]["points"] == 8
    assert detail[0]["exact_score_points"] == 2
    assert detail[0]["winner_points"] == 3
    assert detail[0]["team_a_goals_points"] == 1
    assert detail[0]["team_b_goals_points"] == 1
    assert detail[0]["goal_difference_points"] == 1


def test_final_picks_score_separately():
    ranking, detail = score_predictions(
        [],
        [],
        [FinalPicks("Alex", champion="Brazil", runner_up="France", third_place="Colombia")],
        {"champion": "Brazil", "runner_up": "Argentina", "third_place": "Colombia"},
        POINTS,
    )
    assert ranking[0]["points"] == 23
    assert detail[0]["champion_points"] == 18
    assert detail[0]["third_place_points"] == 5


def test_group_top_three_scores_exact_positions_only():
    schedule = [
        MatchResult("M001", "A", "B", phase="Group X"),
        MatchResult("M002", "C", "D", phase="Group X"),
        MatchResult("M003", "A", "C", phase="Group X"),
        MatchResult("M004", "B", "D", phase="Group X"),
        MatchResult("M005", "A", "D", phase="Group X"),
        MatchResult("M006", "B", "C", phase="Group X"),
    ]
    results = [
        MatchResult("M001", "A", "B", 2, 0, confirmed=True),
        MatchResult("M002", "C", "D", 1, 0, confirmed=True),
        MatchResult("M003", "A", "C", 1, 0, confirmed=True),
        MatchResult("M004", "B", "D", 1, 0, confirmed=True),
        MatchResult("M005", "A", "D", 1, 0, confirmed=True),
        MatchResult("M006", "B", "C", 2, 0, confirmed=True),
    ]
    ranking, detail = score_group_picks(
        [GroupPick("Alex", "Group X", first="A", second="B", third="C")],
        results,
        schedule,
        POINTS,
    )
    assert ranking[0]["points"] == 10
    assert detail[0]["group_first_points"] == 5
    assert detail[0]["group_second_points"] == 3
    assert detail[0]["group_third_points"] == 2
