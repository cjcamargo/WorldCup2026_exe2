from __future__ import annotations

import json
import re
import unicodedata
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from .models import MatchResult, Prediction
from .timeutils import BOGOTA, as_bogota, parse_datetime


WIKIPEDIA_RAW_GROUP_URL = "https://en.wikipedia.org/w/index.php?title=2026_FIFA_World_Cup_Group_{group}&action=raw"
GROUP_STAGE_EXPECTED_MATCHES = 72

TEAM_ALIASES = {
    "mexico": "Mexico",
    "southafrica": "South Africa",
    "sudafrica": "South Africa",
    "southkorea": "South Korea",
    "korearepublic": "South Korea",
    "coreadelsur": "South Korea",
    "czechrepublic": "Czech Republic",
    "czechia": "Czech Republic",
    "repcheca": "Czech Republic",
    "canada": "Canada",
    "bosniaandherzegovina": "Bosnia and Herzegovina",
    "bosniaherzegovina": "Bosnia and Herzegovina",
    "bosniayherzeg": "Bosnia and Herzegovina",
    "bosniayherzegovina": "Bosnia and Herzegovina",
    "unitedstates": "United States",
    "usa": "United States",
    "estadosunidos": "United States",
    "paraguay": "Paraguay",
    "qatar": "Qatar",
    "catar": "Qatar",
    "switzerland": "Switzerland",
    "suiza": "Switzerland",
    "brazil": "Brazil",
    "brasil": "Brazil",
    "morocco": "Morocco",
    "marruecos": "Morocco",
    "haiti": "Haiti",
    "scotland": "Scotland",
    "escocia": "Scotland",
    "australia": "Australia",
    "turkiye": "Türkiye",
    "turkey": "Türkiye",
    "turquia": "Türkiye",
    "germany": "Germany",
    "alemania": "Germany",
    "curacao": "Curaçao",
    "curazao": "Curaçao",
    "netherlands": "Netherlands",
    "paisesbajos": "Netherlands",
    "japan": "Japan",
    "japon": "Japan",
    "cotedivoire": "Côte d'Ivoire",
    "ivorycoast": "Côte d'Ivoire",
    "costademarfil": "Côte d'Ivoire",
    "ecuador": "Ecuador",
    "sweden": "Sweden",
    "suecia": "Sweden",
    "tunisia": "Tunisia",
    "tunez": "Tunisia",
    "spain": "Spain",
    "espana": "Spain",
    "capeverde": "Cabo Verde",
    "caboverde": "Cabo Verde",
    "belgium": "Belgium",
    "belgica": "Belgium",
    "egypt": "Egypt",
    "egipto": "Egypt",
    "saudiarabia": "Saudi Arabia",
    "arabiasaudita": "Saudi Arabia",
    "uruguay": "Uruguay",
    "iran": "IR Iran",
    "iriran": "IR Iran",
    "france": "France",
    "francia": "France",
    "senegal": "Senegal",
    "iraq": "Iraq",
    "irak": "Iraq",
    "norway": "Norway",
    "noruega": "Norway",
    "argentina": "Argentina",
    "algeria": "Algeria",
    "argelia": "Algeria",
    "austria": "Austria",
    "jordan": "Jordan",
    "jordania": "Jordan",
    "portugal": "Portugal",
    "drcongo": "DR Congo",
    "congodr": "DR Congo",
    "repdelcongo": "DR Congo",
    "england": "England",
    "inglaterra": "England",
    "croatia": "Croatia",
    "croacia": "Croatia",
    "ghana": "Ghana",
    "panama": "Panama",
    "uzbekistan": "Uzbekistan",
    "uzbekistan": "Uzbekistan",
    "colombia": "Colombia",
    "newzealand": "New Zealand",
    "nuevazelanda": "New Zealand",
}

MATCH_SECTION_RE = re.compile(
    r"^===\s*(?P<title>[^=]+?)\s*===\s*.*?"
    r"<section begin=.*?\|date=\{\{Start date\|(?P<year>\d+)\|(?P<month>\d+)\|(?P<day>\d+)\}\}\s*"
    r"\|time=(?P<time>[^\n]+)",
    re.M | re.S,
)

TIME_RE = re.compile(
    r"(?P<hour>\d{1,2}):(?P<minute>\d{2})\s*(?P<ampm>[ap])\.m\.\s*UTC(?P<offset_sign>[^0-9])(?P<offset_hour>\d{1,2})(?::(?P<offset_minute>\d{2}))?",
    re.I,
)


@dataclass
class ScheduleSyncReport:
    source: str | None = None
    total_matches: int = 0
    updated_matches: int = 0
    warnings: list[str] = field(default_factory=list)


