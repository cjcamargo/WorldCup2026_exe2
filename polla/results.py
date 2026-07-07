from __future__ import annotations

import csv
import html as html_lib
import json
import re
import urllib.request
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from .models import MatchResult
from .knockout import is_knockout_phase
from .schedule import canonical_team_name, norm_text
from .timeutils import as_bogota, now_bogota, parse_datetime


FINAL_STATUSES = {"FT", "FINAL", "FINALIZADO", "FULL TIME", "AET", "PEN"}


def load_manual_schedule(path: Path) -> list[MatchResult]:
    if not path.exists():
        return []
    import json
    payload = json.loads(path.read_text(encoding="utf-8"))
    matches = []
    for item in payload.get("matches", []):
        matches.append(MatchResult(
            match_id=item["match_id"],
            team_a=item["team_a"],
            team_b=item["team_b"],
            phase=item.get("phase"),
            kickoff_at=as_bogota(parse_datetime(item.get("kickoff_at"))),
            status=item.get("status", "scheduled"),
        ))
    return matches


def load_confirmed_results(path: Path) -> list[MatchResult]:
    if not path.exists():
        return []
    rows: list[MatchResult] = []
    with path.open("r", newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            rows.append(MatchResult(
                match_id=row["match_id"],
                team_a=row["team_a"],
                team_b=row["team_b"],
                goals_a_real=_to_int(row.get("goals_a_real")),
                goals_b_real=_to_int(row.get("goals_b_real")),
                status=row.get("status", "final"),
                phase=row.get("phase") or None,
                source=row.get("source") or None,
                source_url=row.get("source_url") or None,
                confirmed=str(row.get("confirmed", "")).lower() in {"true", "1", "yes"},
            ))
    return rows


def save_results(path: Path, results: list[MatchResult]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(asdict(results[0]).keys()) if results else [
        "match_id", "team_a", "team_b", "goals_a_real", "goals_b_real", "status",
        "phase", "kickoff_at", "source", "source_url", "confirmed",
    ]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for result in results:
            row = asdict(result)
            if result.kickoff_at:
                row["kickoff_at"] = result.kickoff_at.isoformat()
            writer.writerow(row)


def should_check_result(match: MatchResult, cfg: dict, at=None) -> bool:
    at = at or now_bogota()
    if match.confirmed or match.kickoff_at is None:
        return False
    expected_minutes = cfg["knockout_expected_minutes"] if _is_knockout(match.phase) else cfg["group_stage_expected_minutes"]
    first_check = match.kickoff_at + timedelta(minutes=expected_minutes + cfg["result_first_check_minutes_after_expected_end"])
    timeout_hours = (
        cfg.get("knockout_result_refresh_hours_after_kickoff", cfg["result_timeout_hours_after_kickoff"])
        if _is_knockout(match.phase)
        else cfg["result_timeout_hours_after_kickoff"]
    )
    timeout = match.kickoff_at + timedelta(hours=timeout_hours)
    return first_check <= at <= timeout


def fetch_wikipedia_results(source_cfg: dict) -> list[MatchResult]:
    url = source_cfg["url"]
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=45) as response:
        html = response.read()
    tables = pd.read_html(html)
    found: list[MatchResult] = []
    for table in tables:
        text = table.to_string(index=False)
        for match in _parse_score_lines(text, source_cfg["name"], url):
            found.append(match)
    return found


def fetch_sbnation_schedule_results(source_cfg: dict) -> list[MatchResult]:
    url = source_cfg["url"]
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=45) as response:
        raw_html = response.read().decode("utf-8", errors="ignore")
    text = html_lib.unescape(re.sub(r"<[^>]+>", "\n", raw_html))
    found: list[MatchResult] = []
    pattern = re.compile(
        r"Group\s+[A-L]:\s+([A-Za-z .'\-çéôüıİ]+?)\s+(\d{1,2}),\s+([A-Za-z .'\-çéôüıİ]+?)\s+(\d{1,2})(?=\s|$)",
        re.I,
    )
    for match in pattern.finditer(text):
        team_a = canonical_team_name(match.group(1).strip())
        team_b = canonical_team_name(match.group(3).strip())
        found.append(MatchResult(
            match_id=f"{_slug(team_a)}_vs_{_slug(team_b)}",
            team_a=team_a,
            team_b=team_b,
            goals_a_real=int(match.group(2)),
            goals_b_real=int(match.group(4)),
            status="final",
            source=source_cfg["name"],
            source_url=url,
            confirmed=True,
        ))
    return found


