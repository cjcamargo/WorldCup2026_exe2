from polla.models import MatchResult
from polla.standings import calculate_group_standings
from polla.standings import payload_to_standings
from polla.standings import standings_to_payload
from polla.standings import _parse_espn_standings_payload


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


def test_payload_roundtrip_preserves_standings_order():
    schedule = [MatchResult("M001", "Colombia", "Japan", phase="Group A")]
    results = [MatchResult("M001", "Colombia", "Japan", goals_a_real=2, goals_b_real=0, confirmed=True)]
    original = calculate_group_standings(schedule, results)

    restored = payload_to_standings(standings_to_payload(original, "test"))

    assert [row.team for row in restored["Group A"]] == ["Colombia", "Japan"]
    assert restored["Group A"][0].points == 3


def test_parse_espn_standings_payload_extracts_rows():
    payload = {
        "children": [
            {
                "name": "overall",
                "standings": {
                    "entries": [
                        {"team": {"displayName": "Colombia"}, "stats": [{"abbreviation": "PTS", "value": 4}]},
                        {"team": {"displayName": "Japan"}, "stats": [{"abbreviation": "PTS", "value": 1}]},
                    ]
                },
            },
            {
                "name": "Group A",
                "standings": {
                    "entries": [
                        {
                            "team": {"displayName": "Colombia"},
                            "stats": [
                                {"abbreviation": "GP", "value": 2},
                                {"abbreviation": "W", "value": 1},
                                {"abbreviation": "D", "value": 1},
                                {"abbreviation": "L", "value": 0},
                                {"abbreviation": "GF", "value": 3},
                                {"abbreviation": "GA", "value": 1},
                                {"abbreviation": "GD", "value": 2},
                                {"abbreviation": "PTS", "value": 4},
                            ],
                        },
                        {
                            "team": {"displayName": "Japan"},
                            "stats": [
                                {"abbreviation": "GP", "value": 2},
                                {"abbreviation": "PTS", "value": 1},
                            ],
                        },
                    ]
                },
            }
        ]
    }

    parsed = _parse_espn_standings_payload(payload)

    assert parsed["Group A"][0]["team"] == "Colombia"
    assert parsed["Group A"][0]["played"] == 2
    assert parsed["Group A"][0]["points"] == 4
