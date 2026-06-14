from __future__ import annotations

import csv
import html as html_lib
import re
import urllib.request
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from .models import MatchResult
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
    timeout = match.kickoff_at + timedelta(hours=cfg["result_timeout_hours_after_kickoff"])
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
            if source["type"] == "wikipedia_tables":
                candidates.extend(fetch_wikipedia_results(source))
            elif source["type"] == "sbnation_schedule":
                candidates.extend(fetch_sbnation_schedule_results(source))
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"No se pudo consultar {source.get('name')}: {exc}")
    for match in due:
        source_match = _find_candidate(match, candidates)
        if source_match and source_match.confirmed:
            goals_a_real, goals_b_real = _goals_in_schedule_order(match, source_match)
            existing_by_id[match.match_id] = MatchResult(
                match_id=match.match_id,
                team_a=match.team_a,
                team_b=match.team_b,
                goals_a_real=goals_a_real,
                goals_b_real=goals_b_real,
                status="final",
                phase=match.phase,
                kickoff_at=match.kickoff_at,
                source=source_match.source,
                source_url=source_match.source_url,
                confirmed=True,
            )
    return list(existing_by_id.values()), warnings


def _parse_score_lines(text: str, source: str, url: str) -> list[MatchResult]:
    results: list[MatchResult] = []
    pattern = re.compile(r"([A-Z][A-Za-z .'\-]+?)\s+(\d{1,2})\s*[-–]\s*(\d{1,2})\s+([A-Z][A-Za-z .'\-]+)")
    for match in pattern.finditer(text):
        team_a = match.group(1).strip()
        team_b = match.group(4).strip()
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


def _goals_in_schedule_order(match: MatchResult, candidate: MatchResult) -> tuple[int | None, int | None]:
    if _norm(candidate.team_a) == _norm(match.team_a):
        return candidate.goals_a_real, candidate.goals_b_real
    return candidate.goals_b_real, candidate.goals_a_real


def _is_knockout(phase: str | None) -> bool:
    if not phase:
        return False
    return "group" not in phase.lower() and "grupo" not in phase.lower()


def _to_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _norm(value: str) -> str:
    return norm_text(value)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