def fetch_espn_scoreboard_results(source_cfg: dict, due_matches: list[MatchResult]) -> list[MatchResult]:
    url = source_cfg["url"]
    found: list[MatchResult] = []
    for date_key in _espn_date_keys(due_matches):
        req = urllib.request.Request(f"{url}?dates={date_key}", headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=45) as response:
            payload = json.load(response)
        for event in payload.get("events", []):
            result = _parse_espn_event(event, source_cfg["name"], f"{url}?dates={date_key}")
            if result:
                found.append(result)
    return found


def update_results_from_sources(schedule: list[MatchResult], existing: list[MatchResult], cfg: dict) -> tuple[list[MatchResult], list[str]]:
    existing_by_id = {r.match_id: r for r in existing}
    warnings: list[str] = []
    candidates: list[MatchResult] = []
    due = [m for m in schedule if should_check_result(m, cfg)]
    if not due:
        return existing, warnings
    for source in cfg.get("sources", []):
        if not source.get("enabled", True):
            continue
        try:
            if source["type"] == "espn_scoreboard":
                candidates.extend(fetch_espn_scoreboard_results(source, due))
            elif source["type"] == "wikipedia_tables":
                candidates.extend(fetch_wikipedia_results(source))
            elif source["type"] == "sbnation_schedule":
                candidates.extend(fetch_sbnation_schedule_results(source))
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"No se pudo consultar {source.get('name')}: {exc}")
    for match in due:
        source_match = _find_candidate(match, candidates)
        if source_match and source_match.confirmed:
            ordered = _candidate_in_schedule_order(match, source_match)
            if is_knockout_phase(match.phase) and not ordered.qualified_team:
                warnings.append(f"Resultado {match.match_id} encontrado, pero sin equipo clasificado; se reintentara.")
                continue
            existing_by_id[match.match_id] = MatchResult(
                match_id=match.match_id,
                team_a=match.team_a,
                team_b=match.team_b,
                goals_a_real=ordered.goals_a_real,
                goals_b_real=ordered.goals_b_real,
                status="final",
                phase=match.phase,
                kickoff_at=match.kickoff_at,
                source=source_match.source,
                source_url=source_match.source_url,
                confirmed=True,
                final_goals_a=ordered.final_goals_a,
                final_goals_b=ordered.final_goals_b,
                penalties_a=ordered.penalties_a,
                penalties_b=ordered.penalties_b,
                qualified_team=ordered.qualified_team,
                decision=ordered.decision,
            )
    return list(existing_by_id.values()), warnings


def _espn_date_keys(matches: list[MatchResult]) -> list[str]:
    dates = set()
    for match in matches:
        if not match.kickoff_at:
            continue
        dates.add(match.kickoff_at.strftime("%Y%m%d"))
        dates.add((match.kickoff_at + timedelta(days=1)).strftime("%Y%m%d"))
    dates.add(now_bogota().strftime("%Y%m%d"))
    return sorted(dates)


def _parse_espn_event(event: dict, source: str, url: str) -> MatchResult | None:
    competitions = event.get("competitions") or []
    if not competitions:
        return None
    competition = competitions[0]
    status = competition.get("status", {}).get("type", {})
    if not status.get("completed"):
        return None
    competitors = competition.get("competitors") or []
    home = next((item for item in competitors if item.get("homeAway") == "home"), None)
    away = next((item for item in competitors if item.get("homeAway") == "away"), None)
    if not home or not away:
        return None
    team_a = canonical_team_name(home.get("team", {}).get("displayName", ""))
    team_b = canonical_team_name(away.get("team", {}).get("displayName", ""))
    if not team_a or not team_b:
        return None
    home_total = _to_int(home.get("score"))
    away_total = _to_int(away.get("score"))
    home_periods = _period_scores(home)
    away_periods = _period_scores(away)
    status_period = _to_int(competition.get("status", {}).get("period")) or 0
    has_extra_time = status_period > 2 or len(home_periods) > 2 or len(away_periods) > 2
    home_from_events = _regulation_score_from_details(competition, home)
    away_from_events = _regulation_score_from_details(competition, away)
    home_final_from_events = _final_score_from_details(competition, home)
    away_final_from_events = _final_score_from_details(competition, away)
    home_regulation = home_from_events if home_from_events is not None else sum(home_periods[:2]) if len(home_periods) >= 2 else home_total
    away_regulation = away_from_events if away_from_events is not None else sum(away_periods[:2]) if len(away_periods) >= 2 else away_total
    home_final = home_final_from_events if home_final_from_events is not None else sum(home_periods) if home_periods else home_total
    away_final = away_final_from_events if away_final_from_events is not None else sum(away_periods) if away_periods else away_total
    penalties_a = _to_int(home.get("shootoutScore"))
    penalties_b = _to_int(away.get("shootoutScore"))
    qualified = next(
        (
            canonical_team_name(item.get("team", {}).get("displayName", ""))
            for item in competitors
            if item.get("winner") is True
        ),
        None,
    )
    decision = "penalties" if penalties_a is not None or penalties_b is not None else "extra_time" if has_extra_time else "regular_time"
    return MatchResult(
        match_id=f"{_slug(team_a)}_vs_{_slug(team_b)}",
        team_a=team_a,
        team_b=team_b,
        goals_a_real=home_regulation,
        goals_b_real=away_regulation,
        status="final",
        source=source,
        source_url=url,
        confirmed=True,
        final_goals_a=home_final,
        final_goals_b=away_final,
        penalties_a=penalties_a,
        penalties_b=penalties_b,
        qualified_team=qualified,
        decision=decision,
    )


