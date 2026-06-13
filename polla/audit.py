from __future__ import annotations

import csv
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import load_json, save_json
from .models import AuditChange, MatchResult, Prediction


AUDIT_FIELDS = ["goals_a_pred", "goals_b_pred", "winner_pred"]


def prediction_key(pred: Prediction) -> str:
    return f"{pred.participant}|{pred.match_id}|{pred.team_a}|{pred.team_b}"


def predictions_to_snapshot(predictions: list[Prediction]) -> dict[str, Any]:
    return {prediction_key(pred): asdict(pred) for pred in predictions}


def load_snapshot(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return load_json(path)


def detect_changes(previous: dict[str, Any], current: dict[str, Any], detected_at: str) -> list[AuditChange]:
    if not previous:
        return []

    changes: list[AuditChange] = []
    for key, row in current.items():
        old = previous.get(key)
        if old is None:
            changes.append(AuditChange(
                detected_at=detected_at,
                participant=row["participant"],
                match_id=row["match_id"],
                field="prediction",
                old_value=None,
                new_value={field: row.get(field) for field in AUDIT_FIELDS},
                status="new",
            ))
            continue
        for field in AUDIT_FIELDS:
            if old.get(field) != row.get(field):
                changes.append(AuditChange(
                    detected_at=detected_at,
                    participant=row["participant"],
                    match_id=row["match_id"],
                    field=field,
                    old_value=old.get(field),
                    new_value=row.get(field),
                    status="changed",
                ))
    return changes


def apply_deadline_policy(
    predictions: list[Prediction],
    changes: list[AuditChange],
    schedule: list[MatchResult],
    at: datetime,
) -> tuple[list[Prediction], list[AuditChange]]:
    kickoff_by_match = {match.match_id: match.kickoff_at for match in schedule if match.kickoff_at}
    late_keys: set[tuple[str, str]] = set()
    updated_changes: list[AuditChange] = []
    for change in changes:
        kickoff = kickoff_by_match.get(change.match_id)
        if kickoff and at >= kickoff:
            late_keys.add((change.participant, change.match_id))
            updated_changes.append(AuditChange(
                detected_at=change.detected_at,
                participant=change.participant,
                match_id=change.match_id,
                field=change.field,
                old_value=change.old_value,
                new_value=change.new_value,
                status="invalid",
                reason=f"Cambio detectado despues del cierre: {kickoff.isoformat()}",
            ))
        else:
            updated_changes.append(change)
    if not late_keys:
        return predictions, updated_changes
    guarded: list[Prediction] = []
    for pred in predictions:
        if (pred.participant, pred.match_id) in late_keys:
            guarded.append(Prediction(
                participant=pred.participant,
                match_id=pred.match_id,
                team_a=pred.team_a,
                team_b=pred.team_b,
                goals_a_pred=pred.goals_a_pred,
                goals_b_pred=pred.goals_b_pred,
                winner_pred=pred.winner_pred,
                phase=pred.phase,
                source_sheet=pred.source_sheet,
                source_row=pred.source_row,
                valid=False,
                invalid_reason="Cambio tardio detectado por auditoria",
            ))
        else:
            guarded.append(pred)
    return guarded, updated_changes


def save_snapshot(path: Path, snapshot: dict[str, Any]) -> None:
    save_json(path, snapshot)


def append_audit_csv(path: Path, changes: list[AuditChange]) -> None:
    if not changes:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    with path.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(asdict(changes[0]).keys()))
        if not exists:
            writer.writeheader()
        for change in changes:
            writer.writerow(asdict(change))
