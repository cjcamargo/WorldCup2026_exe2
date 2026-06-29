from datetime import date, datetime

from polla.emailer import build_daily_reminder_email
from polla.models import MatchResult
from polla.timeutils import BOGOTA
from scripts.send_daily_reminder import load_reminder_schedule


def test_reminder_schedule_includes_group_stage_and_knockout_without_duplicates():
    schedule = load_reminder_schedule()
    match_ids = [match.match_id for match in schedule]

    assert "M001" in match_ids
    assert "M073" in match_ids
    assert "M104" in match_ids
    assert len(match_ids) == len(set(match_ids)) == 104


def test_daily_reminder_contains_matches_deadline_channels_and_app_link():
    cfg = {
        "from": "sender@example.com",
        "app_url": "https://worldcup2026exe2.streamlit.app/",
    }
    matches = [
        MatchResult(
            "M001",
            "Colombia",
            "Japan",
            phase="Group A",
            kickoff_at=datetime(2026, 6, 19, 14, 0, tzinfo=BOGOTA),
        )
    ]

    message = build_daily_reminder_email(
        "player@example.com",
        date(2026, 6, 19),
        matches,
        {"M001": ["Caracol TV", "DSports"]},
        cfg,
    )
    body = message.get_content()

    assert message["To"] == "player@example.com"
    assert "14:00 | Colombia vs Japan" in body
    assert "Caracol TV, DSports" in body
    assert "primer kickoff + 1 minuto o 2:00 p. m." in body
    assert "https://worldcup2026exe2.streamlit.app/" in body