def _parse_score_lines(text: str, source: str, url: str) -> list[MatchResult]:
    results: list[MatchResult] = []
    pattern = re.compile(r"([A-Z][A-Za-z .'\-]+?)\s+(\d{1,2})\s*[-–]\s*(\d{1,2})\s+([A-Z][A-Za-z .'\-]+)")
    for match in pattern.finditer(text):
        team_a = canonical_team_name(match.group(1).strip())
        team_b = canonical_team_name(match.group(4).strip())
        if len(team_a) > 40 or len(team_b) > 40:
            continue
        results.append(MatchResult(
            match_id=f"{_slug(team_a)}_vs_{_slug(team_b)}",
            team_a=team_a,
            team_b=team_b,
            goals_a_real=int(match.group(2)),
            goals_b_real=int(match.group(3)),
            status="final",
            source=source,
            source_url=url,
            confirmed=True,
        ))
    return results


def _find_candidate(match: MatchResult, candidates: list[MatchResult]) -> MatchResult | None:
    for candidate in candidates:
        if {_norm(candidate.team_a), _norm(candidate.team_b)} == {_norm(match.team_a), _norm(match.team_b)}:
            return candidate
    return None


def _candidate_in_schedule_order(match: MatchResult, candidate: MatchResult) -> MatchResult:
    if _norm(candidate.team_a) == _norm(match.team_a):
        return candidate
    return MatchResult(
        match_id=candidate.match_id,
        team_a=match.team_a,
        team_b=match.team_b,
        goals_a_real=candidate.goals_b_real,
        goals_b_real=candidate.goals_a_real,
        status=candidate.status,
        source=candidate.source,
        source_url=candidate.source_url,
        confirmed=candidate.confirmed,
        final_goals_a=candidate.final_goals_b,
        final_goals_b=candidate.final_goals_a,
        penalties_a=candidate.penalties_b,
        penalties_b=candidate.penalties_a,
        qualified_team=candidate.qualified_team,
        decision=candidate.decision,
    )


def _goals_in_schedule_order(match: MatchResult, candidate: MatchResult) -> tuple[int | None, int | None]:
    ordered = _candidate_in_schedule_order(match, candidate)
    return ordered.goals_a_real, ordered.goals_b_real


def _period_scores(competitor: dict[str, Any]) -> list[int]:
    values = []
    for line in competitor.get("linescores") or []:
        value = _to_int(line.get("value", line.get("displayValue")))
        if value is not None:
            values.append(value)
    return values


def _regulation_score_from_details(competition: dict[str, Any], competitor: dict[str, Any]) -> int | None:
    details = competition.get("details")
    if not isinstance(details, list):
        return None
    team_id = str(competitor.get("team", {}).get("id", ""))
    if not team_id:
        return None
    return sum(
        _to_int(detail.get("scoreValue")) or 0
        for detail in details
        if detail.get("scoringPlay") is True
        and detail.get("shootout") is not True
        and (_to_int(detail.get("clock", {}).get("value")) or 0) <= 90 * 60
        and str(detail.get("team", {}).get("id", "")) == team_id
    )


def _final_score_from_details(competition: dict[str, Any], competitor: dict[str, Any]) -> int | None:
    details = competition.get("details")
    if not isinstance(details, list):
        return None
    scoring_plays = [
        detail for detail in details
        if detail.get("scoringPlay") is True and detail.get("shootout") is not True
    ]
    if not scoring_plays:
        return None
    team_id = str(competitor.get("team", {}).get("id", ""))
    if not team_id:
        return None
    return sum(
        _to_int(detail.get("scoreValue")) or 0
        for detail in scoring_plays
        if str(detail.get("team", {}).get("id", "")) == team_id
    )


def _is_knockout(phase: str | None) -> bool:
    return is_knockout_phase(phase)


def _to_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _norm(value: str) -> str:
    return norm_text(value)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
