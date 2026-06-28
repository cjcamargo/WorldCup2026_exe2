from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from polla.config import config_path, load_json
from polla.emailer import build_changes_email, send_messages
from polla.models import MatchResult
from polla.knockout import derive_final_results, matches_for_mode, merge_knockout_schedule
from polla.results import update_results_from_sources
from polla.scoring import score_all
from polla.standings import calculate_group_standings, fetch_espn_group_standings, standings_to_payload
from polla.supabase_store import SupabaseStore
from polla.timeutils import now_bogota


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Actualiza resultados, ranking y correos desde GitHub Actions.")
    parser.add_argument("--dry-run", action="store_true", help="No escribe resultados/ranking ni envia correos.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    store = _store_from_env()
    store.ensure_schema()

    settings = store.settings()
    matches = store.matches()
    existing_results = _dedupe_results(store.results())
    bracket_cfg = load_json(config_path("calendario_eliminatorias.json"))
    matches, initial_match_changes = merge_knockout_schedule(matches, bracket_cfg, existing_results)
    results_cfg = load_json(config_path("resultados.json"))
    updated_results, result_warnings = update_results_from_sources(matches, existing_results, results_cfg)
    new_results = _new_result_ids(existing_results, updated_results)
    matches, propagated_match_changes = merge_knockout_schedule(matches, bracket_cfg, updated_results)

    predictions = store.predictions()
    group_picks = store.group_picks()
    final_picks = store.final_picks()
    groups = store.groups()
    memberships = store.memberships()
    points = load_json(config_path("puntajes.json"))
    saved_final_results = {
        "champion": settings.get("actual_champion") or None,
        "runner_up": settings.get("actual_runner_up") or None,
        "third_place": settings.get("actual_third_place") or None,
    }
    automatic_final_results = derive_final_results(updated_results)
    final_results = {
        key: automatic_final_results.get(key) or saved_final_results.get(key)
        for key in saved_final_results
    }
    ranking, detail = _score_rows_by_group(
        groups,
        memberships,
        predictions,
        updated_results,
        final_picks,
        final_results,
        group_picks,
        matches,
        points,
    )
    group_standings_payload, standings_warnings = fetch_espn_group_standings(results_cfg.get("standings", {}))
    if not group_standings_payload:
        group_standings = calculate_group_standings(matches, updated_results)
        group_standings_payload = standings_to_payload(
            group_standings,
            source="Calculado desde resultados confirmados",
        )
    else:
        group_standings = group_standings_payload.get("groups", {})

    audit_changes = store.audit_changes_after(settings.get("last_audit_email_at"))
    email_logs: list[str] = []
    if audit_changes:
        alert_cfg = load_json(config_path("alertas.json"))
        if args.dry_run:
            email_logs = send_messages([build_changes_email(audit_changes, alert_cfg)], alert_cfg, dry_run=True)
        else:
            email_logs = send_messages([build_changes_email(audit_changes, alert_cfg)], alert_cfg, dry_run=False)

    if not args.dry_run:
        store.upsert_matches(initial_match_changes + propagated_match_changes)
        store.replace_rows("Results", [_result_row(result) for result in updated_results])
        store.replace_rows("Ranking", ranking)
        store.replace_rows("Detail", _fit_detail_rows(detail))
        store.save_setting("group_standings", group_standings_payload)
        if automatic_final_results["champion"]:
            store.save_setting("actual_champion", automatic_final_results["champion"])
            store.save_setting("actual_runner_up", automatic_final_results["runner_up"] or "")
        if automatic_final_results["third_place"]:
            store.save_setting("actual_third_place", automatic_final_results["third_place"])
        if audit_changes:
            store.save_setting("last_audit_email_at", max(change.detected_at for change in audit_changes))
        store.save_setting("last_backend_run_at", now_bogota().isoformat())

    print("Backend app actualizado")
    print(f"Partidos calendario: {len(matches)}")
    print(f"Resultados confirmados: {len(updated_results)}")
    print(f"Resultados nuevos: {', '.join(new_results) if new_results else 'ninguno'}")
    print(f"Cruces knockout actualizados: {len(initial_match_changes) + len(propagated_match_changes)}")
    print(f"Ranking filas: {len(ranking)}")
    print(f"Tablas de grupo calculadas: {len(group_standings)}")
    print(f"Cambios auditados enviados: {len(audit_changes)}")
    for log in email_logs:
        print(log)
    for warning in result_warnings:
        print(f"WARNING: {warning}")
    for warning in standings_warnings:
        print(f"WARNING: {warning}")
    return 0


def _store_from_env() -> SupabaseStore:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url:
        raise RuntimeError("Falta secret SUPABASE_URL.")
    if not key:
        raise RuntimeError("Falta secret SUPABASE_SERVICE_ROLE_KEY.")
    return SupabaseStore(url, key)


def _dedupe_results(results: list[MatchResult]) -> list[MatchResult]:
    by_id = {}
    for result in results:
        by_id[result.match_id] = result
    return list(by_id.values())


def _new_result_ids(old: list[MatchResult], new: list[MatchResult]) -> list[str]:
    old_ids = {result.match_id for result in old if result.confirmed}
    return sorted(result.match_id for result in new if result.confirmed and result.match_id not in old_ids)


def _result_row(result: MatchResult) -> dict[str, Any]:
    return {
        "match_id": result.match_id,
        "team_a": result.team_a,
        "team_b": result.team_b,
        "goals_a_real": result.goals_a_real,
        "goals_b_real": result.goals_b_real,
        "status": result.status,
        "phase": result.phase,
        "kickoff_at": result.kickoff_at.isoformat() if result.kickoff_at else "",
        "source": result.source,
        "source_url": result.source_url,
        "confirmed": str(result.confirmed),
        "final_goals_a": result.final_goals_a,
        "final_goals_b": result.final_goals_b,
        "penalties_a": result.penalties_a,
        "penalties_b": result.penalties_b,
        "qualified_team": result.qualified_team,
        "decision": result.decision,
    }


def _fit_detail_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    headers = ["group_id", "participant", "match_id", "team_a", "team_b", "pred_score", "real_score", "points"]
    return [{header: row.get(header, "") for header in headers} for row in rows]


def _score_rows_by_group(
    groups: list[Any],
    memberships: list[Any],
    predictions: list[Any],
    results: list[MatchResult],
    final_picks: list[Any],
    final_results: dict[str, str | None],
    group_picks: list[Any],
    matches: list[MatchResult],
    points: dict[str, int],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not groups:
        return score_all(predictions, results, final_picks, final_results, group_picks, matches, points)
    ranking_rows: list[dict[str, Any]] = []
    detail_rows: list[dict[str, Any]] = []
    for group in groups:
        if not getattr(group, "active", True):
            continue
        participants = {
            membership.participant
            for membership in memberships
            if membership.group_id == group.group_id and membership.status == "active"
        }
        competition_mode = getattr(group, "competition_mode", "full")
        scoped_matches = matches_for_mode(matches, competition_mode)
        match_ids = {match.match_id for match in scoped_matches}
        scoped_predictions = [
            prediction for prediction in predictions
            if prediction.group_id == group.group_id and prediction.match_id in match_ids
        ]
        scoped_results = [result for result in results if result.match_id in match_ids]
        scoped_final_picks = [] if competition_mode == "group_stage" else [
            pick for pick in final_picks if pick.group_id == group.group_id
        ]
        scoped_group_picks = [] if competition_mode == "knockout" else [
            pick for pick in group_picks if pick.group_id == group.group_id
        ]
        ranking, detail = score_all(
            scoped_predictions,
            scoped_results,
            scoped_final_picks,
            final_results,
            scoped_group_picks,
            scoped_matches,
            points,
        )
        group_ranking = [dict(row) for row in ranking if row.get("participant") in participants]
        for idx, row in enumerate(group_ranking, start=1):
            row["rank"] = idx
            ranking_rows.append({"group_id": group.group_id, **row})
        for row in detail:
            if row.get("participant") in participants:
                detail_rows.append({"group_id": group.group_id, **row})
    return ranking_rows, detail_rows


if __name__ == "__main__":
    raise SystemExit(main())
