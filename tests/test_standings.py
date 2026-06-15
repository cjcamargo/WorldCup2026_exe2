from polla.models import MatchResult
from polla.standings import calculate_group_standings


def test_group_standings_include_points_goals_and_goal_difference():
    schedule = [
        MatchResult("M001", "Colombia", "Japan", phase="Group A"),
        MatchResult("M002", "Germany", "Mexico", phase="Group A"),
        MatchResult("M003", "Colombia", "Germany", phase="Group A"),
    ]
    results = [
        MatchResult("M001", "Colombia", "Japan", goals_a_real=2, goals_b_real=0, confirmed=True),
        MatchResult("M002", "Germany", "Mexico", goals_a_real=1, goals_b_real=1, confirmed=True),
        MatchResult("M003", "Colombia", "Germany", goals_a_real=0, goals_b_real=3, confirmed=True),
    ]

    standings = calculate_group_standings(schedule, results)["Group A"]

    assert [row.team for row in standings] == ["Germany", "Colombia", "Mexico", "Japan"]
    assert standings[0].points == 4
    assert standings[0].goals_for == 4
    assert standings[0].goals_against == 1
    assert standings[0].goal_difference == 3
    assert standings[1].played == 2
    assert standings[1].won == 1
    assert standings[1].lost == 1


def test_group_standings_ignore_unconfirmed_results_and_knockout_matches():
    schedule = [
        MatchResult("M001", "Colombia", "Japan", phase="Group A"),
        MatchResult("M073", "Winner A", "Runner B", phase="Round of 32"),
    ]
    results = [
        MatchResult("M001", "Colombia", "Japan", goals_a_real=2, goals_b_real=0, confirmed=False),
        MatchResult("M073", "Winner A", "Runner B", goals_a_real=4, goals_b_real=0, confirmed=True),
    ]

    standings = calculate_group_standings(schedule, results)["Group A"]

    assert len(standings) == 2
    assert all(row.played == 0 for row in standings)
