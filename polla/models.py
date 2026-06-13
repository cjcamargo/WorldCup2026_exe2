from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class Prediction:
    participant: str
    match_id: str
    team_a: str
    team_b: str
    goals_a_pred: int | None
    goals_b_pred: int | None
    winner_pred: str | None = None
    phase: str | None = None
    source_sheet: str | None = None
    source_row: int | None = None
    valid: bool = True
    invalid_reason: str | None = None


@dataclass(frozen=True)
class FinalPicks:
    participant: str
    champion: str | None = None
    runner_up: str | None = None
    third_place: str | None = None


@dataclass(frozen=True)
class GroupPick:
    participant: str
    group: str
    first: str | None = None
    second: str | None = None
    third: str | None = None


@dataclass(frozen=True)
class User:
    participant: str
    pin_hash: str
    role: str = "player"
    active: bool = True


@dataclass(frozen=True)
class MatchResult:
    match_id: str
    team_a: str
    team_b: str
    goals_a_real: int | None = None
    goals_b_real: int | None = None
    status: str = "scheduled"
    phase: str | None = None
    kickoff_at: datetime | None = None
    source: str | None = None
    source_url: str | None = None
    confirmed: bool = False


@dataclass(frozen=True)
class AuditChange:
    detected_at: str
    participant: str
    match_id: str
    field: str
    old_value: Any
    new_value: Any
    status: str
    reason: str | None = None


@dataclass
class RunSummary:
    predictions_read: int = 0
    changes_detected: int = 0
    results_confirmed: int = 0
    emails_prepared: int = 0
    warnings: list[str] = field(default_factory=list)