def load_schedule(path: Path) -> list[MatchResult]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    matches: list[MatchResult] = []
    for item in payload.get("matches", []):
        matches.append(MatchResult(
            match_id=item["match_id"],
            team_a=canonical_team_name(item["team_a"]),
            team_b=canonical_team_name(item["team_b"]),
            phase=item.get("phase"),
            kickoff_at=as_bogota(parse_datetime(item.get("kickoff_at"))),
            status=item.get("status", "scheduled"),
            confirmed=bool(item.get("confirmed", False)),
            source=item.get("source"),
            source_url=item.get("source_url"),
            goals_a_real=item.get("goals_a_real"),
            goals_b_real=item.get("goals_b_real"),
        ))
    return matches


def save_schedule(path: Path, schedule: list[MatchResult]) -> None:
    payload = {
        "matches": [
            {
                "match_id": match.match_id,
                "phase": match.phase,
                "team_a": match.team_a,
                "team_b": match.team_b,
                "kickoff_at": match.kickoff_at.isoformat() if match.kickoff_at else None,
                "status": match.status,
            }
            for match in sorted(schedule, key=lambda item: item.match_id)
        ]
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def build_expected_matches(predictions: Iterable[Prediction]) -> list[MatchResult]:
    expected_by_id: dict[str, MatchResult] = {}
    for prediction in predictions:
        if prediction.match_id in expected_by_id:
            continue
        expected_by_id[prediction.match_id] = MatchResult(
            match_id=prediction.match_id,
            team_a=canonical_team_name(prediction.team_a),
            team_b=canonical_team_name(prediction.team_b),
            phase=_canonical_phase(prediction.phase),
            status="scheduled",
        )
    return sorted(expected_by_id.values(), key=lambda item: item.match_id)


def load_schedule_config(path: Path) -> dict:
    if not path.exists():
        return {
            "expected_group_stage_matches": GROUP_STAGE_EXPECTED_MATCHES,
            "sources": [{"name": "wikipedia_group_pages_raw", "type": "wikipedia_group_pages_raw", "enabled": True}],
        }
    return json.loads(path.read_text(encoding="utf-8"))


def sync_group_stage_schedule(
    existing_schedule: list[MatchResult],
    expected_matches: list[MatchResult],
    cfg: dict,
) -> tuple[list[MatchResult], ScheduleSyncReport]:
    report = ScheduleSyncReport()
    expected_count = int(cfg.get("expected_group_stage_matches", GROUP_STAGE_EXPECTED_MATCHES))
    base_matches = expected_matches or [match for match in existing_schedule if _is_group_stage(match.phase)]
    if not base_matches:
        report.warnings.append("No hay partidos base para sincronizar calendario.")
        return existing_schedule, report

    fetched: list[MatchResult] = []
    for source in cfg.get("sources", []):
        if not source.get("enabled", True):
            continue
        try:
            if source.get("type") == "wikipedia_group_pages_raw":
                fetched = fetch_wikipedia_group_stage_schedule(source)
                report.source = source.get("name", source.get("type"))
        except Exception as exc:  # noqa: BLE001
            report.warnings.append(f"No se pudo sincronizar calendario desde {source.get('name')}: {exc}")
        if fetched:
            break

    if not fetched:
        complete_existing = _count_complete_group_stage(existing_schedule)
        if complete_existing >= expected_count:
            report.total_matches = complete_existing
            report.warnings.append("Se mantiene calendario local existente; no hubo fuente remota disponible.")
            return existing_schedule, report
        raise RuntimeError("No fue posible sincronizar el calendario de fase de grupos desde Wikipedia.")

    merged_schedule, updated = merge_group_stage_schedule(existing_schedule, base_matches, fetched)
    report.total_matches = _count_complete_group_stage(merged_schedule)
    report.updated_matches = updated
    if report.total_matches < expected_count:
        raise RuntimeError(
            f"Calendario incompleto tras sincronizacion: {report.total_matches}/{expected_count} partidos con kickoff."
        )
    return merged_schedule, report


def fetch_wikipedia_group_stage_schedule(source_cfg: dict | None = None) -> list[MatchResult]:
    source_cfg = source_cfg or {}
    groups = source_cfg.get("groups") or [chr(code) for code in range(ord("A"), ord("L") + 1)]
    matches: list[MatchResult] = []
    for group in groups:
        url = source_cfg.get("url_template", WIKIPEDIA_RAW_GROUP_URL).format(group=group)
        matches.extend(parse_wikipedia_group_page(_fetch_text(url), f"Group {group}", url))
    return matches


def parse_wikipedia_group_page(raw_text: str, phase: str, source_url: str) -> list[MatchResult]:
    matches: list[MatchResult] = []
    for found in MATCH_SECTION_RE.finditer(raw_text):
        title = found.group("title").strip()
        if " vs " not in title:
            continue
        team_a_raw, team_b_raw = [part.strip() for part in title.split(" vs ", 1)]
        kickoff_at = parse_wikipedia_kickoff(
            int(found.group("year")),
            int(found.group("month")),
            int(found.group("day")),
            found.group("time"),
        )
        matches.append(MatchResult(
            match_id="",
            team_a=canonical_team_name(team_a_raw),
            team_b=canonical_team_name(team_b_raw),
            phase=phase,
            kickoff_at=kickoff_at,
            status="scheduled",
            source="wikipedia_group_pages_raw",
            source_url=source_url,
        ))
    return matches


def parse_wikipedia_kickoff(year: int, month: int, day: int, raw_time: str) -> datetime:
    clean = raw_time.replace("&nbsp;", " ")
    clean = re.sub(r"\[\[[^|\]]+\|([^\]]+)\]\]", r"\1", clean)
    clean = re.sub(r"\[\[([^\]]+)\]\]", r"\1", clean)
    clean = re.sub(r"</?includeonly>", "", clean)
    clean = clean.replace("\\u2212", "-").replace("\u2212", "-").replace("âˆ’", "-")
    clean = re.sub(r"\s+", " ", clean).strip()
    match = TIME_RE.search(clean)
    if not match:
        raise ValueError(f"Hora no reconocida: {raw_time}")
    hour = int(match.group("hour"))
    minute = int(match.group("minute"))
    ampm = match.group("ampm").lower()
    if ampm == "p" and hour != 12:
        hour += 12
    if ampm == "a" and hour == 12:
        hour = 0
    offset_hours = int(match.group("offset_hour"))
    offset_minutes = int(match.group("offset_minute") or 0)
    total_minutes = offset_hours * 60 + offset_minutes
    if match.group("offset_sign") != "+":
        total_minutes *= -1
    local_tz = timezone(timedelta(minutes=total_minutes))
    return datetime(year, month, day, hour, minute, tzinfo=local_tz).astimezone(BOGOTA)


def canonical_team_name(value: str) -> str:
    key = norm_text(value)
    return TEAM_ALIASES.get(key, _title_case_spaces(value))


def norm_text(value: str) -> str:
    stripped = unicodedata.normalize("NFKD", value)
    stripped = stripped.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "", stripped.casefold())


