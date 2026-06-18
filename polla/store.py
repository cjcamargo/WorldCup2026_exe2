from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import asdict
from datetime import datetime
from typing import Any, Iterable

from .models import AuditChange, FinalPicks, GroupPick, MatchResult, Prediction, User
from .prediction_rules import prediction_is_locked, prediction_lock_at
from .schedule import canonical_team_name
from .timeutils import as_bogota, parse_datetime


SHEETS = {
    "users": "Users",
    "matches": "Matches",
    "predictions": "Predictions",
    "group_picks": "GroupPicks",
    "final_picks": "FinalPicks",
    "results": "Results",
    "audit": "AuditLog",
    "settings": "Settings",
    "ranking": "Ranking",
    "detail": "Detail",
}

HEADERS = {
    "Users": ["participant", "pin_hash", "role", "active"],
    "Matches": ["match_id", "phase", "team_a", "team_b", "kickoff_at", "status"],
    "Predictions": ["participant", "match_id", "team_a", "team_b", "goals_a_pred", "goals_b_pred", "updated_at"],
    "GroupPicks": ["participant", "group", "first", "second", "third", "updated_at"],
    "FinalPicks": ["participant", "champion", "runner_up", "third_place", "updated_at"],
    "Results": ["match_id", "team_a", "team_b", "goals_a_real", "goals_b_real", "status", "phase", "kickoff_at", "source", "source_url", "confirmed"],
    "AuditLog": ["detected_at", "participant", "match_id", "field", "old_value", "new_value", "status", "reason"],
    "Settings": ["key", "value"],
    "Ranking": ["participant", "points", "rank"],
    "Detail": ["participant", "match_id", "team_a", "team_b", "pred_score", "real_score", "points"],
}


def hash_pin(participant: str, pin: str) -> str:
    payload = f"{participant.strip().casefold()}:{pin}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def verify_pin(participant: str, pin: str, stored_hash: str) -> bool:
    return hmac.compare_digest(hash_pin(participant, pin), stored_hash)


