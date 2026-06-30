from app import _predicted_match_counts
from polla.models import MatchResult, Prediction


def test_predicted_match_counts_only_complete_unique_predictions_with_confirmed_results():
    predictions = [
        Prediction("Alex", "M001", "Colombia", "Japan", 2, 1),
        Prediction("Alex", "M001", "Colombia", "Japan", 2, 1),
        Prediction("Alex", "M002", "Germany", "Mexico", 1, 0),
        Prediction("Alex", "M003", "France", "Sweden", None, 0),
        Prediction("Carlos", "M001", "Colombia", "Japan", 1, 1),
    ]
    results = [
        MatchResult("M001", "Colombia", "Japan", confirmed=True),
        MatchResult("M002", "Germany", "Mexico", confirmed=False),
        MatchResult("M003", "France", "Sweden", confirmed=True),
    ]

    counts = _predicted_match_counts(
        predictions,
        results,
    )

    assert counts == {"Alex": 1, "Carlos": 1}


def test_predicted_match_counts_are_scoped_to_group():
    predictions = [
        Prediction("Alex", "M001", "Colombia", "Japan", 2, 1, group_id="group-a"),
        Prediction("Alex", "M001", "Colombia", "Japan", 1, 0, group_id="group-b"),
    ]
    results = [MatchResult("M001", "Colombia", "Japan", confirmed=True)]

    counts = _predicted_match_counts(
        predictions,
        results,
        "group-a",
    )

    assert counts == {"Alex": 1}