def merge_group_stage_schedule(
    existing_schedule: list[MatchResult],
    base_matches: list[MatchResult],
    fetched_schedule: list[MatchResult],
) -> tuple[list[MatchResult], int]:
    pair_to_base = {
        (norm_text(match.team_a), norm_text(match.team_b)): match
        for match in base_matches
        if _is_group_stage(match.phase)
    }
    resolved_group_matches: dict[str, MatchResult] = {}
    for source_match in fetched_schedule:
        base = pair_to_base.get((norm_text(source_match.team_a), norm_text(source_match.team_b)))
        if not base:
            continue
        resolved_group_matches[base.match_id] = MatchResult(
            match_id=base.match_id,
            team_a=base.team_a,
            team_b=base.team_b,
            phase=_prefer_source_phase(base.phase, source_match.phase),
            kickoff_at=source_match.kickoff_at,
            status=source_match.status or "scheduled",
            source=source_match.source,
            source_url=source_match.source_url,
        )

    untouched = [match for match in existing_schedule if not _is_group_stage(match.phase)]
    updated = 0
    final_group_matches: list[MatchResult] = []
    existing_by_id = {match.match_id: match for match in existing_schedule}
    for base in sorted(base_matches, key=lambda item: item.match_id):
        resolved = resolved_group_matches.get(base.match_id)
        fallback = existing_by_id.get(base.match_id)
        chosen = resolved or fallback or base
        if resolved and _schedule_signature(existing_by_id.get(base.match_id)) != _schedule_signature(resolved):
            updated += 1
        final_group_matches.append(chosen)
    return sorted(untouched + final_group_matches, key=lambda item: item.match_id), updated


def _fetch_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=45) as response:
        return response.read().decode("utf-8", "ignore")


def _canonical_phase(value: str | None) -> str | None:
    if not value:
        return None
    if "group" in value.casefold():
        suffix = value.strip().split()[-1]
        if len(suffix) == 1 and suffix.isalpha():
            return f"Group {suffix.upper()}"
    return value


def _count_complete_group_stage(schedule: list[MatchResult]) -> int:
    return sum(1 for match in schedule if _is_group_stage(match.phase) and match.kickoff_at is not None)


def _is_group_stage(phase: str | None) -> bool:
    return bool(phase and "group" in phase.casefold())


def _schedule_signature(match: MatchResult | None) -> tuple[str | None, str | None, str | None, str | None]:
    if match is None:
        return (None, None, None, None)
    return (
        match.team_a,
        match.team_b,
        match.phase,
        match.kickoff_at.isoformat() if match.kickoff_at else None,
    )


def _title_case_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _prefer_source_phase(base_phase: str | None, source_phase: str | None) -> str | None:
    if not base_phase:
        return source_phase
    if base_phase.casefold() == "group stage" and source_phase:
        return source_phase
    return base_phase
