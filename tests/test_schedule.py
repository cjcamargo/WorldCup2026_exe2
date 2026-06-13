from datetime import datetime
from zoneinfo import ZoneInfo

from polla.models import MatchResult, Prediction
from polla.schedule import (
    build_expected_matches,
    canonical_team_name,
    merge_group_stage_schedule,
    parse_wikipedia_group_page,
    parse_wikipedia_kickoff,
)


def test_parse_wikipedia_kickoff_to_bogota():
    kickoff = parse_wikipedia_kickoff(2026, 6, 11, "1:00&nbsp;p.m. [[UTC−06:00|UTC−6]]")
    assert kickoff == datetime(2026, 6, 11, 14, 0, tzinfo=ZoneInfo("America/Bogota"))


def test_canonical_team_name_handles_spanish_aliases():
    assert canonical_team_name("REP. CHECA") == "Czech Republic"
    assert canonical_team_name("PAÍSES BAJOS") == "Netherlands"
    assert canonical_team_name("REP. del CONGO") == "DR Congo"


def test_parse_wikipedia_group_page_extracts_matches():
    raw_text = """
===Mexico vs South Africa===
<section begin=A1 />{{#invoke:football box|main
|date={{Start date|2026|6|11}}
|time=1:00&nbsp;p.m. [[UTC−06:00|UTC−6]]
|team1={{#invoke:flag|fb-rt|MEX}}
|score={{score link|2026 FIFA World Cup Group A#Mexico vs South Africa|2–0}}
|team2={{#invoke:flag|fb|RSA}}
===South Korea vs Czech Republic===
<section begin=A2 />{{#invoke:football box|main
|date={{Start date|2026|6|11}}
|time=8:00&nbsp;p.m. [[UTC−06:00|UTC−6]]
|team1={{#invoke:flag|fb-rt|KOR}}
|score={{score link|2026 FIFA World Cup Group A#South Korea vs Czech Republic|2–1}}
|team2={{#invoke:flag|fb|CZE}}
"""
    matches = parse_wikipedia_group_page(raw_text, "Group A", "https://example.test/a")
    assert len(matches) == 2
    assert matches[0].team_a == "Mexico"
    assert matches[0].team_b == "South Africa"
    assert matches[0].kickoff_at == datetime(2026, 6, 11, 14, 0, tzinfo=ZoneInfo("America/Bogota"))
    assert matches[1].kickoff_at == datetime(2026, 6, 11, 21, 0, tzinfo=ZoneInfo("America/Bogota"))


def test_merge_group_stage_schedule_uses_excel_match_ids():
    expected = build_expected_matches([
        Prediction(
            participant="Alex",
            match_id="M001",
            team_a="MÉXICO",
            team_b="SUDÁFRICA",
            goals_a_pred=1,
            goals_b_pred=0,
            phase="Group stage",
        ),
        Prediction(
            participant="Alex",
            match_id="M002",
            team_a="COREA del SUR",
            team_b="REP. CHECA",
            goals_a_pred=2,
            goals_b_pred=1,
            phase="Group stage",
        ),
    ])
    fetched = [
        MatchResult(
            match_id="",
            team_a="Mexico",
            team_b="South Africa",
            phase="Group A",
            kickoff_at=datetime(2026, 6, 11, 14, 0, tzinfo=ZoneInfo("America/Bogota")),
        ),
        MatchResult(
            match_id="",
            team_a="South Korea",
            team_b="Czech Republic",
            phase="Group A",
            kickoff_at=datetime(2026, 6, 11, 21, 0, tzinfo=ZoneInfo("America/Bogota")),
        ),
    ]
    merged, updated = merge_group_stage_schedule([], expected, fetched)
    assert updated == 2
    assert [match.match_id for match in merged] == ["M001", "M002"]
    assert merged[1].team_a == "South Korea"
