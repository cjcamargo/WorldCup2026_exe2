from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from polla.audit import append_audit_csv, apply_deadline_policy, detect_changes, load_snapshot, predictions_to_snapshot, save_snapshot
from polla.config import ROOT, config_path, data_path, load_json, output_path
from polla.drive import DriveDownloadError, resolve_participant_file
from polla.emailer import build_changes_email, send_messages
from polla.excel_reader import apply_prediction_overrides, read_predictions, workbook_hash
from polla.models import RunSummary
from polla.reporting import write_workbook
from polla.results import load_confirmed_results, save_results, update_results_from_sources
from polla.schedule import build_expected_matches, load_schedule, load_schedule_config, save_schedule, sync_group_stage_schedule
from polla.scoring import score_predictions
from polla.timeutils import now_bogota


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Automatizacion de polla mundialista.")
    parser.add_argument("--dry-run", action="store_true", help="No envia correos y evita acciones riesgosas.")
    parser.add_argument("--audit-only", action="store_true", help="Solo lee Excel y detecta cambios.")
    parser.add_argument("--results-only", action="store_true", help="Solo consulta resultados web.")
    parser.add_argument("--rebuild-ranking", action="store_true", help="Recalcula ranking con datos existentes.")
    parser.add_argument("--refresh-downloads", action="store_true", help="Fuerza descarga de Excel desde Drive.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = RunSummary()
    participants_cfg = load_json(config_path("participantes.json"))
    points_cfg = load_json(config_path("puntajes.json"))
    alert_cfg = load_json(config_path("alertas.json"))
    extractor_cfg = load_json(config_path("extractor.json"))
    overrides_cfg = load_json(config_path("prediction_overrides.json")) if config_path("prediction_overrides.json").exists() else {"overrides": []}
    results_cfg = load_json(config_path("resultados.json"))
    schedule_cfg = load_schedule_config(config_path("calendario_fuentes.json"))
    drive_auth_cfg = load_json(config_path("google_drive.json"))
    detected_at = now_bogota().isoformat()
    run_at = now_bogota()
    schedule_path = config_path("calendario_partidos.json")
    schedule = load_schedule(schedule_path)

    downloads_dir = data_path("downloads")
    inputs_dir = ROOT / "inputs"
    all_predictions = []
    all_picks = []
    sync_error_reported = False

    if not args.results_only:
        for participant in participants_cfg["participants"]:
            if not participant.get("active", True):
                continue
            try:
                path = resolve_participant_file(
                    participant,
                    downloads_dir,
                    inputs_dir,
                    args.refresh_downloads,
                    auth_config=drive_auth_cfg,
                    root=ROOT,
                )
                predictions, picks, warnings = read_predictions(path, participant["name"], extractor_cfg)
                summary.warnings.extend(warnings)
                all_predictions.extend(predictions)
                all_picks.append(picks)
                summary.predictions_read += len(predictions)
                summary.warnings.append(f"{participant['name']}: hash {workbook_hash(path)[:12]}")
            except DriveDownloadError as exc:
                message = str(exc)
                if "credenciales OAuth" in message or "token de Google Drive" in message:
                    if not sync_error_reported:
                        summary.warnings.append(f"No se pudo sincronizar Google Drive: {message}")
                        sync_error_reported = True
                else:
                    summary.warnings.append(f"No se pudo sincronizar {participant['name']}: {message}")

        expected_matches = build_expected_matches(all_predictions)
        schedule, schedule_report = sync_group_stage_schedule(schedule, expected_matches, schedule_cfg)
        summary.warnings.append(
            f"Calendario grupos: {schedule_report.total_matches} partidos, {schedule_report.updated_matches} actualizados"
        )
        if schedule_report.source:
            summary.warnings.append(f"Fuente calendario: {schedule_report.source}")
        summary.warnings.extend(schedule_report.warnings)
        if not args.dry_run and schedule_report.updated_matches:
            save_schedule(schedule_path, schedule)

        all_predictions, override_warnings = apply_prediction_overrides(
            all_predictions,
            overrides_cfg.get("overrides"),
        )
        snapshot_path = data_path("snapshots", "latest_predictions.json")
        previous_snapshot = load_snapshot(snapshot_path)
        current_snapshot = predictions_to_snapshot(all_predictions)
        changes = detect_changes(previous_snapshot, current_snapshot, detected_at)
        all_predictions, changes = apply_deadline_policy(all_predictions, changes, schedule, run_at)
        current_snapshot = predictions_to_snapshot(all_predictions)
        summary.changes_detected = len(changes)
        append_audit_csv(data_path("auditoria", "auditoria_cambios.csv"), changes)
        summary.warnings.extend(override_warnings)
        messages = [build_changes_email(changes, alert_cfg)] if changes else []
        email_failed = False
        try:
            email_logs = send_messages(messages, alert_cfg, dry_run=args.dry_run or alert_cfg.get("dry_run", True))
        except RuntimeError as exc:
            email_failed = True
            email_logs = [f"Email no enviado: {exc}"]
        summary.emails_prepared = len(email_logs)
        summary.warnings.extend(email_logs)

        if not args.dry_run and not email_failed:
            save_snapshot(snapshot_path, current_snapshot)

        if args.audit_only:
            _print_summary(summary)
            return 0

    results_path = data_path("resultados", "resultados_confirmados.csv")
    confirmed_results = load_confirmed_results(results_path)
    if not args.audit_only and not args.rebuild_ranking:
        if args.results_only:
            schedule, schedule_report = sync_group_stage_schedule(schedule, [], schedule_cfg)
            summary.warnings.append(
                f"Calendario grupos: {schedule_report.total_matches} partidos, {schedule_report.updated_matches} actualizados"
            )
            if schedule_report.source:
                summary.warnings.append(f"Fuente calendario: {schedule_report.source}")
            summary.warnings.extend(schedule_report.warnings)
            if not args.dry_run and schedule_report.updated_matches:
                save_schedule(schedule_path, schedule)
        confirmed_results, result_warnings = update_results_from_sources(schedule, confirmed_results, results_cfg)
        summary.warnings.extend(result_warnings)
        if not args.dry_run:
            save_results(results_path, confirmed_results)

    if args.results_only:
        _print_summary(summary)
        return 0

    final_results = {"champion": None, "runner_up": None, "third_place": None}
    ranking, detail = score_predictions(all_predictions, confirmed_results, all_picks, final_results, points_cfg)
    write_workbook(output_path("ranking_polla.xlsx"), ranking, detail, summary.warnings)
    _print_summary(summary)
    return 0


def _print_summary(summary: RunSummary) -> None:
    print("Resumen ejecucion")
    print(f"Pronosticos leidos: {summary.predictions_read}")
    print(f"Cambios detectados: {summary.changes_detected}")
    print(f"Resultados confirmados: {summary.results_confirmed}")
    print(f"Correos preparados: {summary.emails_prepared}")
    for warning in summary.warnings:
        print(f"- {warning}")


if __name__ == "__main__":
    raise SystemExit(main())
