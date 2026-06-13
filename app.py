from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

import pandas as pd
import streamlit as st

from polla.config import config_path, load_json
from polla.models import FinalPicks, GroupPick, MatchResult
from polla.scoring import score_all
from polla.store import GoogleSheetsStore, verify_pin
from polla.timeutils import BOGOTA, now_bogota


st.set_page_config(page_title="Polla Mundialista", page_icon="1:2", layout="wide")


@st.cache_resource(ttl=300)
def get_store() -> GoogleSheetsStore:
    sheets_cfg = st.secrets.get("google_sheets", {})
    spreadsheet_id = sheets_cfg.get("spreadsheet_id")
    credentials = st.secrets.get("gcp_service_account")
    if not spreadsheet_id or not credentials:
        st.error("Faltan secrets de Google Sheets. Configura google_sheets.spreadsheet_id y gcp_service_account.")
        st.stop()
    store = GoogleSheetsStore(spreadsheet_id, dict(credentials))
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
    st.title("Polla Mundialista")
    if "participant" not in st.session_state:
        login()
        return

    state = load_state()
    participant = st.session_state["participant"]
    role = st.session_state["role"]
    st.caption(f"Sesión: {participant}")
    if st.button("Salir", type="secondary"):
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

    for phase, matches in sorted(matches_by_phase.items()):
        st.subheader(phase)
        for match in sorted(matches, key=lambda item: item.kickoff_at or datetime.max.replace(tzinfo=BOGOTA)):
            pred = predictions.get((participant, match.match_id))
            locked = bool(match.kickoff_at and now >= match.kickoff_at)
            label = f"{match.match_id} | {match.team_a} vs {match.team_b}"
            caption = match.kickoff_at.strftime("%Y-%m-%d %H:%M") if match.kickoff_at else "Horario por definir"
            with st.form(f"pred_{match.match_id}"):
                st.markdown(f"**{label}**")
                st.caption(caption + (" | Cerrado" if locked else ""))
                col_a, col_b, col_save = st.columns([1, 1, 1])
                goals_a = col_a.number_input(match.team_a, min_value=0, max_value=20, value=_default_int(pred.goals_a_pred if pred else None), step=1, disabled=locked)
                goals_b = col_b.number_input(match.team_b, min_value=0, max_value=20, value=_default_int(pred.goals_b_pred if pred else None), step=1, disabled=locked)
                submitted = col_save.form_submit_button("Guardar", disabled=locked)
            if submitted:
                try:
                    store.save_prediction(participant, match, int(goals_a), int(goals_b), now)
                    load_state.clear()
                    st.success("Marcador guardado.")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))


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
        store.replace_rows("Ranking", ranking or [{"participant": "", "points": 0, "rank": ""}])
        store.replace_rows("Detail", _fit_detail_rows(detail))
        load_state.clear()
        st.success("Ranking guardado en Google Sheets.")


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


def _teams_by_group(matches: list[MatchResult]) -> dict[str, list[str]]:
    groups: dict[str, set[str]] = defaultdict(set)
    for match in matches:
        if match.phase and "group" in match.phase.casefold():
            groups[match.phase].update([match.team_a, match.team_b])
    return {group: sorted(teams) for group, teams in groups.items()}


def _default_int(value: int | None) -> int:
    return int(value) if value is not None else 0


def _index(options: list[str], value: str | None) -> int:
    return options.index(value) if value in options else 0


def _fit_detail_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    headers = ["participant", "match_id", "team_a", "team_b", "pred_score", "real_score", "points"]
    return [{header: row.get(header, "") for header in headers} for row in rows]


if __name__ == "__main__":
    main()
