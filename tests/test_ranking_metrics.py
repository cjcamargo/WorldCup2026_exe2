from app import _predicted_match_counts
from polla.models import Prediction


def test_predicted_match_counts_only_complete_unique_predictions():
    predictions = [
        Prediction("Alex", "M001", "Colombia", "Japan", 2, 1),
        Prediction("Alex", "M001", "Colombia", "Japan", 2, 1),
        Prediction("Alex", "M002", "Germany", "Mexico", None, 0),
        Prediction("Carlos", "M001", "Colombia", "Japan", 1, 1),
    ]

    counts = _predicted_match_counts(predictions)

    assert counts == {"Alex": 1, "Carlos": 1}
