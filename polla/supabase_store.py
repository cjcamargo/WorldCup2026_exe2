from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Any

from .models import AuditChange, FinalPicks, GroupPick, MatchResult, Prediction, User
from .schedule import canonical_team_name
from .timeutils import as_bogota, parse_datetime


class SupabaseStore:
    def __init__(self, url: str, key: str):
        from supabase import create_client

        self.client = create_client(url, key)

    def ensure_schema(self) -> None:
        return

    def users(self) -> list[User]:
        rows = self._select("users")
        return [
            User(
                participant=row["participant"],
                pin_hash=row["pin_hash"],
                role=row.get("role") or "player",
                active=bool(row.get("active", True)),
            )
            for row in rows
        ]

    def matches(self) -> list[MatchResult]:
        rows = self._select("matches", order="match_id")
        return [
            MatchResult(
                match_id=row["match_id"],
                phase=row.get("phase"),
                team_a=canonical_team_name(row["team_a"]),
                team_b=canonical_team_name(row["team_b"]),
                kickoff_at=as_bogota(parse_datetime(row.get("kickoff_at"))),
                status=row.get("status") or "scheduled",
            )
            for row in rows
        ]

    def predictions(self, participant: str | None = None) -> list[Prediction]:
        query = self.client.table("predictions").select("*")
        if participant:
            query = query.eq("participant", participant)
        rows = query.execute().data or []
        return [
            Prediction(
                participant=row["participant"],
                match_id=row["match_id"],
                team_a=row["team_a"],
                team_b=row["team_b"],
                goals_a_pred=row.get("goals_a_pred"),
                goals_b_pred=row.get("goals_b_pred"),
            )
            for row in rows
        ]

    def group_picks(self, participant: str | None = None) -> list[GroupPick]:
        query = self.client.table("group_picks").select("*")
        if participant:
            query = query.eq("participant", participant)
        rows = query.execute().data or []
        return [
            GroupPick(
                participant=row["participant"],
                group=row["group"],
                first=row.get("first"),
                second=row.get("second"),
                third=row.get("third"),
            )
            for row in rows
        ]

    def final_picks(self, participant: str | None = None) -> list[FinalPicks]:
        query = self.client.table("final_picks").select("*")
        if participant:
            query = query.eq("participant", participant)
        rows = query.execute().data or []
        return [
            FinalPicks(
                participant=row["participant"],
                champion=row.get("champion"),
                runner_up=row.get("runner_up"),
                third_place=row.get("third_place"),
            )
            for row in rows
        ]

    def results(self) -> list[MatchResult]:
        rows = self._select("results", order="match_id")
        return [
            MatchResult(
                match_id=row["match_id"],
                team_a=canonical_team_name(row["team_a"]),
                team_b=canonical_team_name(row["team_b"]),
                goals_a_real=row.get("goals_a_real"),
                goals_b_real=row.get("goals_b_real"),
                status=row.get("status") or "scheduled",
                phase=row.get("phase"),
                kickoff_at=as_bogota(parse_datetime(row.get("kickoff_at"))),
                source=row.get("source"),
                source_url=row.get("source_url"),
                confirmed=bool(row.get("confirmed", False)),
            )
            for row in rows
        ]

    def settings(self) -> dict[str, Any]:
        return {row["key"]: _decode(row.get("value")) for row in self._select("settings") if row.get("key")}

    def audit_changes_after(self, detected_after: str | None) -> list[AuditChange]:
        query = self.client.table("audit_log").select("*").order("detected_at")
        if detected_after:
            query = query.gt("detected_at", detected_after)
        rows = query.execute().data or []
        return [
            AuditChange(
                detected_at=row["detected_at"],
                participant=row["participant"],
                match_id=row["match_id"],
                field=row["field"],
                old_value=row.get("old_value"),
                new_value=row.get("new_value"),
                status=row["status"],
                reason=row.get("reason"),
            )
            for row in rows
        ]

    def save_prediction(self, participant: str, match: MatchResult, goals_a: int | None, goals_b: int | None, at: datetime) -> None:
        if match.kickoff_at and at >= match.kickoff_at:
            raise ValueError("Este partido ya inicio y no puede editarse.")
        values = {
            "participant": participant,
            "match_id": match.match_id,
            "team_a": match.team_a,
            "team_b": match.team_b,
            "goals_a_pred": goals_a,
            "goals_b_pred": goals_b,
            "updated_at": at.isoformat(),
        }
        old = self._one("predictions", {"participant": participant, "match_id": match.match_id})
        self.client.table("predictions").upsert(values).execute()
        self._audit_upsert(old, values, participant, match.match_id, at)

    def save_group_pick(self, pick: GroupPick, at: datetime) -> None:
        values = {**asdict(pick), "updated_at": at.isoformat()}
        old = self._one("group_picks", {"participant": pick.participant, "group": pick.group})
        self.client.table("group_picks").upsert(values).execute()
        self._audit_upsert(old, values, pick.participant, f"GROUP_{pick.group}", at)

    def save_final_picks(self, picks: FinalPicks, at: datetime) -> None:
        values = {**asdict(picks), "updated_at": at.isoformat()}
        old = self._one("final_picks", {"participant": picks.participant})
        self.client.table("final_picks").upsert(values).execute()
        self._audit_upsert(old, values, picks.participant, "FINAL_PICKS", at)

    def save_setting(self, key: str, value: Any) -> None:
        self.client.table("settings").upsert({"key": key, "value": _encode(value)}).execute()

    def replace_rows(self, table_name: str, rows: list[dict[str, Any]]) -> None:
        table = _table_name(table_name)
        self.client.table(table).delete().neq(_delete_filter_column(table), "__never__").execute()
        if rows:
            self.client.table(table).insert([_clean_row(row) for row in rows]).execute()

    def append_audit(self, changes: list[AuditChange]) -> None:
        if not changes:
            return
        self.client.table("audit_log").insert([
            {
                "detected_at": change.detected_at,
                "participant": change.participant,
                "match_id": change.match_id,
                "field": change.field,
                "old_value": _encode(change.old_value),
                "new_value": _encode(change.new_value),
                "status": change.status,
                "reason": change.reason,
            }
            for change in changes
        ]).execute()

    def _select(self, table: str, order: str | None = None) -> list[dict[str, Any]]:
        query = self.client.table(table).select("*")
        if order:
            query = query.order(order)
        return query.execute().data or []

    def _one(self, table: str, filters: dict[str, Any]) -> dict[str, Any] | None:
        query = self.client.table(table).select("*")
        for key, value in filters.items():
            query = query.eq(key, value)
        rows = query.limit(1).execute().data or []
        return rows[0] if rows else None

    def _audit_upsert(self, old: dict[str, Any] | None, new: dict[str, Any], participant: str, match_id: str, at: datetime) -> None:
        if old is None:
            self.append_audit([AuditChange(at.isoformat(), participant, match_id, "prediction", None, new, "new")])
            return
        changes: list[AuditChange] = []
        for field, value in new.items():
            if field == "updated_at":
                continue
            if str(old.get(field, "")) != str(value or ""):
                changes.append(AuditChange(at.isoformat(), participant, match_id, field, old.get(field), value, "changed"))
        self.append_audit(changes)


def _table_name(name: str) -> str:
    return {
        "Users": "users",
        "Matches": "matches",
        "Predictions": "predictions",
        "GroupPicks": "group_picks",
        "FinalPicks": "final_picks",
        "Results": "results",
        "AuditLog": "audit_log",
        "Settings": "settings",
        "Ranking": "ranking",
        "Detail": "detail",
        "users": "users",
        "matches": "matches",
        "predictions": "predictions",
        "group_picks": "group_picks",
        "final_picks": "final_picks",
        "results": "results",
        "audit_log": "audit_log",
        "settings": "settings",
        "ranking": "ranking",
        "detail": "detail",
    }[name]


def _delete_filter_column(table: str) -> str:
    if table in {"audit_log", "detail"}:
        return "id"
    return {
        "users": "participant",
        "matches": "match_id",
        "predictions": "participant",
        "group_picks": "participant",
        "final_picks": "participant",
        "results": "match_id",
        "settings": "key",
        "ranking": "participant",
    }.get(table, "id")


def _clean_row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if value is not None}


def _encode(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        import json
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _decode(value: Any) -> Any:
    if value in (None, ""):
        return None
    text = str(value)
    if text.casefold() in {"true", "false"}:
        return text.casefold() == "true"
    return text
