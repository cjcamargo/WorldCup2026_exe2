from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage

from .models import AuditChange


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
    user = os.environ.get(cfg["smtp_user_env"])
    password = os.environ.get(cfg["smtp_password_env"])
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
