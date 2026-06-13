from polla.store import hash_pin, verify_pin


def test_pin_hash_is_participant_scoped():
    alex_hash = hash_pin("Alex", "1234")
    assert verify_pin("Alex", "1234", alex_hash)
    assert not verify_pin("Alex", "9999", alex_hash)
    assert not verify_pin("CarlosF", "1234", alex_hash)
