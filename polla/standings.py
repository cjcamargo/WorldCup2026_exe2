from __future__ import annotations

from dataclasses import dataclass

from .models import MatchResult


@dataclass(frozen=True)
class TeamStanding:
    group: str
    team: str
    played: int = 0
    won: int = 0
    drawn: int = 0
    lost: int = 0
    goals_for: int = 0
    goals_against: int = 0
    goal_difference: int = 0
    points: int = 0


def calculate_group_standings(
    schedule: list[MatchResult],
    results: list[MatchResult],
) -> dict[str, list[TeamStanding]]:
    tables: dict[str, dict[str, dict[str, int]]] = {}
    for match in schedule:
        if not _is_group_phase(match.phase):
            continue
        group = match.phase or "Sin fase"
        tables.setdefault(group, {})
        _ensure_team(tables[group], match.team_a)
        _ensure_team(tables[group], match.team_b)

    schedule_by_id = {match.match_id: match for match in schedule}
    for result in results:
        if not result.confirmed or result.goals_a_real is None or result.goals_b_real is None:
            continue
        match = schedule_by_id.get(result.match_id)
        if not match or not _is_group_phase(match.phase):
            continue
        group = match.phase or "Sin fase"
        table = tables.setdefault(group, {})
        _ensure_team(table, match.team_a)
        _ensure_team(table, match.team_b)
        _apply_result(table, match.team_a, match.team_b, int(result.goals_a_real), int(result.goals_b_real))

    return {
        group: [_to_standing(group, team, stats) for team, stats in _sorted_table(table)]
        for group, table in sorted(tables.items())
    }


def _apply_result(table: dict[str, dict[str, int]], team_a: str, team_b: str, goals_a: int, goals_b: int) -> None:
    table[team_a]["played"] += 1
    table[team_b]["played"] += 1
    table[team_a]["goals_for"] += goals_a
    table[team_a]["goals_against"] += goals_b
    table[team_b]["goals_for"] += goals_b
    table[team_b]["goals_against"] += goals_a
    if goals_a > goals_b:
        table[team_a]["won"] += 1
        table[team_b]["lost"] += 1
        table[team_a]["points"] += 3
    elif goals_b > goals_a:
        table[team_b]["won"] += 1
        table[team_a]["lost"] += 1
        table[team_b]["points"] += 3
    else:
        table[team_a]["drawn"] += 1
        table[team_b]["drawn"] += 1
        table[team_a]["points"] += 1
        table[team_b]["points"] += 1


def _ensure_team(table: dict[str, dict[str, int]], team: str) -> None:
    table.setdefault(
        team,
        {
            "played": 0,
            "won": 0,
            "drawn": 0,
            "lost": 0,
            "goals_for": 0,
            "goals_against": 0,
            "points": 0,
        },
    )


def _sorted_table(table: dict[str, dict[str, int]]) -> list[tuple[str, dict[str, int]]]:
    return sorted(
        table.items(),
        key=lambda item: (
            -item[1]["points"],
            -(item[1]["goals_for"] - item[1]["goals_against"]),
            -item[1]["goals_for"],
            item[1]["goals_against"],
            item[0],
        ),
    )


def _to_standing(group: str, team: str, stats: dict[str, int]) -> TeamStanding:
    return TeamStanding(
        group=group,
        team=team,
        played=stats["played"],
        won=stats["won"],
        drawn=stats["drawn"],
        lost=stats["lost"],
        goals_for=stats["goals_for"],
        goals_against=stats["goals_against"],
        goal_difference=stats["goals_for"] - stats["goals_against"],
        points=stats["points"],
    )


def _is_group_phase(phase: str | None) -> bool:
    return bool(phase and "group" in phase.casefold())
