from __future__ import annotations

import os
import smtplib
from datetime import date
from email.message import EmailMessage

from .models import AuditChange, MatchResult


def build_group_join_request_email(participant: str, group_name: str, invite_code: str, requested_at: str, cfg: dict) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = f"Polla Mundialista: solicitud para unirse a {group_name}"
    msg["From"] = cfg["from"]
    msg["To"] = _recipients_header(cfg["to"])
    msg.set_content(
        "\n".join([
            "Hay una nueva solicitud para unirse a un grupo.",
            "",
            f"Grupo: {group_name}",
            f"Codigo: {invite_code}",
            f"Usuario solicitante: {participant}",
            f"Fecha/hora: {requested_at}",
            "",
            "Entra a la pestaña Admin de la app para aprobarlo.",
        ])
    )
    return msg


def build_changes_email(changes: list[AuditChange], cfg: dict) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = f"Alerta Polla Mundialista: {len(changes)} cambio(s) detectado(s)"
    msg["From"] = cfg["from"]
    msg["To"] = _recipients_header(cfg["to"])
    lines = [
        "Se detectaron cambios en la polla mundialista.",
        "",
        f"Total cambios: {len(changes)}",
        "",
    ]
    for idx, change in enumerate(changes, start=1):
        lines.extend([
            f"{idx}. {change.participant} - {change.match_id}",
            f"   Campo: {change.field}",
            f"   Valor anterior: {change.old_value}",
            f"   Valor nuevo: {change.new_value}",
            f"   Detectado: {change.detected_at}",
            f"   Estado: {change.status}",
            f"   Motivo: {change.reason or ''}",
            "",
        ])
    msg.set_content("\n".join(lines))
    return msg


def build_daily_reminder_email(
    recipient: str,
    target_date: date,
    matches: list[MatchResult],
    broadcasts: dict[str, list[str]],
    cfg: dict,
) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = f"Polla Mundialista: partidos de hoy {target_date.isoformat()}"
    msg["From"] = cfg["from"]
    msg["To"] = recipient
    lines = [
        "Hola,",
        "",
        f"Estos son los partidos programados para hoy, {target_date.isoformat()}, en hora Bogota:",
        "",
    ]
    if matches:
        for match in matches:
            kickoff = match.kickoff_at.strftime("%H:%M") if match.kickoff_at else "Horario por definir"
            channels = ", ".join(broadcasts.get(match.match_id, [])) or "Televisacion por confirmar"
            lines.extend([
                f"- {kickoff} | {match.team_a} vs {match.team_b}",
                f"  Grupo: {match.phase or 'Sin fase'}",
                f"  TV: {channels}",
            ])
        lines.extend([
            "",
            "Recuerda cargar tus predicciones antes del cierre: 12:00 m o kickoff + 2 minutos, lo que ocurra de ultimo.",
        ])
    else:
        lines.append("Hoy no hay partidos programados en el calendario de la polla.")
    lines.extend([
        "",
        "Ingresa a la app:",
        cfg["app_url"],
        "",
        "Polla Mundialista Exe2",
    ])
    msg.set_content("\n".join(lines))
    return msg


def build_change_email(change: AuditChange, cfg: dict) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = f"Alerta Polla Mundialista: cambio detectado - {change.participant}"
    msg["From"] = cfg["from"]
    msg["To"] = _recipients_header(cfg["to"])
    msg.set_content(
        "\n".join([
            "Se detecto un cambio en la polla mundialista.",
            "",
            f"Participante: {change.participant}",
            f"Partido: {change.match_id}",
            f"Campo: {change.field}",
            f"Valor anterior: {change.old_value}",
            f"Valor nuevo: {change.new_value}",
            f"Detectado: {change.detected_at}",
            f"Estado: {change.status}",
            f"Motivo: {change.reason or ''}",
        ])
    )
    return msg


def send_messages(messages: list[EmailMessage], cfg: dict, dry_run: bool) -> list[str]:
    if not messages:
        return []
    if dry_run or not cfg.get("enabled"):
        return [f"DRY-RUN email: {msg['Subject']} -> {msg['To']}" for msg in messages]
    user = cfg.get("smtp_user") or os.environ.get(cfg["smtp_user_env"])
    password = cfg.get("smtp_password") or os.environ.get(cfg["smtp_password_env"])
    if not user or not password:
        raise RuntimeError("Faltan variables de entorno SMTP para enviar correos.")
    with smtplib.SMTP(cfg["smtp_host"], int(cfg["smtp_port"])) as smtp:
        smtp.starttls()
        smtp.login(user, password)
        for msg in messages:
            smtp.send_message(msg)
    return [f"Email enviado: {msg['Subject']} -> {msg['To']}" for msg in messages]


def _recipients_header(value: str | list[str]) -> str:
    if isinstance(value, list):
        return ", ".join(value)
    return value