class GoogleSheetsStore:
    def __init__(self, spreadsheet_id: str, credentials: dict[str, Any]):
        import gspread
        from google.oauth2.service_account import Credentials

        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(credentials, scopes=scopes)
        self.client = gspread.authorize(creds)
        self.spreadsheet = self.client.open_by_key(spreadsheet_id)

    def ensure_schema(self) -> None:
        existing = {sheet.title for sheet in self.spreadsheet.worksheets()}
        for title, headers in HEADERS.items():
            if title in existing:
                ws = self.spreadsheet.worksheet(title)
            else:
                ws = self.spreadsheet.add_worksheet(title=title, rows=1000, cols=max(26, len(headers)))
            values = ws.get_all_values()
            if not values:
                ws.update("A1", [headers])
            elif values[0] != headers:
                ws.update("A1", [headers])

    def users(self) -> list[User]:
        return [
            User(
                participant=row["participant"],
                pin_hash=row["pin_hash"],
                role=row.get("role") or "player",
                active=_to_bool(row.get("active"), True),
            )
            for row in self._rows("Users")
            if row.get("participant")
        ]

    def create_user(self, participant: str, pin_hash: str, role: str = "player", active: bool = False) -> None:
        self.spreadsheet.worksheet("Users").append_row(
            [participant, pin_hash, role, _encode(active)],
            value_input_option="USER_ENTERED",
        )

    def update_user_pin(self, participant: str, pin_hash: str) -> None:
        self._update_user_fields(participant, {"pin_hash": pin_hash})

    def set_user_active(self, participant: str, active: bool) -> None:
        self._update_user_fields(participant, {"active": active})

    def matches(self) -> list[MatchResult]:
        out: list[MatchResult] = []
        for row in self._rows("Matches"):
            if not row.get("match_id"):
                continue
            out.append(MatchResult(
                match_id=row["match_id"],
                phase=row.get("phase") or None,
                team_a=canonical_team_name(row["team_a"]),
                team_b=canonical_team_name(row["team_b"]),
                kickoff_at=as_bogota(parse_datetime(row.get("kickoff_at"))),
                status=row.get("status") or "scheduled",
            ))
        return out

    def predictions(self, participant: str | None = None) -> list[Prediction]:
        out: list[Prediction] = []
        for row in self._rows("Predictions"):
            if not row.get("participant") or not row.get("match_id"):
                continue
            if participant and row["participant"] != participant:
                continue
            goals_a = _to_int(row.get("goals_a_pred"))
            goals_b = _to_int(row.get("goals_b_pred"))
            out.append(Prediction(
                participant=row["participant"],
                match_id=row["match_id"],
                team_a=row["team_a"],
                team_b=row["team_b"],
                goals_a_pred=goals_a,
                goals_b_pred=goals_b,
            ))
        return out

    def group_picks(self, participant: str | None = None) -> list[GroupPick]:
        out: list[GroupPick] = []
        for row in self._rows("GroupPicks"):
            if not row.get("participant") or not row.get("group"):
                continue
            if participant and row["participant"] != participant:
                continue
            out.append(GroupPick(
                participant=row["participant"],
                group=row["group"],
                first=row.get("first") or None,
                second=row.get("second") or None,
                third=row.get("third") or None,
            ))
        return out

    def final_picks(self, participant: str | None = None) -> list[FinalPicks]:
        out: list[FinalPicks] = []
        for row in self._rows("FinalPicks"):
            if not row.get("participant"):
                continue
            if participant and row["participant"] != participant:
                continue
            out.append(FinalPicks(
                participant=row["participant"],
                champion=row.get("champion") or None,
                runner_up=row.get("runner_up") or None,
                third_place=row.get("third_place") or None,
            ))
        return out

    def results(self) -> list[MatchResult]:
        out: list[MatchResult] = []
        for row in self._rows("Results"):
            if not row.get("match_id"):
                continue
            out.append(MatchResult(
                match_id=row["match_id"],
                team_a=canonical_team_name(row["team_a"]),
                team_b=canonical_team_name(row["team_b"]),
                goals_a_real=_to_int(row.get("goals_a_real")),
                goals_b_real=_to_int(row.get("goals_b_real")),
                status=row.get("status") or "scheduled",
                phase=row.get("phase") or None,
                kickoff_at=as_bogota(parse_datetime(row.get("kickoff_at"))),
                source=row.get("source") or None,
                source_url=row.get("source_url") or None,
                confirmed=_to_bool(row.get("confirmed"), False),
            ))
        return out

    def settings(self) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for row in self._rows("Settings"):
            if row.get("key"):
                values[row["key"]] = _decode(row.get("value"))
        return values

    def audit_changes_after(self, detected_after: str | None) -> list[AuditChange]:
        changes: list[AuditChange] = []
        for row in self._rows("AuditLog"):
            detected_at = str(row.get("detected_at") or "")
            if not detected_at:
                continue
            if detected_after and detected_at <= detected_after:
                continue
            changes.append(AuditChange(
                detected_at=detected_at,
                participant=str(row.get("participant") or ""),
                match_id=str(row.get("match_id") or ""),
                field=str(row.get("field") or ""),
                old_value=row.get("old_value"),
                new_value=row.get("new_value"),
                status=str(row.get("status") or ""),
                reason=str(row.get("reason") or "") or None,
            ))
        return changes

    def save_prediction(self, participant: str, match: MatchResult, goals_a: int | None, goals_b: int | None, at: datetime) -> None:
        if prediction_is_locked(match, at):
            lock_at = prediction_lock_at(match)
            lock_text = lock_at.strftime("%Y-%m-%d %H:%M") if lock_at else "el cierre"
            raise ValueError(f"Las predicciones de este partido cerraron el {lock_text} hora Bogota.")
        values = {
            "participant": participant,
            "match_id": match.match_id,
            "team_a": match.team_a,
            "team_b": match.team_b,
            "goals_a_pred": goals_a,
            "goals_b_pred": goals_b,
            "updated_at": at.isoformat(),
        }
        self._upsert("Predictions", ["participant", "match_id"], values, participant, match.match_id, at)

    def save_group_pick(self, pick: GroupPick, at: datetime) -> None:
        values = {**asdict(pick), "updated_at": at.isoformat()}
        self._upsert("GroupPicks", ["participant", "group"], values, pick.participant, f"GROUP_{pick.group}", at)

    def save_final_picks(self, picks: FinalPicks, at: datetime) -> None:
        values = {**asdict(picks), "updated_at": at.isoformat()}
        self._upsert("FinalPicks", ["participant"], values, picks.participant, "FINAL_PICKS", at)

    def save_setting(self, key: str, value: Any) -> None:
        ws = self.spreadsheet.worksheet("Settings")
        rows = ws.get_all_records()
        encoded_row = [key, _encode(value)]
        for idx, row in enumerate(rows, start=2):
            if row.get("key") == key:
                ws.update(f"A{idx}", [encoded_row])
                return
        ws.append_row(encoded_row, value_input_option="USER_ENTERED")

    def replace_rows(self, sheet_name: str, rows: list[dict[str, Any]]) -> None:
        headers = HEADERS[sheet_name]
        matrix = [headers]
        for row in rows:
            matrix.append([_encode(row.get(header)) for header in headers])
        ws = self.spreadsheet.worksheet(sheet_name)
        ws.clear()
        ws.update("A1", matrix)

    def append_audit(self, changes: Iterable[AuditChange]) -> None:
        rows = [
            [
                change.detected_at,
                change.participant,
                change.match_id,
                change.field,
                _encode(change.old_value),
                _encode(change.new_value),
                change.status,
                change.reason or "",
            ]
            for change in changes
        ]
        if rows:
            self.spreadsheet.worksheet("AuditLog").append_rows(rows, value_input_option="USER_ENTERED")

    def _rows(self, sheet_name: str) -> list[dict[str, str]]:
        return self.spreadsheet.worksheet(sheet_name).get_all_records()

    def _update_user_fields(self, participant: str, values: dict[str, Any]) -> None:
        ws = self.spreadsheet.worksheet("Users")
        rows = ws.get_all_records()
        headers = HEADERS["Users"]
        for idx, row in enumerate(rows, start=2):
            if row.get("participant") != participant:
                continue
            updated = {**row, **values}
            ws.update(f"A{idx}", [[_encode(updated.get(header)) for header in headers]])
            return
        raise ValueError(f"Usuario no encontrado: {participant}")

    def _upsert(
        self,
        sheet_name: str,
        key_fields: list[str],
        values: dict[str, Any],
        participant: str,
        match_id: str,
        at: datetime,
    ) -> None:
        ws = self.spreadsheet.worksheet(sheet_name)
        rows = ws.get_all_records()
        headers = HEADERS[sheet_name]
        found_idx: int | None = None
        old_row: dict[str, Any] | None = None
        for idx, row in enumerate(rows, start=2):
            if all(str(row.get(field, "")) == str(values.get(field, "")) for field in key_fields):
                found_idx = idx
                old_row = row
                break
        encoded_row = [_encode(values.get(header)) for header in headers]
        if found_idx:
            ws.update(f"A{found_idx}", [encoded_row])
            changes = _row_changes(old_row or {}, values, participant, match_id, at)
        else:
            ws.append_row(encoded_row, value_input_option="USER_ENTERED")
            changes = [AuditChange(at.isoformat(), participant, match_id, "prediction", None, values, "new")]
        self.append_audit(changes)


def _row_changes(old: dict[str, Any], new: dict[str, Any], participant: str, match_id: str, at: datetime) -> list[AuditChange]:
    changes: list[AuditChange] = []
    for field, value in new.items():
        if field == "updated_at":
            continue
        if str(old.get(field, "")) != str(_encode(value)):
            changes.append(AuditChange(at.isoformat(), participant, match_id, field, old.get(field), value, "changed"))
    return changes


def _to_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _to_bool(value: Any, default: bool) -> bool:
    if value in (None, ""):
        return default
    return str(value).strip().casefold() in {"true", "1", "yes", "si", "sí"}


def _encode(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _decode(value: Any) -> Any:
    if value in (None, ""):
        return None
    text = str(value)
    if text[:1] in {"{", "["}:
        return json.loads(text)
    if text.casefold() in {"true", "false"}:
        return text.casefold() == "true"
    return text
