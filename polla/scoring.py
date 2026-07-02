from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .models import FinalPicks, GroupPick, MatchResult, Prediction
from .knockout import is_knockout_phase


def score_predictions(
    predictions: list[Prediction],
    results: list[MatchResult],
    final_picks: list[FinalPicks],
    final_results: dict[str, str | None],
    points: dict[str, int],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    result_by_match = {r.match_id: r for r in results if r.confirmed and r.goals_a_real is not None and r.goals_b_real is not None}
    detail: list[dict[str, Any]] = []
    totals: dict[str, dict[str, Any]] = {}
    for pred in predictions:
        total_row = totals.setdefault(pred.participant, {"participant": pred.participant, "points": 0})
        result = result_by_match.get(pred.match_id)
        if result is None or not pred.valid:
            continue
        row = _score_match(pred, result, points)
        detail.append(row)
        total_row["points"] += row["points"]
    for picks in final_picks:
        total_row = totals.setdefault(picks.participant, {"participant": picks.participant, "points": 0})
        final_row = _score_finals(picks, final_results, points)
        if final_row["points"]:
            detail.append(final_row)
            total_row["points"] += final_row["points"]
    ranking = sorted(totals.values(), key=lambda item: item["points"], reverse=True)
    for idx, row in enumerate(ranking, start=1):
        row["rank"] = idx
    return ranking, detail


def score_all(
    predictions: list[Prediction],
    results: list[MatchResult],
    final_picks: list[FinalPicks],
    final_results: dict[str, str | None],
    group_picks: list[GroupPick],
    schedule: list[MatchResult],
    points: dict[str, int],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ranking, detail = score_predictions(predictions, results, final_picks, final_results, points)
    group_ranking, group_detail = score_group_picks(group_picks, results, schedule, points)
    totals = {row["participant"]: dict(row) for row in ranking}
    for row in group_ranking:
        total_row = totals.setdefault(row["participant"], {"participant": row["participant"], "points": 0})
        total_row["points"] += row["points"]
    final_ranking = sorted(totals.values(), key=lambda item: item["points"], reverse=True)
    for idx, row in enumerate(final_ranking, start=1):
        row["rank"] = idx
    return final_ranking, detail + group_detail


def score_group_picks(
    group_picks: list[GroupPick],
    results: list[MatchResult],
    schedule: list[MatchResult],
    points: dict[str, int],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    standings_by_group = _completed_group_standings(results, schedule)
    detail: list[dict[str, Any]] = []
    totals: dict[str, dict[str, Any]] = {}
    for pick in group_picks:
        total_row = totals.setdefault(pick.participant, {"participant": pick.participant, "points": 0})
        actual = standings_by_group.get(pick.group)
        if not actual:
            continue
        row = {
            "participant": pick.participant,
            "match_id": f"GROUP_{pick.group}",
            "team_a": "",
            "team_b": "",
            "pred_score": f"{pick.first} | {pick.second} | {pick.third}",
            "real_score": " | ".join(actual[:3]),
            "exact_score_points": 0,
            "winner_points": 0,
            "team_a_goals_points": 0,
            "team_b_goals_points": 0,
            "goal_difference_points": 0,
            "group_first_points": 0,
            "group_second_points": 0,
            "group_third_points": 0,
            "points": 0,
        }
        if _same_team(pick.first, actual[0] if len(actual) > 0 else None):
            row["group_first_points"] = points.get("group_first", 5)
        if _same_team(pick.second, actual[1] if len(actual) > 1 else None):
            row["group_second_points"] = points.get("group_second", 3)
        if _same_team(pick.third, actual[2] if len(actual) > 2 else None):
            row["group_third_points"] = points.get("group_third", 2)
        row["points"] = row["group_first_points"] + row["group_second_points"] + row["group_third_points"]
        if row["points"]:
            detail.append(row)
            total_row["points"] += row["points"]
    ranking = sorted(totals.values(), key=lambda item: item["points"], reverse=True)
    for idx, row in enumerate(ranking, start=1):
        row["rank"] = idx
    return ranking, detail


def _score_match(pred: Prediction, result: MatchResult, points: dict[str, int]) -> dict[str, Any]:
    predicted_qualifier = pred.qualified_team_pred or pred.winner_pred
    real_goals_a, real_goals_b = _score_goals(result)
    pred_score = f"{pred.goals_a_pred}-{pred.goals_b_pred}"
    real_score = f"{real_goals_a}-{real_goals_b}"
    if is_knockout_phase(result.phase):
        pred_score += f" | Clasifica {predicted_qualifier or '-'}"
        real_score += f" (120 min) | Clasifica {result.qualified_team or '-'}"
    row = {
        "participant": pred.participant,
        "match_id": pred.match_id,
        "team_a": pred.team_a,
        "team_b": pred.team_b,
        "pred_score": pred_score,
        "real_score": real_score,
        "exact_score_points": 0,
        "winner_points": 0,
        "team_a_goals_points": 0,
        "team_b_goals_points": 0,
        "goal_difference_points": 0,
        "points": 0,
    }
    pred_outcome = _outcome(pred.goals_a_pred, pred.goals_b_pred)
    real_outcome = _outcome(real_goals_a, real_goals_b)
    if pred.goals_a_pred == real_goals_a and pred.goals_b_pred == real_goals_b:
        row["exact_score_points"] = points["exact_score"]
    if is_knockout_phase(result.phase) and result.qualified_team:
        if _same_team(predicted_qualifier, result.qualified_team):
            row["winner_points"] = points["winner"]
    elif pred_outcome is not None and pred_outcome == real_outcome:
        row["winner_points"] = points["winner"]
    if pred.goals_a_pred == real_goals_a:
        row["team_a_goals_points"] = points["team_goals"]
    if pred.goals_b_pred == real_goals_b:
        row["team_b_goals_points"] = points["team_goals"]
    if _diff(pred.goals_a_pred, pred.goals_b_pred) == _diff(real_goals_a, real_goals_b):
        row["goal_difference_points"] = points["goal_difference"]
    row["points"] = sum(value for key, value in row.items() if key.endswith("_points"))
    return row


def _score_goals(result: MatchResult) -> tuple[int | None, int | None]:
    if (
        is_knockout_phase(result.phase)
        and result.final_goals_a is not None
        and result.final_goals_b is not None
    ):
        return result.final_goals_a, result.final_goals_b
    return result.goals_a_real, result.goals_b_real


def _score_finals(picks: FinalPicks, final_results: dict[str, str | None], points: dict[str, int]) -> dict[str, Any]:
    row = {
        "participant": picks.participant,
        "match_id": "FINAL_PICKS",
        "team_a": "",
        "team_b": "",
        "pred_score": "",
        "real_score": "",
        "exact_score_points": 0,
        "winner_points": 0,
        "team_a_goals_points": 0,
        "team_b_goals_points": 0,
        "goal_difference_points": 0,
        "champion_points": 0,
        "runner_up_points": 0,
        "third_place_points": 0,
        "points": 0,
    }
    if picks.champion and _same_team(picks.champion, final_results.get("champion")):
        row["champion_points"] = points["champion"]
    if picks.runner_up and _same_team(picks.runner_up, final_results.get("runner_up")):
        row["runner_up_points"] = points["runner_up"]
    if picks.third_place and _same_team(picks.third_place, final_results.get("third_place")):
        row["third_place_points"] = points["third_place"]
    row["points"] = row["champion_points"] + row["runner_up_points"] + row["third_place_points"]
    return row


def _winner(team_a: str, team_b: str, goals_a: int | None, goals_b: int | None) -> str | None:
    if goals_a is None or goals_b is None:
        return None
    if goals_a > goals_b:
        return team_a
    if goals_b > goals_a:
        return team_b
    return "Empate"


def _outcome(goals_a: int | None, goals_b: int | None) -> str | None:
    if goals_a is None or goals_b is None:
        return None
    if goals_a > goals_b:
        return "A"
    if goals_b > goals_a:
        return "B"
    return "D"


def _diff(a: int | None, b: int | None) -> int | None:
    if a is None or b is None:
        return None
    return a - b


def _same_team(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return False
    return left.strip().casefold() == right.strip().casefold()


def _completed_group_standings(
    results: list[MatchResult],
    schedule: list[MatchResult],
) -> dict[str, list[str]]:
    schedule_by_group: dict[str, list[MatchResult]] = {}
    for match in schedule:
        if match.phase and "group" in match.phase.casefold():
            schedule_by_group.setdefault(match.phase, []).append(match)
    result_by_match = {
        result.match_id: result
        for result in results
        if result.confirmed and result.goals_a_real is not None and result.goals_b_real is not None
    }
    standings: dict[str, list[str]] = {}
    for group, matches in schedule_by_group.items():
        if not matches or any(match.match_id not in result_by_match for match in matches):
            continue
        table: dict[str, dict[str, int]] = {}
        for match in matches:
            result = result_by_match[match.match_id]
            _ensure_team(table, match.team_a)
            _ensure_team(table, match.team_b)
            table[match.team_a]["gf"] += int(result.goals_a_real or 0)
            table[match.team_a]["ga"] += int(result.goals_b_real or 0)
            table[match.team_b]["gf"] += int(result.goals_b_real or 0)
            table[match.team_b]["ga"] += int(result.goals_a_real or 0)
            if result.goals_a_real > result.goals_b_real:
                table[match.team_a]["pts"] += 3
            elif result.goals_b_real > result.goals_a_real:
                table[match.team_b]["pts"] += 3
            else:
                table[match.team_a]["pts"] += 1
                table[match.team_b]["pts"] += 1
        standings[group] = [
            team
            for team, _stats in sorted(
                table.items(),
                key=lambda item: (
                    item[1]["pts"],
                    item[1]["gf"] - item[1]["ga"],
                    item[1]["gf"],
                    item[0],
                ),
                reverse=True,
            )
        ]
    return standings


def _ensure_team(table: dict[str, dict[str, int]], team: str) -> None:
    table.setdefault(team, {"pts": 0, "gf": 0, "ga": 0})
