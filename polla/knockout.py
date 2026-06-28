from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

from .models import MatchResult
from .schedule import canonical_team_name
from .timeutils import as_bogota, parse_datetime


KNOCKOUT_PHASES = {"round of 32", "round of 16", "quarter-finals", "semi-finals", "third place", "final"}


def is_knockout_phase(phase: str | None) -> bool:
    return bool(phase and phase.casefold() in KNOCKOUT_PHASES)


def matches_for_mode(matches: Iterable[MatchResult], competition_mode: str) -> list[MatchResult]:
    if competition_mode == "group_stage":
        return [match for match in matches if not is_knockout_phase(match.phase)]
    if competition_mode == "knockout":
        return [match for match in matches if is_knockout_phase(match.phase)]
    return list(matches)


def is_match_ready(match: MatchResult) -> bool:
    return not match.team_a.startswith("Winner ") and not match.team_a.startswith("Loser ") \
        and not match.team_b.startswith("Winner ") and not match.team_b.startswith("Loser ")


def bracket_matches(payload: dict[str, Any], results: Iterable[MatchResult] = ()) -> list[MatchResult]:
    result_by_id = {result.match_id: result for result in results if result.confirmed}
    matches: list[MatchResult] = []
    for item in payload.get("matches", []):
        team_a = _resolve_slot(item, "team_a", result_by_id)
        team_b = _resolve_slot(item, "team_b", result_by_id)
        matches.append(MatchResult(
            match_id=item["match_id"],
            team_a=team_a,
            team_b=team_b,
            phase=item["phase"],
            kickoff_at=as_bogota(parse_datetime(item.get("kickoff_at"))),
            status="scheduled",
            source="BBC Sport",
            source_url=payload.get("source"),
        ))
    return matches


def merge_knockout_schedule(
    existing: Iterable[MatchResult],
    payload: dict[str, Any],
    results: Iterable[MatchResult],
) -> tuple[list[MatchResult], list[MatchResult]]:
    existing_by_id = {match.match_id: match for match in existing}
    resolved = bracket_matches(payload, results)
    changed = [
        match for match in resolved
        if _schedule_signature(existing_by_id.get(match.match_id)) != _schedule_signature(match)
    ]
    merged = {match.match_id: match for match in existing}
    merged.update({match.match_id: match for match in resolved})
    return sorted(merged.values(), key=lambda match: match.match_id), changed


def knockout_teams(matches: Iterable[MatchResult]) -> list[str]:
    teams = {
        team
        for match in matches
        if is_knockout_phase(match.phase)
        for team in (match.team_a, match.team_b)
        if not team.startswith(("Winner ", "Loser "))
    }
    return sorted(teams)


def derive_final_results(results: Iterable[MatchResult]) -> dict[str, str | None]:
    by_id = {result.match_id: result for result in results if result.confirmed}
    final = by_id.get("M104")
    third_place = by_id.get("M103")
    champion = final.qualified_team if final else None
    runner_up = _loser(final) if final else None
    third = third_place.qualified_team if third_place else None
    return {"champion": champion, "runner_up": runner_up, "third_place": third}


def _resolve_slot(item: dict[str, Any], field: str, results: dict[str, MatchResult]) -> str:
    direct = item.get(field)
    if direct:
        return canonical_team_name(direct)
    source = item[f"{field}_from"]
    source_id = source["match_id"]
    result = results.get(source_id)
    if not result or not result.qualified_team:
        label = "Winner" if source["result"] == "winner" else "Loser"
        return f"{label} {source_id}"
    if source["result"] == "winner":
        return result.qualified_team
    return _loser(result) or f"Loser {source_id}"


def _loser(result: MatchResult | None) -> str | None:
    if not result or not result.qualified_team:
        return None
    return result.team_b if result.qualified_team == result.team_a else result.team_a


def _schedule_signature(match: MatchResult | None) -> tuple[Any, ...]:
    if match is None:
        return ()
    kickoff: datetime | None = as_bogota(match.kickoff_at)
    return match.team_a, match.team_b, match.phase, kickoff.isoformat() if kickoff else None
