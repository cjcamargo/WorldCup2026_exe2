from __future__ import annotations

import argparse
from datetime import date
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from polla.config import config_path, load_json
from polla.emailer import build_daily_reminder_email, send_messages
from polla.schedule import load_schedule
from polla.timeutils import now_bogota


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Envia el recordatorio diario de partidos y predicciones.")
    parser.add_argument("--dry-run", action="store_true", help="Prepara el correo sin enviarlo.")
    parser.add_argument("--date", help="Fecha opcional YYYY-MM-DD para pruebas.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    target_date = date.fromisoformat(args.date) if args.date else now_bogota().date()
    cfg = load_json(config_path("recordatorios.json"))
    schedule = load_schedule(config_path("calendario_partidos.json"))
    broadcasts = load_json(config_path("televisacion.json")).get("matches", {})
    matches = sorted(
        [match for match in schedule if match.kickoff_at and match.kickoff_at.date() == target_date],
        key=lambda match: match.kickoff_at,
    )

    if not matches and not cfg.get("send_when_no_matches", True):
        print(f"Sin partidos el {target_date.isoformat()}; no se envia recordatorio.")
        return 0

    messages = [
        build_daily_reminder_email(
            recipient=recipient,
            target_date=target_date,
            matches=matches,
            broadcasts=broadcasts,
            cfg=cfg,
        )
        for recipient in cfg.get("to", [])
    ]
    logs = send_messages(messages, cfg, dry_run=args.dry_run)
    print(f"Fecha Bogota: {target_date.isoformat()}")
    print(f"Partidos: {len(matches)}")
    print(f"Destinatarios: {len(messages)}")
    for log in logs:
        print(log)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
