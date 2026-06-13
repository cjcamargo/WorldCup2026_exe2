from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from polla.config import config_path, load_json
from polla.models import FinalPicks, GroupPick, MatchResult
from polla.scoring import score_all
from polla.store import verify_pin
from polla.supabase_store import SupabaseStore
from polla.timeutils import BOGOTA, now_bogota


st.set_page_config(page_title="Polla Mundialista", page_icon="1:2", layout="wide")


LOGO_PATH = Path(__file__).parent / "assets" / "exe2_logo.svg"


TEAM_FLAGS = {
    "Algeria": "🇩🇿",
    "Argentina": "🇦🇷",
    "Australia": "🇦🇺",
    "Austria": "🇦🇹",
    "Belgium": "🇧🇪",
    "Bosnia and Herzegovina": "🇧🇦",
    "Brazil": "🇧🇷",
    "Cabo Verde": "🇨🇻",
    "Canada": "🇨🇦",
    "Colombia": "🇨🇴",
    "Croatia": "🇭🇷",
    "Curaçao": "🇨🇼",
    "Czech Republic": "🇨🇿",
    "Côte d'Ivoire": "🇨🇮",
    "DR Congo": "🇨🇩",
    "Ecuador": "🇪🇨",
    "Egypt": "🇪🇬",
    "England": "🏴",
    "France": "🇫🇷",
    "Germany": "🇩🇪",
    "Ghana": "🇬🇭",
    "Haiti": "🇭🇹",
    "IR Iran": "🇮🇷",
    "Iraq": "🇮🇶",
    "Japan": "🇯🇵",
    "Jordan": "🇯🇴",
    "Mexico": "🇲🇽",
    "Morocco": "🇲🇦",
    "Netherlands": "🇳🇱",
    "New Zealand": "🇳🇿",
    "Norway": "🇳🇴",
    "Panama": "🇵🇦",
    "Paraguay": "🇵🇾",
    "Portugal": "🇵🇹",
    "Qatar": "🇶🇦",
    "Saudi Arabia": "🇸🇦",
    "Scotland": "🏴",
    "Senegal": "🇸🇳",
    "South Africa": "🇿🇦",
    "South Korea": "🇰🇷",
    "Spain": "🇪🇸",
    "Sweden": "🇸🇪",
    "Switzerland": "🇨🇭",
    "Tunisia": "🇹🇳",
    "Türkiye": "🇹🇷",
    "United States": "🇺🇸",
    "Uruguay": "🇺🇾",
    "Uzbekistan": "🇺🇿",
}


@st.cache_resource(ttl=300)
def get_store() -> SupabaseStore:
    supabase_cfg = st.secrets.get("supabase", {})
    url = supabase_cfg.get("url")
    key = supabase_cfg.get("service_role_key")
    if not url or not key:
        st.error("Faltan secrets de Supabase. Configura supabase.url y supabase.service_role_key.")
        st.stop()
    store = SupabaseStore(url, key)
    store.ensure_schema()
    return store


@st.cache_data(ttl=60)
def load_state() -> dict[str, Any]:
    store = get_store()
    return {
        "users": store.users(),
        "matches": store.matches(),
        "predictions": store.predictions(),
        "group_picks": store.group_picks(),
        "final_picks": store.final_picks(),
        "results": store.results(),
        "settings": store.settings(),
        "points": load_json(config_path("puntajes.json")),
    }


def main() -> None:
    inject_styles()
    render_header()
    if "participant" not in st.session_state:
        login()
        return

    state = load_state()
    participant = st.session_state["participant"]
    role = st.session_state["role"]
    session_col, exit_col = st.columns([1, 0.18], vertical_alignment="center")
    session_col.caption(f"Sesión: {participant}")
    if exit_col.button("Salir", type="secondary", use_container_width=True):
        st.session_state.clear()
        st.rerun()

    tabs = ["Mis marcadores", "Top 3 grupos", "Finales", "Ranking", "Detalle"]
    if role == "admin":
        tabs.append("Admin")
    rendered_tabs = st.tabs(tabs)
    with rendered_tabs[0]:
        match_predictions_view(participant, state)
    with rendered_tabs[1]:
        group_picks_view(participant, state)
    with rendered_tabs[2]:
        final_picks_view(participant, state)
    with rendered_tabs[3]:
        ranking_view(state)
    with rendered_tabs[4]:
        detail_view(state)
    if role == "admin":
        with rendered_tabs[5]:
            admin_view(state)


