from types import SimpleNamespace

from app import _pin_update_error, _registration_error
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
