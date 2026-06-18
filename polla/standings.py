from __future__ import annotations

from dataclasses import dataclass
import json
import urllib.request
from typing import Any

from .models import MatchResult
from .schedule import canonical_team_name
from .timeutils import now_bogota


@dataclass(frozen=True)
class TeamStanding:
    group: str
    team: str
    source_rank: int = 0
    played: int = 0
    won: int = 0
    drawn: int = 0
    lost: int = 0
    goals_for: int = 0
    goals_against: int = 0
    goal_difference: int = 0
    points: int = 0


DEFAULT_ESPN_STANDINGS_URLS = [
    "https://site.web.api.espn.com/apis/v2/sports/soccer/fifa.world/standings?season=2026",
    "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/standings?season=2026",
]


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


def fetch_espn_group_standings(cfg: dict[str, Any] | None = None) -> tuple[dict[str, Any] | None, list[str]]:
    cfg = cfg or {}
    warnings: list[str] = []
    for url in cfg.get("urls") or DEFAULT_ESPN_STANDINGS_URLS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=int(cfg.get("timeout_seconds", 45))) as response:
                payload = json.load(response)
            groups = _parse_espn_standings_payload(payload)
            if groups:
                return {
                    "source": "ESPN standings",
                    "source_url": url,
                    "updated_at": now_bogota().isoformat(),
                    "groups": groups,
                }, warnings
            warnings.append(f"ESPN standings sin grupos utiles: {url}")
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"No se pudo consultar ESPN standings {url}: {exc}")
    return None, warnings


def standings_to_payload(
    standings_by_group: dict[str, list[TeamStanding]],
    source: str,
    source_url: str | None = None,
) -> dict[str, Any]:
    return {
        "source": source,
        "source_url": source_url,
        "updated_at": now_bogota().isoformat(),
        "groups": {
            group: [_standing_to_dict(row, idx) for idx, row in enumerate(rows, start=1)]
            for group, rows in standings_by_group.items()
        },
    }


def payload_to_standings(payload: Any) -> dict[str, list[TeamStanding]]:
    if isinstance(payload, str):
        payload = json.loads(payload)
    groups = (payload or {}).get("groups") or {}
    out: dict[str, list[TeamStanding]] = {}
    for group, rows in groups.items():
        standings = [
            TeamStanding(
                group=group,
                team=str(row.get("team") or ""),
                source_rank=int(row.get("rank") or 0),
                played=int(row.get("played") or 0),
                won=int(row.get("won") or 0),
                drawn=int(row.get("drawn") or 0),
                lost=int(row.get("lost") or 0),
                goals_for=int(row.get("goals_for") or 0),
                goals_against=int(row.get("goals_against") or 0),
                goal_difference=int(row.get("goal_difference") or 0),
                points=int(row.get("points") or 0),
            )
            for row in rows
        ]
        out[group] = sort_standings(standings)
    return out


def sort_standings(rows: list[TeamStanding]) -> list[TeamStanding]:
    return sorted(
        rows,
        key=lambda row: (
            -row.points,
            -row.goal_difference,
            -row.goals_for,
            row.goals_against,
            row.source_rank if row.source_rank > 0 else 999,
            row.team,
        ),
    )


def _parse_espn_standings_payload(payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for node in _walk_dicts(payload):
        standings_node = node.get("standings")
        if isinstance(standings_node, dict) and isinstance(standings_node.get("entries"), list):
            rows = [
                _parse_espn_entry(entry, idx)
                for idx, entry in enumerate(standings_node["entries"], start=1)
                if isinstance(entry, dict)
            ]
            rows = [row for row in rows if row and row.get("team")]
            group_name = _espn_group_name(node)
            if len(rows) >= 2 and _is_world_cup_group_name(group_name):
                groups[group_name] = _sort_payload_rows(rows)
        entries = node.get("entries")
        if not isinstance(entries, list) or not entries:
            continue
        rows = [
            _parse_espn_entry(entry, idx)
            for idx, entry in enumerate(entries, start=1)
            if isinstance(entry, dict)
        ]
        rows = [row for row in rows if row and row.get("team")]
        if len(rows) < 2:
            continue
        group_name = _espn_group_name(node)
        if _is_world_cup_group_name(group_name):
            groups[group_name] = _sort_payload_rows(rows)
    return groups


def _parse_espn_entry(entry: dict[str, Any], fallback_rank: int = 0) -> dict[str, Any] | None:
    team = entry.get("team") or {}
    team_name = canonical_team_name(
        team.get("displayName") or team.get("shortDisplayName") or team.get("name") or entry.get("name") or ""
    )
    if not team_name:
        return None
    stats = _espn_stats(entry)
    return {
        "rank": _to_int(entry.get("rank") or entry.get("position")) or fallback_rank,
        "team": team_name,
        "played": _first_stat(stats, "GP", "P", "gamesPlayed", "played"),
        "won": _first_stat(stats, "W", "wins"),
        "drawn": _first_stat(stats, "D", "draws", "ties"),
        "lost": _first_stat(stats, "L", "losses"),
        "goals_for": _first_stat(stats, "F", "GF", "goalsFor", "pointsFor"),
        "goals_against": _first_stat(stats, "A", "GA", "goalsAgainst", "pointsAgainst"),
        "goal_difference": _first_stat(stats, "GD", "DIFF", "goalDifference", "differential"),
        "points": _first_stat(stats, "PTS", "points"),
    }


def _sort_payload_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            -int(row.get("points") or 0),
            -int(row.get("goal_difference") or 0),
            -int(row.get("goals_for") or 0),
            int(row.get("goals_against") or 0),
            int(row.get("rank") or 999),
            str(row.get("team") or ""),
        ),
    )


def _espn_stats(entry: dict[str, Any]) -> dict[str, int]:
    stats: dict[str, int] = {}
    for stat in entry.get("stats") or []:
        if not isinstance(stat, dict):
            continue
        value = _to_int(stat.get("value") if stat.get("value") is not None else stat.get("displayValue"))
        for key in (stat.get("name"), stat.get("abbreviation"), stat.get("shortDisplayName"), stat.get("displayName")):
            if key:
                stats[str(key)] = value
    return stats


def _first_stat(stats: dict[str, int], *keys: str) -> int:
    normalized = {str(key).casefold(): value for key, value in stats.items()}
    for key in keys:
        if key.casefold() in normalized:
            return normalized[key.casefold()]
    return 0


def _espn_group_name(node: dict[str, Any]) -> str:
    group = node.get("group") or node.get("name") or node.get("displayName") or node.get("shortName")
    if isinstance(group, dict):
        group = group.get("displayName") or group.get("name") or group.get("abbreviation")
    text = str(group or "").strip()
    if text:
        return text
    return f"Group {len(node.get('entries') or [])}"


def _walk_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dicts(child)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_dicts(item)


def _standing_to_dict(row: TeamStanding, rank: int) -> dict[str, Any]:
    return {
        "rank": row.source_rank or rank,
        "team": row.team,
        "played": row.played,
        "won": row.won,
        "drawn": row.drawn,
        "lost": row.lost,
        "goals_for": row.goals_for,
        "goals_against": row.goals_against,
        "goal_difference": row.goal_difference,
        "points": row.points,
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


def _is_world_cup_group_name(name: str) -> bool:
    return name.casefold().startswith("group ") and name[-1:].upper() in set("ABCDEFGHIJKL")


def _to_int(value: Any) -> int:
    if value in (None, ""):
        return 0
    try:
        return int(float(str(value).replace("+", "")))
    except ValueError:
        return 0