def render_header() -> None:
    logo_svg = LOGO_PATH.read_text(encoding="utf-8")
    st.markdown(
        f"""
        <section class="app-hero">
          <div class="hero-logo">{logo_svg}</div>
          <div class="hero-copy">
            <h1>Polla Mundialista Exe2</h1>
            <p>Pronósticos, ranking y resultados en una sola cancha.</p>
          </div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def login() -> None:
    state = load_state()
    active_users = [user for user in state["users"] if user.active]
    names = [user.participant for user in active_users]
    with st.form("login"):
        participant = st.selectbox("Usuario", names)
        pin = st.text_input("PIN", type="password")
        submitted = st.form_submit_button("Entrar")
    if not submitted:
        return
    user = next((item for item in active_users if item.participant == participant), None)
    if not user or not verify_pin(participant, pin, user.pin_hash):
        st.error("Usuario o PIN inválido.")
        return
    st.session_state["participant"] = user.participant
    st.session_state["role"] = user.role
    st.rerun()


def match_predictions_view(participant: str, state: dict[str, Any]) -> None:
    store = get_store()
    now = now_bogota()
    predictions = {(pred.participant, pred.match_id): pred for pred in state["predictions"]}
    matches_by_phase: dict[str, list[MatchResult]] = defaultdict(list)
    for match in state["matches"]:
        matches_by_phase[match.phase or "Sin fase"].append(match)

    phases = sorted(matches_by_phase)
    selected_phase = st.selectbox("Grupo o fase", phases, key="match_phase_filter")
    selected_matches = sorted(matches_by_phase[selected_phase], key=lambda item: item.kickoff_at or datetime.max.replace(tzinfo=BOGOTA))
    participant_predictions = [pred for pred in state["predictions"] if pred.participant == participant]
    saved_count = len({pred.match_id for pred in participant_predictions if pred.goals_a_pred is not None and pred.goals_b_pred is not None})
    open_count = sum(1 for match in state["matches"] if not match.kickoff_at or now < match.kickoff_at)
    locked_count = len(state["matches"]) - open_count

    metric_cols = st.columns(3)
    metric_cols[0].metric("Marcadores guardados", saved_count)
    metric_cols[1].metric("Partidos abiertos", open_count)
    metric_cols[2].metric("Partidos cerrados", locked_count)

    grid = st.columns(2)
    for idx, match in enumerate(selected_matches):
        with grid[idx % 2]:
            _match_prediction_card(store, participant, match, predictions.get((participant, match.match_id)), now)


def group_picks_view(participant: str, state: dict[str, Any]) -> None:
    store = get_store()
    settings = state["settings"]
    picks = {(pick.participant, pick.group): pick for pick in state["group_picks"]}
    teams_by_group = _teams_by_group(state["matches"])
    for group, teams in sorted(teams_by_group.items()):
        closed = bool(settings.get(f"group_closed_{group}", False))
        current = picks.get((participant, group), GroupPick(participant, group))
        st.subheader(group)
        if closed:
            st.info("Este grupo está cerrado por admin.")
        with st.form(f"group_{group}"):
            first = st.selectbox("1°", [""] + teams, index=_index([""] + teams, current.first), disabled=closed, key=f"{group}_first")
            second_options = [""] + [team for team in teams if team != first]
            second = st.selectbox("2°", second_options, index=_index(second_options, current.second), disabled=closed, key=f"{group}_second")
            third_options = [""] + [team for team in teams if team not in {first, second}]
            third = st.selectbox("3°", third_options, index=_index(third_options, current.third), disabled=closed, key=f"{group}_third")
            submitted = st.form_submit_button("Guardar Top 3", disabled=closed)
        if submitted:
            store.save_group_pick(GroupPick(participant, group, first or None, second or None, third or None), now_bogota())
            load_state.clear()
            st.success("Top 3 guardado.")
            st.rerun()


def final_picks_view(participant: str, state: dict[str, Any]) -> None:
    store = get_store()
    closed = bool(state["settings"].get("final_picks_closed", False))
    teams = sorted({match.team_a for match in state["matches"]} | {match.team_b for match in state["matches"]})
    current = next((pick for pick in state["final_picks"] if pick.participant == participant), FinalPicks(participant))
    if closed:
        st.info("Los picks finales están cerrados por admin.")
    with st.form("final_picks"):
        champion = st.selectbox("Campeón", [""] + teams, index=_index([""] + teams, current.champion), disabled=closed)
        runner_options = [""] + [team for team in teams if team != champion]
        runner_up = st.selectbox("Subcampeón", runner_options, index=_index(runner_options, current.runner_up), disabled=closed)
        third_options = [""] + [team for team in teams if team not in {champion, runner_up}]
        third_place = st.selectbox("Tercer puesto", third_options, index=_index(third_options, current.third_place), disabled=closed)
        submitted = st.form_submit_button("Guardar finales", disabled=closed)
    if submitted:
        store.save_final_picks(FinalPicks(participant, champion or None, runner_up or None, third_place or None), now_bogota())
        load_state.clear()
        st.success("Picks finales guardados.")
        st.rerun()


def ranking_view(state: dict[str, Any]) -> None:
    ranking, _detail = _score_state(state)
    if not ranking:
        st.info("Todavía no hay puntos calculados.")
        return
    st.dataframe(pd.DataFrame(ranking), hide_index=True, use_container_width=True)


def detail_view(state: dict[str, Any]) -> None:
    _ranking, detail = _score_state(state)
    if not detail:
        st.info("Todavía no hay detalle de puntos.")
        return
    st.dataframe(pd.DataFrame(detail), hide_index=True, use_container_width=True)


def admin_view(state: dict[str, Any]) -> None:
    store = get_store()
    st.subheader("Cierres manuales")
    teams_by_group = _teams_by_group(state["matches"])
    for group in sorted(teams_by_group):
        key = f"group_closed_{group}"
        new_value = st.toggle(f"Cerrar Top 3 {group}", value=bool(state["settings"].get(key, False)))
        if new_value != bool(state["settings"].get(key, False)):
            store.save_setting(key, new_value)
            load_state.clear()
            st.rerun()
    final_closed = st.toggle("Cerrar campeón/subcampeón/tercero", value=bool(state["settings"].get("final_picks_closed", False)))
    if final_closed != bool(state["settings"].get("final_picks_closed", False)):
        store.save_setting("final_picks_closed", final_closed)
        load_state.clear()
        st.rerun()

    st.subheader("Resultados finales reales")
    teams = sorted({match.team_a for match in state["matches"]} | {match.team_b for match in state["matches"]})
    with st.form("actual_finals"):
        actual_champion = st.selectbox("Campeón real", [""] + teams, index=_index([""] + teams, state["settings"].get("actual_champion")))
        runner_options = [""] + [team for team in teams if team != actual_champion]
        actual_runner_up = st.selectbox("Subcampeón real", runner_options, index=_index(runner_options, state["settings"].get("actual_runner_up")))
        third_options = [""] + [team for team in teams if team not in {actual_champion, actual_runner_up}]
        actual_third_place = st.selectbox("Tercer puesto real", third_options, index=_index(third_options, state["settings"].get("actual_third_place")))
        submitted = st.form_submit_button("Guardar resultados finales reales")
    if submitted:
        store.save_setting("actual_champion", actual_champion or "")
        store.save_setting("actual_runner_up", actual_runner_up or "")
        store.save_setting("actual_third_place", actual_third_place or "")
        load_state.clear()
        st.success("Resultados finales reales guardados.")
        st.rerun()

    st.subheader("Publicar ranking")
    if st.button("Recalcular y guardar ranking"):
        ranking, detail = _score_state(state)
        store.replace_rows("Ranking", ranking)
        store.replace_rows("Detail", _fit_detail_rows(detail))
        load_state.clear()
        st.success("Ranking guardado en Supabase.")


def _score_state(state: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    return score_all(
        state["predictions"],
        state["results"],
        state["final_picks"],
        {
            "champion": state["settings"].get("actual_champion") or None,
            "runner_up": state["settings"].get("actual_runner_up") or None,
            "third_place": state["settings"].get("actual_third_place") or None,
        },
        state["group_picks"],
        state["matches"],
        state["points"],
    )


def _match_prediction_card(
    store: SupabaseStore,
    participant: str,
    match: MatchResult,
    pred: Any,
    now: datetime,
) -> None:
    locked = bool(match.kickoff_at and now >= match.kickoff_at)
    caption = match.kickoff_at.strftime("%Y-%m-%d %H:%M") if match.kickoff_at else "Horario por definir"
    status = "Cerrado" if locked else "Abierto"
    with st.container(border=True):
        st.markdown(
            f"""
            <div class="match-head">
              <span class="match-id">{match.match_id}</span>
              <span class="match-status {'locked' if locked else 'open'}">{status}</span>
            </div>
            <div class="match-title">
              <span>{_team_label(match.team_a)}</span>
              <span class="versus">vs</span>
              <span>{_team_label(match.team_b)}</span>
            </div>
            <div class="match-time">{caption}</div>
            """,
            unsafe_allow_html=True,
        )
        with st.form(f"pred_{match.match_id}"):
            col_a, col_b, col_save = st.columns([1, 1, 0.9], vertical_alignment="bottom")
            goals_a = col_a.number_input(
                _team_label(match.team_a),
                min_value=0,
                max_value=20,
                value=_default_int(pred.goals_a_pred if pred else None),
                step=1,
                disabled=locked,
                key=f"{match.match_id}_a",
            )
            goals_b = col_b.number_input(
                _team_label(match.team_b),
                min_value=0,
                max_value=20,
                value=_default_int(pred.goals_b_pred if pred else None),
                step=1,
                disabled=locked,
                key=f"{match.match_id}_b",
            )
            submitted = col_save.form_submit_button("Guardar", disabled=locked, use_container_width=True)
        if submitted:
            try:
                store.save_prediction(participant, match, int(goals_a), int(goals_b), now)
                load_state.clear()
                st.success("Marcador guardado.")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))


def _teams_by_group(matches: list[MatchResult]) -> dict[str, list[str]]:
    groups: dict[str, set[str]] = defaultdict(set)
    for match in matches:
        if match.phase and "group" in match.phase.casefold():
            groups[match.phase].update([match.team_a, match.team_b])
    return {group: sorted(teams) for group, teams in groups.items()}


def _team_label(team: str) -> str:
    return f"{TEAM_FLAGS.get(team, '🏳️')} {team}"


def _default_int(value: int | None) -> int:
    return int(value) if value is not None else 0


def _index(options: list[str], value: str | None) -> int:
    return options.index(value) if value in options else 0


def _fit_detail_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    headers = ["participant", "match_id", "team_a", "team_b", "pred_score", "real_score", "points"]
    return [{header: row.get(header, "") for header in headers} for row in rows]


def inject_styles() -> None:
    st.markdown(
        """
        <style>
        :root {
            --exe-yellow: #fcd116;
            --exe-blue: #003893;
            --exe-red: #ce1126;
            --exe-ink: #071b3a;
            --exe-grass: #0f7a45;
            --exe-surface: #ffffff;
            --exe-border: #d7e0ea;
        }
        .stApp {
            background:
                linear-gradient(90deg, rgba(255,255,255,0.32) 1px, transparent 1px),
                linear-gradient(180deg, rgba(255,255,255,0.24) 1px, transparent 1px),
                linear-gradient(135deg, #f7faf8 0%, #edf7f0 44%, #f8fafc 100%);
            background-size: 44px 44px, 44px 44px, auto;
            color: var(--exe-ink);
        }
        .block-container {
            max-width: 1280px;
            padding-top: 2rem;
            padding-bottom: 3rem;
        }
        .app-hero {
            display: grid;
            grid-template-columns: minmax(220px, 360px) 1fr;
            align-items: center;
            gap: 1.6rem;
            margin-bottom: 1rem;
            padding: 1rem;
            border-radius: 12px;
            background:
                linear-gradient(90deg, rgba(7,27,58,0.94), rgba(0,56,147,0.88)),
                repeating-linear-gradient(90deg, transparent 0 42px, rgba(255,255,255,0.09) 42px 44px);
            border: 1px solid rgba(255,255,255,0.36);
            box-shadow: 0 18px 42px rgba(7, 27, 58, 0.18);
        }
        .hero-logo svg {
            display: block;
            width: min(100%, 360px);
            height: auto;
            border-radius: 18px;
            box-shadow: 0 16px 34px rgba(0,0,0,0.22);
        }
        .hero-copy h1 {
            margin: 0;
            color: #ffffff;
            font-size: clamp(2rem, 4vw, 4.6rem);
            line-height: 0.98;
            font-weight: 900;
        }
        .hero-copy p {
            margin: 0.8rem 0 0;
            color: #fff4b8;
            font-size: 1.08rem;
            font-weight: 650;
        }
        .stTabs [data-baseweb="tab-list"] {
            gap: 0.35rem;
            border-bottom: 3px solid var(--exe-yellow);
        }
        .stTabs [data-baseweb="tab"] {
            border-radius: 8px 8px 0 0;
            color: var(--exe-ink);
            font-weight: 750;
        }
        .stTabs [aria-selected="true"] {
            background: var(--exe-blue);
            color: #ffffff;
        }
        .stButton > button,
        .stFormSubmitButton > button {
            border-radius: 8px;
            border: 1px solid #d3ab00;
            background: var(--exe-yellow);
            color: var(--exe-ink);
            font-weight: 800;
        }
        .stButton > button:hover,
        .stFormSubmitButton > button:hover {
            border-color: var(--exe-blue);
            color: var(--exe-blue);
        }
        div[data-testid="stMetric"] {
            background: rgba(255,255,255,0.92);
            border: 1px solid var(--exe-border);
            border-radius: 8px;
            padding: 0.7rem 0.85rem;
            box-shadow: 0 8px 20px rgba(7,27,58,0.06);
        }
        div[data-testid="stVerticalBlockBorderWrapper"] {
            border-color: var(--exe-border);
            box-shadow: 0 10px 22px rgba(7,27,58,0.07);
            background: rgba(255,255,255,0.96);
        }
        .match-head {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 0.75rem;
            margin-bottom: 0.4rem;
        }
        .match-id {
            color: var(--exe-blue);
            font-size: 0.78rem;
            font-weight: 700;
        }
        .match-status {
            border-radius: 999px;
            font-size: 0.72rem;
            font-weight: 700;
            padding: 0.16rem 0.5rem;
        }
        .match-status.open {
            background: #dcfce7;
            color: #166534;
        }
        .match-status.locked {
            background: #fee2e2;
            color: var(--exe-red);
        }
        .match-title {
            display: grid;
            grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
            align-items: center;
            gap: 0.45rem;
            font-size: 0.98rem;
            font-weight: 750;
            line-height: 1.2;
        }
        .match-title span {
            min-width: 0;
            overflow-wrap: anywhere;
        }
        .match-title span:last-child {
            text-align: right;
        }
        .versus {
            color: var(--exe-red);
            font-size: 0.75rem;
            text-transform: uppercase;
            font-weight: 900;
        }
        .match-time {
            color: #64748b;
            font-size: 0.8rem;
            margin: 0.35rem 0 0.55rem;
        }
        @media (max-width: 760px) {
            .app-hero {
                grid-template-columns: 1fr;
                gap: 1rem;
            }
            .hero-copy h1 {
                font-size: 2.2rem;
            }
            .match-title {
                grid-template-columns: 1fr;
            }
            .match-title span:last-child {
                text-align: left;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
