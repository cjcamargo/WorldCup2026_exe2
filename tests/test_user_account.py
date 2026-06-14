from types import SimpleNamespace

from app import _clean_invite_code, _group_creation_error, _pin_update_error, _registration_error, _username_suggestions
from polla.emailer import build_group_join_request_email
from polla.store import hash_pin


def test_registration_rejects_duplicate_case_insensitive():
    users = [SimpleNamespace(participant="CarlosF")]

    error = _registration_error("carlosf", "1234", "1234", users)

    assert error


def test_registration_accepts_new_user():
    users = [SimpleNamespace(participant="CarlosF")]

    error = _registration_error("Nuevo", "1234", "1234", users)

    assert error is None


def test_pin_update_requires_current_pin():
    stored_hash = hash_pin("CarlosF", "1234")

    error = _pin_update_error("CarlosF", "9999", "5678", "5678", stored_hash)

    assert error


def test_pin_update_accepts_valid_change():
    stored_hash = hash_pin("CarlosF", "1234")

    error = _pin_update_error("CarlosF", "1234", "5678", "5678", stored_hash)

    assert error is None


def test_username_suggestions_skip_existing_names():
    users = [
        SimpleNamespace(participant="CarlosF"),
        SimpleNamespace(participant="CarlosF2"),
    ]

    suggestions = _username_suggestions("CarlosF", users)

    assert "CarlosF2" not in suggestions
    assert suggestions


def test_group_creation_rejects_duplicate_code():
    groups = [SimpleNamespace(invite_code="EXE2")]

    error = _group_creation_error("Exe2 nuevo", "EXE2", groups)

    assert error


def test_clean_invite_code_from_group_name():
    assert _clean_invite_code("Polla Familia 2026") == "POLLA-FAMILIA-2026"


def test_group_join_request_email_contains_request_details():
    cfg = {"from": "from@example.com", "to": ["admin@example.com"]}

    msg = build_group_join_request_email("Nuevo", "Exe2", "EXE2", "2026-06-14T10:00:00", cfg)

    body = msg.get_content()
    assert msg["To"] == "admin@example.com"
    assert "Nuevo" in body
    assert "Exe2" in body
    assert "EXE2" in body
