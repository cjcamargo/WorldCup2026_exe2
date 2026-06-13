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
from polla.results import update_results_from_sources
from polla.scoring import score_all
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
    results_cfg = load_json(config_path("resultados.json"))
    updated_results, result_warnings = update_results_from_sources(matches, existing_results, results_cfg)
    new_results = _new_result_ids(existing_results, updated_results)

    predictions = store.predictions()
    group_picks = store.group_picks()
    final_picks = store.final_picks()
    points = load_json(config_path("puntajes.json"))
    final_results = {
        "champion": settings.get("actual_champion") or None,
        "runner_up": settings.get("actual_runner_up") or None,
        "third_place": settings.get("actual_third_place") or None,
    }
    ranking, detail = score_all(predictions, updated_results, final_picks, final_results, group_picks, matches, points)

    audit_changes = store.audit_changes_after(settings.get("last_audit_email_at"))
    email_logs: list[str] = []
    if audit_changes:
        alert_cfg = load_json(config_path("alertas.json"))
        if args.dry_run:
            email_logs = send_messages([build_changes_email(audit_changes, alert_cfg)], alert_cfg, dry_run=True)
        else:
            email_logs = send_messages([build_changes_email(audit_changes, alert_cfg)], alert_cfg, dry_run=False)

    if not args.dry_run:
        store.replace_rows("Results", [_result_row(result) for result in updated_results])
        store.replace_rows("Ranking", ranking or [{"participant": "", "points": 0, "rank": ""}])
        store.replace_rows("Detail", _fit_detail_rows(detail))
        if audit_changes:
            store.save_setting("last_audit_email_at", max(change.detected_at for change in audit_changes))
        store.save_setting("last_backend_run_at", now_bogota().isoformat())

    print("Backend app actualizado")
    print(f"Partidos calendario: {len(matches)}")
    print(f"Resultados confirmados: {len(updated_results)}")
    print(f"Resultados nuevos: {', '.join(new_results) if new_results else 'ninguno'}")
    print(f"Ranking filas: {len(ranking)}")
    print(f"Cambios auditados enviados: {len(audit_changes)}")
    for log in email_logs:
        print(log)
    for warning in result_warnings:
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
    }


def _fit_detail_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    headers = ["participant", "match_id", "team_a", "team_b", "pred_score", "real_score", "points"]
    return [{header: row.get(header, "") for header in headers} for row in rows]


if __name__ == "__main__":
    raise SystemExit(main())
