from __future__ import annotations

import base64
from collections import defaultdict
from datetime import date, datetime
from html import escape
from pathlib import Path
from typing import Any

import streamlit as st

from polla.config import config_path, load_json
from polla.emailer import build_group_join_request_email, send_messages
from polla.models import FinalPicks, GroupPick, MatchResult
from polla.knockout import is_knockout_phase, is_match_ready, knockout_teams, matches_for_mode
from polla.prediction_rules import prediction_is_locked, prediction_lock_at, predictions_visible_for_date
from polla.scoring import score_all
from polla.standings import calculate_group_standings, payload_to_standings
from polla.store import hash_pin, verify_pin
from polla.supabase_store import SupabaseStore
from polla.timeutils import BOGOTA, now_bogota


st.set_page_config(page_title="Polla Mundialista", page_icon="1:2", layout="wide")


LOGO_PATH = Path(__file__).parent / "assets" / "exe2_logo.png"


TEAM_CODES = {
    "Algeria": "dz",
    "Argentina": "ar",
    "Australia": "au",
    "Austria": "at",
    "Belgium": "be",
    "Bosnia and Herzegovina": "ba",
    "Brazil": "br",
    "Cabo Verde": "cv",
    "Canada": "ca",
    "Colombia": "co",
    "Croatia": "hr",
    "Cura\u00e7ao": "cw",
    "Czech Republic": "cz",
    "C\u00f4te d'Ivoire": "ci",
    "DR Congo": "cd",
    "Ecuador": "ec",
    "Egypt": "eg",
    "England": "gb-eng",
    "France": "fr",
    "Germany": "de",
    "Ghana": "gh",
    "Haiti": "ht",
    "IR Iran": "ir",
    "Iraq": "iq",
    "Japan": "jp",
    "Jordan": "jo",
    "Mexico": "mx",
    "Morocco": "ma",
    "Netherlands": "nl",
    "New Zealand": "nz",
    "Norway": "no",
    "Panama": "pa",
    "Paraguay": "py",
    "Portugal": "pt",
    "Qatar": "qa",
    "Saudi Arabia": "sa",
    "Scotland": "gb-sct",
    "Senegal": "sn",
    "South Africa": "za",
    "South Korea": "kr",
    "Spain": "es",
    "Sweden": "se",
    "Switzerland": "ch",
    "Tunisia": "tn",
    "T\u00fcrkiye": "tr",
    "United States": "us",
    "Uruguay": "uy",
    "Uzbekistan": "uz",
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
        "groups": store.groups(),
        "memberships": store.memberships(),
        "matches": store.matches(),
        "predictions": store.predictions(),
        "group_picks": store.group_picks(),
        "final_picks": store.final_picks(),
        "results": store.results(),
        "settings": store.settings(),
        "points": load_json(config_path("puntajes.json")),
        "broadcasts": load_json(config_path("televisacion.json")),
    }


def main() -> None:
    inject_styles()
    if "participant" not in st.session_state:
        render_header()
        login()
        return

    state = load_state()
    participant = st.session_state["participant"]
    role = st.session_state["role"]
    active_group = _active_group_for_session(participant, state)
    render_header(participant, active_group)
    session_col, exit_col = st.columns([1, 0.16], vertical_alignment="center")
    session_col.markdown(_session_html(participant, active_group), unsafe_allow_html=True)
    if exit_col.button("Salir", type="secondary", use_container_width=True):
        st.session_state.clear()
        st.rerun()

    if not active_group:
        st.info("Tu usuario no tiene un grupo activo. Crea un grupo o solicita unirte a uno desde Mi cuenta.")
        account_view(participant, state, None)
        return

    _group_selector(participant, state, active_group)

    if active_group.competition_mode == "knockout":
        tabs = ["Mis marcadores", "Predicciones", "Resultados", "Ranking", "Finales", "Detalle", "Mi cuenta"]
    elif active_group.competition_mode == "group_stage":
        tabs = ["Mis marcadores", "Predicciones", "Posiciones", "Ranking", "Top 3 grupos", "Detalle", "Mi cuenta"]
    else:
        tabs = ["Mis marcadores", "Predicciones", "Posiciones", "Ranking", "Top 3 grupos", "Finales", "Detalle", "Mi cuenta"]
    if role == "admin" or _is_group_admin(participant, active_group.group_id, state):
        tabs.append("Admin")
    rendered_tabs = st.tabs(tabs)
    for tab, name in zip(rendered_tabs, tabs):
        with tab:
            if name == "Mis marcadores":
                match_predictions_view(participant, state, active_group)
            elif name == "Predicciones":
                predictions_view(state, active_group)
            elif name == "Posiciones":
                standings_view(state)
            elif name == "Resultados":
                knockout_results_view(state)
            elif name == "Ranking":
                ranking_view(state, active_group.group_id)
            elif name == "Top 3 grupos":
                group_picks_view(participant, state, active_group)
            elif name == "Finales":
                final_picks_view(participant, state, active_group)
            elif name == "Detalle":
                detail_view(state, active_group.group_id)
            elif name == "Mi cuenta":
                account_view(participant, state, active_group)
            elif name == "Admin":
                admin_view(participant, state, active_group)


def render_header(participant: str | None = None, active_group: Any | None = None) -> None:
    logo_data = base64.b64encode(LOGO_PATH.read_bytes()).decode("ascii")
    group_label = f" - {escape(active_group.name)}" if active_group else ""
    session = f'<span class="header-session">{escape(participant)}{group_label}</span>' if participant else ""
    st.markdown(
        f"""
        <section class="app-shell-header">
          <div class="brand-lockup">
            <img src="data:image/png;base64,{logo_data}" alt="Exe2 logo" />
            <div class="brand-copy">
              <h1>Polla Mundialista Exe2</h1>
              <p>Pronosticos, ranking y resultados en una sola cancha.</p>
            </div>
          </div>
          {session}
        </section>
        """,
        unsafe_allow_html=True,
    )

def login() -> None:
    store = get_store()
    state = load_state()
    st.markdown('<div class="section-title">Elige como quieres entrar</div>', unsafe_allow_html=True)
    login_tab, create_group_tab, join_group_tab = st.tabs(["Iniciar sesion", "Crear grupo", "Unirme a grupo"])

    with login_tab:
        st.caption("Para usuarios que ya tienen cuenta y grupo aprobado.")
        _login_existing_user(state)

    with create_group_tab:
        st.caption("Para el primero de una polla: crea el grupo y tu usuario admin.")
        _create_group_first_user(store, state)

    with join_group_tab:
        st.caption("Para entrar a una polla existente usando el codigo del grupo.")
        _join_group_new_user(store, state)


def _login_existing_user(state: dict[str, Any]) -> None:
    active_users = [user for user in state["users"] if user.active]
    names = [user.participant for user in active_users]
    with st.form("login"):
        participant = st.selectbox("Usuario", names, help="Usa esta opcion si ya tienes usuario y PIN.")
        pin = st.text_input("PIN", type="password", help="Tu PIN personal de acceso.")
        submitted = st.form_submit_button("Entrar", help="Ingresa si tu usuario ya fue creado y, si aplica, aprobado en un grupo.")
    if not submitted:
        return
    user = next((item for item in active_users if item.participant == participant), None)
    if not user or not verify_pin(participant, pin, user.pin_hash):
        st.error("Usuario o PIN invalido.")
        return
    st.session_state["participant"] = user.participant
    st.session_state["role"] = user.role
    st.rerun()


def _create_group_first_user(store: SupabaseStore, state: dict[str, Any]) -> None:
    with st.form("create_group_first_user"):
        group_name = st.text_input("Nombre del grupo", help="Este sera el nombre visible de tu polla.")
        suggested_code = _clean_invite_code(group_name) if group_name else ""
        invite_code = st.text_input("Codigo de invitacion", value=suggested_code, help="Comparte este codigo para que otros pidan unirse.").strip().upper()
        participant = st.text_input("Tu usuario", help="Este usuario sera admin del grupo. Debe ser unico en toda la app.")
        pin = st.text_input("PIN", type="password", help="Minimo 4 caracteres.")
        confirm_pin = st.text_input("Confirmar PIN", type="password")
        submitted = st.form_submit_button("Crear grupo y usuario", help="Crea el grupo y deja tu usuario como admin del grupo.")
    if not submitted:
        return
    cleaned_name = _clean_group_name(group_name)
    code = _clean_invite_code(invite_code or cleaned_name)
    cleaned_participant = _clean_participant(participant)
    group_error = _group_creation_error(cleaned_name, code, state["groups"])
    user_error = _registration_error(cleaned_participant, pin, confirm_pin, state["users"])
    if group_error:
        st.error(group_error)
        return
    if user_error:
        st.error(user_error)
        if any(user.participant.casefold() == cleaned_participant.casefold() for user in state["users"]):
            st.info("Sugerencias disponibles: " + ", ".join(_username_suggestions(cleaned_participant, state["users"])))
        return
    try:
        store.create_user(cleaned_participant, hash_pin(cleaned_participant, pin), role="player", active=True)
        group = store.create_group(cleaned_name, code, cleaned_participant)
    except Exception:
        st.error("No se pudo crear el grupo. Revisa si el usuario o codigo ya existen.")
        return
    load_state.clear()
    st.session_state["participant"] = cleaned_participant
    st.session_state["role"] = "player"
    st.session_state["active_group_id"] = group.group_id
    st.success(f"Grupo creado. Comparte el codigo {group.invite_code}.")
    st.rerun()


def _join_group_new_user(store: SupabaseStore, state: dict[str, Any]) -> None:
    with st.form("join_group_new_user"):
        invite_code = st.text_input("Codigo de grupo", help="Pidele este codigo al admin del grupo.").strip().upper()
        participant = st.text_input("Nombre corto", help="Debe estar disponible en toda la app.")
        pin = st.text_input("PIN", type="password", help="Minimo 4 caracteres.")
        confirm_pin = st.text_input("Confirmar PIN", type="password")
        submitted = st.form_submit_button("Enviar solicitud", help="Crea tu usuario y envia una solicitud al admin del grupo.")
    if not submitted:
        return
    group = store.group_by_invite_code(invite_code)
    if not group:
        st.error("El codigo de grupo no existe.")
        return
    cleaned_participant = _clean_participant(participant)
    validation_error = _registration_error(cleaned_participant, pin, confirm_pin, state["users"])
    if validation_error:
        st.error(validation_error)
        if any(user.participant.casefold() == cleaned_participant.casefold() for user in state["users"]):
            st.info("Sugerencias disponibles: " + ", ".join(_username_suggestions(cleaned_participant, state["users"])))
        return
    try:
        store.create_user(cleaned_participant, hash_pin(cleaned_participant, pin), role="player", active=True)
        store.create_membership(group.group_id, cleaned_participant, role="player", status="pending")
    except Exception:
        st.error("No se pudo crear la solicitud. Revisa si el usuario ya existe e intenta de nuevo.")
        return
    load_state.clear()
    email_error = _send_join_request_email(cleaned_participant, group)
    if email_error:
        st.warning(f"Solicitud creada, pero no se pudo enviar correo: {email_error}")
    else:
        st.success("Solicitud enviada. El admin del grupo debe aprobarte.")

def match_predictions_view(participant: str, state: dict[str, Any], active_group: Any) -> None:
    store = get_store()
    now = now_bogota()
    group_matches = matches_for_mode(state["matches"], active_group.competition_mode)
    predictions = {
        (pred.participant, pred.match_id): pred
        for pred in state["predictions"]
        if pred.group_id == active_group.group_id
    }
    selected_phase, selected_date = _group_date_filters(group_matches, f"match_{active_group.group_id}")
    selected_matches = _filter_matches(group_matches, selected_phase, selected_date)
    participant_predictions = [
        pred for pred in state["predictions"]
        if pred.participant == participant and pred.group_id == active_group.group_id
    ]
    saved_count = len({pred.match_id for pred in participant_predictions if pred.goals_a_pred is not None and pred.goals_b_pred is not None})
    open_count = sum(1 for match in group_matches if is_match_ready(match) and not prediction_is_locked(match, now, group_matches))
    locked_count = sum(1 for match in group_matches if is_match_ready(match) and prediction_is_locked(match, now, group_matches))

    metric_cols = st.columns(3)
    _metric_card(metric_cols[0], "Marcadores guardados", saved_count, "score")
    _metric_card(metric_cols[1], "Partidos abiertos", open_count, "open")
    _metric_card(metric_cols[2], "Partidos cerrados", locked_count, "closed")

    grid = st.columns(2)
    for idx, match in enumerate(selected_matches):
        with grid[idx % 2]:
            _match_prediction_card(
                store, active_group.group_id, participant, match,
                predictions.get((participant, match.match_id)), now, state["broadcasts"], group_matches,
            )


def predictions_view(state: dict[str, Any], active_group: Any) -> None:
    group_matches = matches_for_mode(state["matches"], active_group.competition_mode)
    date_options = _date_filter_options(group_matches)
    selected_date = st.date_input(
        "Fecha de predicciones",
        value=_default_filter_date(date_options),
        min_value=min(date_options) if date_options else None,
        max_value=max(date_options) if date_options else None,
        key=f"shared_predictions_date_{active_group.group_id}",
    )
    now = now_bogota()
    if not predictions_visible_for_date(selected_date, now, group_matches):
        st.info(f"Las predicciones del {selected_date.isoformat()} estaran visibles desde el cierre diario: primer kickoff + 1 minuto o 2:00 p. m., lo que ocurra primero.")
        return

    matches = [match for match in _filter_matches(group_matches, "Todos", selected_date) if prediction_is_locked(match, now, group_matches)]
    if not matches:
        st.info("Todavia no hay partidos bloqueados para esta fecha.")
        return
    participants = sorted(_active_participants_for_group(active_group.group_id, state) - {"admin"})
    predictions = {
        (pred.participant, pred.match_id): pred
        for pred in state["predictions"]
        if pred.group_id == active_group.group_id
    }
    st.caption("Marcadores revelados desde el cierre diario: primer kickoff + 1 minuto o 2:00 p. m., lo que ocurra primero.")
    for match in matches:
        st.markdown(
            f'<div class="section-title">{_team_html(match.team_a)} vs {_team_html(match.team_b)}'
            f'<span>{escape(match.match_id)}</span></div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            _prediction_comparison_html(match, participants, predictions),
            unsafe_allow_html=True,
        )


def group_picks_view(participant: str, state: dict[str, Any], active_group: Any) -> None:
    store = get_store()
    settings = state["settings"]
    picks = {
        (pick.participant, pick.group): pick
        for pick in state["group_picks"]
        if pick.group_id == active_group.group_id
    }
    teams_by_group = _teams_by_group(state["matches"])
    for group, teams in sorted(teams_by_group.items()):
        closed = bool(settings.get(f"group_closed_{group}", False))
        current = picks.get((participant, group), GroupPick(participant, group))
        st.subheader(group)
        if closed:
            st.info("Este grupo esta cerrado por admin.")
        with st.form(f"group_{group}"):
            first = st.selectbox("1", [""] + teams, index=_index([""] + teams, current.first), disabled=closed, key=f"{group}_first")
            second_options = [""] + [team for team in teams if team != first]
            second = st.selectbox("2", second_options, index=_index(second_options, current.second), disabled=closed, key=f"{group}_second")
            third_options = [""] + [team for team in teams if team not in {first, second}]
            third = st.selectbox("3", third_options, index=_index(third_options, current.third), disabled=closed, key=f"{group}_third")
            submitted = st.form_submit_button("Guardar Top 3", disabled=closed)
        if submitted:
            store.save_group_pick(GroupPick(participant, group, first or None, second or None, third or None, active_group.group_id), now_bogota())
            load_state.clear()
            st.success("Top 3 guardado.")
            st.rerun()


def final_picks_view(participant: str, state: dict[str, Any], active_group: Any) -> None:
    store = get_store()
    setting_key = _final_picks_setting_key(active_group)
    closed = bool(state["settings"].get(setting_key, False))
    group_matches = matches_for_mode(state["matches"], active_group.competition_mode)
    teams = knockout_teams(group_matches) if active_group.competition_mode == "knockout" else sorted(
        {match.team_a for match in group_matches} | {match.team_b for match in group_matches}
    )
    current = next(
        (pick for pick in state["final_picks"] if pick.participant == participant and pick.group_id == active_group.group_id),
        FinalPicks(participant, group_id=active_group.group_id),
    )
    if closed:
        st.info("Los picks finales estan cerrados por admin.")
    with st.form(f"final_picks_{active_group.group_id}"):
        champion = st.selectbox(
            "Campeon", [""] + teams, index=_index([""] + teams, current.champion), disabled=closed,
            key=f"{active_group.group_id}_champion",
        )
        runner_options = [""] + [team for team in teams if team != champion]
        runner_up = st.selectbox(
            "Subcampeon", runner_options, index=_index(runner_options, current.runner_up), disabled=closed,
            key=f"{active_group.group_id}_runner_up",
        )
        third_options = [""] + [team for team in teams if team not in {champion, runner_up}]
        third_place = st.selectbox(
            "Tercer puesto", third_options, index=_index(third_options, current.third_place), disabled=closed,
            key=f"{active_group.group_id}_third_place",
        )
        submitted = st.form_submit_button("Guardar finales", disabled=closed)
    if submitted:
        store.save_final_picks(FinalPicks(participant, champion or None, runner_up or None, third_place or None, active_group.group_id), now_bogota())
        load_state.clear()
        st.success("Picks finales guardados.")
        st.rerun()


def ranking_view(state: dict[str, Any], group_id: str) -> None:
    ranking, _detail = _score_state(state, group_id)
    if not ranking:
        st.info("Todavia no hay puntos calculados.")
        return
    group = next((item for item in state["groups"] if item.group_id == group_id), None)
    group_matches = matches_for_mode(state["matches"], group.competition_mode) if group else []
    group_match_ids = {match.match_id for match in group_matches}
    group_results = [
        result for result in state["results"]
        if result.match_id in group_match_ids
    ]
    predicted_counts = _predicted_match_counts(
        state["predictions"], group_results, group_id,
    )
    st.markdown('<div class="section-title">Tabla de posiciones</div>', unsafe_allow_html=True)
    for idx, row in enumerate(ranking, start=1):
        raw_rank = row.get("rank") or idx
        try:
            rank_num = int(raw_rank)
        except (TypeError, ValueError):
            rank_num = idx
        participant = escape(str(row.get("participant", "")))
        participant_key = str(row.get("participant", ""))
        points_value = int(row.get("points", 0) or 0)
        points = escape(str(points_value))
        predicted = predicted_counts.get(participant_key, 0)
        points_per_prediction = points_value / predicted if predicted else 0.0
        medal = {1: "1", 2: "2", 3: "3"}.get(rank_num, str(raw_rank))
        st.markdown(
            f"""
            <div class="ranking-row rank-{rank_num}">
              <div class="rank-left">
                <span class="rank-medal">{medal}</span>
                <span class="rank-name">{participant}</span>
              </div>
              <div class="rank-stats">
                <div class="rank-points"><strong>{points}</strong><span>pts</span></div>
                <div class="rank-ratio"><span>Pts / partido con resultado</span><strong>{points_per_prediction:.2f}</strong></div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def results_view(state: dict[str, Any]) -> None:
    confirmed_results = [result for result in state["results"] if result.confirmed]
    if not confirmed_results:
        st.info("Todavia no hay resultados reales confirmados.")
        return

    selected_phase, selected_date = _group_date_filters(confirmed_results, "results")
    results = sorted(
        _filter_matches(confirmed_results, selected_phase, selected_date),
        key=lambda item: item.kickoff_at or datetime.max.replace(tzinfo=BOGOTA),
    )
    if not results:
        st.info("No hay resultados confirmados para esos filtros.")
        return

    st.markdown(f'<div class="section-title">Resultados confirmados <span>{len(results)}</span></div>', unsafe_allow_html=True)
    for result in results:
        score = _score_text(result.goals_a_real, result.goals_b_real)
        kickoff = result.kickoff_at.strftime("%Y-%m-%d %H:%M") if result.kickoff_at else "Horario por definir"
        source = result.source or "Automatico"
        broadcast_html = _broadcast_html(_broadcast_channels(state["broadcasts"], result.match_id))
        with st.container(border=True):
            st.markdown(
                f"""
                <div class="result-row">
                  <div>
                    <div class="match-id">{result.match_id} - {result.phase or "Sin fase"}</div>
                    <div class="result-title">
                      <span>{_team_html(result.team_a)}</span>
                      <strong>{score}</strong>
                      <span>{_team_html(result.team_b)}</span>
                    </div>
                    <div class="match-time">{kickoff} - Fuente: {source}</div>
                    {broadcast_html}
                  </div>
                  <span class="match-status open">Confirmado</span>
                </div>
                """,
                unsafe_allow_html=True,
            )


def knockout_results_view(state: dict[str, Any]) -> None:
    matches = matches_for_mode(state["matches"], "knockout")
    results = {result.match_id: result for result in state["results"] if result.confirmed}
    phases = ["Round of 32", "Round of 16", "Quarter-finals", "Semi-finals", "Third place", "Final"]
    for phase in phases:
        phase_matches = [match for match in matches if match.phase == phase]
        if not phase_matches:
            continue
        st.markdown(f'<div class="section-title">{escape(phase)} <span>{len(phase_matches)}</span></div>', unsafe_allow_html=True)
        for match in sorted(phase_matches, key=lambda item: item.kickoff_at or datetime.max.replace(tzinfo=BOGOTA)):
            result = results.get(match.match_id)
            if result:
                st.markdown(_compact_result_html(result), unsafe_allow_html=True)
            else:
                kickoff = match.kickoff_at.strftime("%Y-%m-%d %H:%M") if match.kickoff_at else "Horario por definir"
                st.markdown(
                    '<div class="compact-result">'
                    f'<span class="match-id">{escape(match.match_id)}</span>'
                    f'<span>{_team_html(match.team_a)}</span><strong>vs</strong><span>{_team_html(match.team_b)}</span>'
                    f'<small>{escape(kickoff)} - Pendiente</small></div>',
                    unsafe_allow_html=True,
                )


def standings_view(state: dict[str, Any]) -> None:
    selected_phase, selected_date = _group_date_filters(state["matches"], "standings")
    filtered_results = [
        result
        for result in state["results"]
        if result.confirmed and _matches_date(result, selected_date, include_before=True)
    ]
    standings_payload = state["settings"].get("group_standings")
    use_saved_standings = selected_date is None and standings_payload
    if use_saved_standings:
        standings_by_group = payload_to_standings(standings_payload)
    else:
        standings_by_group = calculate_group_standings(state["matches"], filtered_results)
    groups = _standings_groups_for_filter(standings_by_group, state["matches"], selected_phase)
    if not groups:
        st.info("No hay grupos para esos filtros.")
        return
    st.caption(_standings_source_text(standings_payload, use_saved_standings, filtered_results))
    for group in groups:
        rows = standings_by_group[group]
        display_group = selected_phase if selected_phase != "Todos" else group
        st.markdown(f'<div class="section-title">{escape(display_group)} <span>{len(rows)}</span></div>', unsafe_allow_html=True)
        st.markdown(_standings_table_html(rows), unsafe_allow_html=True)
        _standings_group_results(filtered_results, display_group, selected_date)


def detail_view(state: dict[str, Any], group_id: str) -> None:
    _ranking, detail = _score_state(state, group_id)
    if not detail:
        st.info("Todavia no hay detalle de puntos.")
        return
    participants = sorted({str(row.get("participant", "")) for row in detail if row.get("participant")})
    filter_participant, filter_date = st.columns(2)
    selected = filter_participant.selectbox("Participante", ["Todos"] + participants, key="detail_participant")
    all_dates = filter_date.checkbox("Todas las fechas", value=False, key="detail_all_dates")
    selected_date = None
    date_options = _date_filter_options(state["matches"])
    if not all_dates:
        selected_date = filter_date.date_input(
            "Fecha",
            value=_default_filter_date(date_options),
            min_value=min(date_options) if date_options else None,
            max_value=max(date_options) if date_options else None,
            key="detail_date_filter",
        )
    rows = _filter_detail_rows(detail, state["matches"], selected, selected_date)
    if not rows:
        st.info("No hay detalle de puntos para esos filtros.")
        return
    st.markdown(f'<div class="section-title">Detalle de puntos <span>{len(rows)}</span></div>', unsafe_allow_html=True)
    for row in rows:
        participant = escape(str(row.get("participant", "")))
        match_id = escape(str(row.get("match_id", "")))
        team_a = escape(str(row.get("team_a", "")))
        team_b = escape(str(row.get("team_b", "")))
        pred_score = escape(str(row.get("pred_score", "- : -")))
        real_score = escape(str(row.get("real_score", "- : -")))
        points = escape(str(row.get("points", 0)))
        st.markdown(
            f"""
            <div class="detail-card">
              <div class="detail-top">
                <span class="match-id">{match_id}</span>
                <span class="detail-participant">{participant}</span>
                <span class="points-pill">+{points} pts</span>
              </div>
              <div class="detail-match">{team_a} vs {team_b}</div>
              <div class="detail-score-grid">
                <div><span>Prediccion</span><strong>{pred_score}</strong></div>
                <div><span>Resultado</span><strong>{real_score}</strong></div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def account_view(participant: str, state: dict[str, Any], active_group: Any | None) -> None:
    store = get_store()
    user = _user_by_participant(state["users"], participant)
    if not user:
        st.error("No se encontro el usuario de la sesion.")
        return

    st.markdown('<div class="section-title">Mis grupos</div>', unsafe_allow_html=True)
    _render_user_groups(participant, state, active_group)

    group_cols = st.columns(2)
    with group_cols[0]:
        with st.form("join_group"):
            invite_code = st.text_input("Codigo de invitacion", help="Codigo compartido por el admin del grupo.").strip().upper()
            join_submitted = st.form_submit_button("Unirme a grupo", help="Envia una solicitud pendiente de aprobacion.")
        if join_submitted:
            group = store.group_by_invite_code(invite_code)
            if not group:
                st.error("El codigo de grupo no existe.")
            elif _membership_for(participant, group.group_id, state):
                st.info("Ya tienes una solicitud o membresia en ese grupo.")
            else:
                store.create_membership(group.group_id, participant, role="player", status="pending")
                load_state.clear()
                email_error = _send_join_request_email(participant, group)
                if email_error:
                    st.warning(f"Solicitud creada, pero no se pudo enviar correo: {email_error}")
                else:
                    st.success("Solicitud enviada al admin del grupo.")
                st.rerun()

    with group_cols[1]:
        with st.form("create_group"):
            group_name = st.text_input("Nombre del grupo", help="Nombre visible en rankings y perfil.")
            desired_code = st.text_input("Codigo de invitacion", help="Codigo que compartiras con amigos para que se unan.").strip().upper()
            create_submitted = st.form_submit_button("Crear grupo", help="Crea un nuevo grupo y te asigna como admin.")
        if create_submitted:
            cleaned_name = _clean_group_name(group_name)
            code = _clean_invite_code(desired_code or cleaned_name)
            error = _group_creation_error(cleaned_name, code, state["groups"])
            if error:
                st.error(error)
            else:
                try:
                    group = store.create_group(cleaned_name, code, participant)
                except Exception:
                    st.error("No se pudo crear el grupo. Prueba con otro codigo.")
                    return
                load_state.clear()
                st.session_state["active_group_id"] = group.group_id
                st.success("Grupo creado correctamente.")
                st.rerun()

    st.markdown('<div class="section-title">Actualizar PIN</div>', unsafe_allow_html=True)
    with st.form("update_pin"):
        current_pin = st.text_input("PIN actual", type="password")
        new_pin = st.text_input("Nuevo PIN", type="password")
        confirm_pin = st.text_input("Confirmar nuevo PIN", type="password")
        submitted = st.form_submit_button("Actualizar PIN")
    if not submitted:
        return
    validation_error = _pin_update_error(participant, current_pin, new_pin, confirm_pin, user.pin_hash)
    if validation_error:
        st.error(validation_error)
        return
    store.update_user_pin(participant, hash_pin(participant, new_pin))
    load_state.clear()
    st.success("PIN actualizado correctamente.")


def admin_view(participant: str, state: dict[str, Any], active_group: Any) -> None:
    store = get_store()
    is_global_admin = st.session_state.get("role") == "admin"
    active_members = _active_members_for_group(active_group.group_id, state)
    pending_members = _pending_members_for_group(active_group.group_id, state)

    st.subheader(f"Solicitudes pendientes - {active_group.name}")
    st.caption(f"Miembros activos: {len(active_members)} / 10")
    if not pending_members:
        st.info("No hay solicitudes pendientes para este grupo.")
    for membership in sorted(pending_members, key=lambda item: item.participant.casefold()):
        cols = st.columns([1, 0.28], vertical_alignment="center")
        cols[0].markdown(
            f"""
            <div class="user-approval-row">
              <strong>{escape(membership.participant)}</strong>
              <span>{escape(membership.role or "player")}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        disabled = len(active_members) >= 10
        if cols[1].button("Aprobar", key=f"approve_{active_group.group_id}_{membership.participant}", use_container_width=True, disabled=disabled):
            if store.active_member_count(active_group.group_id) >= 10:
                st.error("Este grupo ya alcanzo el maximo de 10 participantes.")
                return
            store.set_membership_status(active_group.group_id, membership.participant, "active")
            load_state.clear()
            st.success(f"Usuario {membership.participant} aprobado en {active_group.name}.")
            st.rerun()
        if disabled:
            cols[1].caption("Grupo lleno")

    with st.expander("Usuarios activos"):
        if not active_members:
            st.caption("No hay usuarios activos.")
        for membership in sorted(active_members, key=lambda item: item.participant.casefold()):
            st.markdown(
                f'<div class="active-user-row"><strong>{escape(membership.participant)}</strong><span>{escape(membership.role)}</span></div>',
                unsafe_allow_html=True,
            )

    if not is_global_admin:
        return

    st.subheader("Cierres manuales")
    if active_group.competition_mode != "knockout":
        teams_by_group = _teams_by_group(state["matches"])
        for group in sorted(teams_by_group):
            key = f"group_closed_{group}"
            new_value = st.toggle(f"Cerrar Top 3 {group}", value=bool(state["settings"].get(key, False)))
            if new_value != bool(state["settings"].get(key, False)):
                store.save_setting(key, new_value)
                load_state.clear()
                st.rerun()
    if active_group.competition_mode != "group_stage":
        final_key = _final_picks_setting_key(active_group)
        final_closed = st.toggle(
            f"Cerrar campeon/subcampeon/tercero - {active_group.name}",
            value=bool(state["settings"].get(final_key, False)),
        )
        if final_closed != bool(state["settings"].get(final_key, False)):
            store.save_setting(final_key, final_closed)
            load_state.clear()
            st.rerun()

    st.subheader("Resultados finales reales")
    teams = sorted({
        team for match in state["matches"] for team in (match.team_a, match.team_b)
        if not team.startswith(("Winner ", "Loser "))
    })
    with st.form("actual_finals"):
        actual_champion = st.selectbox("Campeon real", [""] + teams, index=_index([""] + teams, state["settings"].get("actual_champion")))
        runner_options = [""] + [team for team in teams if team != actual_champion]
        actual_runner_up = st.selectbox("Subcampeon real", runner_options, index=_index(runner_options, state["settings"].get("actual_runner_up")))
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
        ranking, detail = _score_rows_by_group(state)
        store.replace_rows("Ranking", ranking)
        store.replace_rows("Detail", _fit_detail_rows(detail))
        load_state.clear()
        st.success("Ranking guardado en Supabase.")


def _score_state(state: dict[str, Any], group_id: str | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    group = next((item for item in state["groups"] if item.group_id == group_id), None)
    if group is None:
        return [], []
    matches = matches_for_mode(state["matches"], group.competition_mode)
    match_ids = {match.match_id for match in matches}
    predictions = [
        pred for pred in state["predictions"]
        if pred.group_id == group_id and pred.match_id in match_ids
    ]
    results = [result for result in state["results"] if result.match_id in match_ids]
    final_picks = [] if group.competition_mode == "group_stage" else [
        pick for pick in state["final_picks"] if pick.group_id == group_id
    ]
    group_picks = [] if group.competition_mode == "knockout" else [
        pick for pick in state["group_picks"] if pick.group_id == group_id
    ]
    ranking, detail = score_all(
        predictions,
        results,
        final_picks,
        {
            "champion": state["settings"].get("actual_champion") or None,
            "runner_up": state["settings"].get("actual_runner_up") or None,
            "third_place": state["settings"].get("actual_third_place") or None,
        },
        group_picks,
        matches,
        state["points"],
    )
    participants = _active_participants_for_group(group_id, state)
    ranking = [row for row in ranking if row.get("participant") in participants]
    for idx, row in enumerate(ranking, start=1):
        row["rank"] = idx
    detail = [row for row in detail if row.get("participant") in participants]
    return ranking, detail


def _match_prediction_card(
    store: SupabaseStore,
    group_id: str,
    participant: str,
    match: MatchResult,
    pred: Any,
    now: datetime,
    broadcasts: dict[str, Any],
    schedule: list[MatchResult],
) -> None:
    ready = is_match_ready(match)
    locked = not ready or prediction_is_locked(match, now, schedule)
    lock_at = prediction_lock_at(match, schedule)
    caption = match.kickoff_at.strftime("%Y-%m-%d %H:%M") if match.kickoff_at else "Horario por definir"
    status = "Pendiente" if not ready else "Cerrado" if locked else "Abierto"
    just_saved = st.session_state.get("last_saved_prediction") == match.match_id
    if just_saved:
        st.session_state.pop("last_saved_prediction", None)
    is_saved = bool(
        pred
        and pred.goals_a_pred is not None
        and pred.goals_b_pred is not None
    ) or just_saved
    saved_badge = '<span class="prediction-saved-flag">Guardado</span>' if is_saved else ""
    saved_note = '<div class="prediction-saved-note">Prediccion guardada correctamente.</div>' if just_saved else ""
    badges_html = (
        '<div class="match-badges">'
        f'{saved_badge}<span class="match-status {"locked" if locked else "open"}">{status}</span>'
        "</div>"
    )
    card_header_html = (
        '<div class="match-card-top">'
        f'<div><span class="match-id">{escape(match.match_id)}</span>'
        f'<div class="match-time">{escape(caption)}</div>'
        f'<div class="match-lock-time">Cierre: {escape(lock_at.strftime("%H:%M") if lock_at else "Por definir")}</div></div>'
        f"{badges_html}"
        "</div>"
    )
    card_intro_html = (
        f"{card_header_html}"
        '<div class="match-title">'
        f"<span>{_team_html(match.team_a)}</span>"
        '<span class="versus">vs</span>'
        f"<span>{_team_html(match.team_b)}</span>"
        "</div>"
        f'{_broadcast_html(_broadcast_channels(broadcasts, match.match_id))}'
        f"{saved_note}"
    )
    with st.container(border=True):
        st.markdown(card_intro_html, unsafe_allow_html=True)
        with st.form(f"pred_{group_id}_{match.match_id}"):
            if is_knockout_phase(match.phase):
                st.caption("Pronostica el marcador al finalizar 120 minutos, sin incluir penales.")
            col_a, score_sep, col_b = st.columns([0.8, 0.18, 0.8], vertical_alignment="bottom")
            goals_a = col_a.number_input(
                match.team_a,
                min_value=0,
                max_value=20,
                value=_default_int(pred.goals_a_pred if pred else None),
                step=1,
                disabled=locked,
                key=f"{group_id}_{match.match_id}_a",
                label_visibility="collapsed",
            )
            score_sep.markdown('<div class="score-separator">:</div>', unsafe_allow_html=True)
            goals_b = col_b.number_input(
                match.team_b,
                min_value=0,
                max_value=20,
                value=_default_int(pred.goals_b_pred if pred else None),
                step=1,
                disabled=locked,
                key=f"{group_id}_{match.match_id}_b",
                label_visibility="collapsed",
            )
            qualified_team_pred = None
            if is_knockout_phase(match.phase) and ready:
                if goals_a > goals_b:
                    qualified_team_pred = match.team_a
                    st.caption(f"Clasifica: {match.team_a}")
                elif goals_b > goals_a:
                    qualified_team_pred = match.team_b
                    st.caption(f"Clasifica: {match.team_b}")
                else:
                    qualifier_options = [match.team_a, match.team_b]
                    qualified_team_pred = st.selectbox(
                        "Quien clasifica",
                        qualifier_options,
                        index=_index(qualifier_options, pred.qualified_team_pred if pred else None),
                        disabled=locked,
                        key=f"{group_id}_{match.match_id}_qualifier",
                    )
            submitted = st.form_submit_button("Guardar", disabled=locked, use_container_width=True)
        if submitted:
            try:
                store.save_prediction(group_id, participant, match, int(goals_a), int(goals_b), qualified_team_pred, now)
                st.session_state["last_saved_prediction"] = match.match_id
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


def _active_group_for_session(participant: str, state: dict[str, Any]) -> Any | None:
    groups = {group.group_id: group for group in state["groups"] if group.active}
    active_memberships = [
        membership
        for membership in state["memberships"]
        if membership.participant == participant and membership.status == "active" and membership.group_id in groups
    ]
    if not active_memberships:
        st.session_state.pop("active_group_id", None)
        return None
    selected = st.session_state.get("active_group_id")
    if selected in groups and any(membership.group_id == selected for membership in active_memberships):
        return groups[selected]
    first_group_id = active_memberships[0].group_id
    st.session_state["active_group_id"] = first_group_id
    return groups[first_group_id]


def _group_selector(participant: str, state: dict[str, Any], active_group: Any) -> None:
    groups = {group.group_id: group for group in state["groups"] if group.active}
    user_group_ids = [
        membership.group_id
        for membership in state["memberships"]
        if membership.participant == participant and membership.status == "active" and membership.group_id in groups
    ]
    if len(user_group_ids) <= 1:
        return
    options = {groups[group_id].name: group_id for group_id in user_group_ids}
    selected_name = st.selectbox(
        "Grupo activo",
        list(options),
        index=list(options.values()).index(active_group.group_id),
        key="active_group_select",
    )
    selected_group_id = options[selected_name]
    if selected_group_id != active_group.group_id:
        st.session_state["active_group_id"] = selected_group_id
        st.rerun()


def _session_html(participant: str, active_group: Any | None) -> str:
    group = f' - Grupo: <strong>{escape(active_group.name)}</strong>' if active_group else ""
    return f'<div class="session-chip">Sesion: <strong>{escape(participant)}</strong>{group}</div>'


def _is_group_admin(participant: str, group_id: str, state: dict[str, Any]) -> bool:
    return any(
        membership.participant == participant
        and membership.group_id == group_id
        and membership.status == "active"
        and membership.role == "admin"
        for membership in state["memberships"]
    )


def _membership_for(participant: str, group_id: str, state: dict[str, Any]) -> Any | None:
    return next(
        (
            membership
            for membership in state["memberships"]
            if membership.participant == participant and membership.group_id == group_id
        ),
        None,
    )


def _active_members_for_group(group_id: str, state: dict[str, Any]) -> list[Any]:
    return [
        membership
        for membership in state["memberships"]
        if membership.group_id == group_id and membership.status == "active"
    ]


def _pending_members_for_group(group_id: str, state: dict[str, Any]) -> list[Any]:
    return [
        membership
        for membership in state["memberships"]
        if membership.group_id == group_id and membership.status == "pending"
    ]


def _active_participants_for_group(group_id: str, state: dict[str, Any]) -> set[str]:
    return {membership.participant for membership in _active_members_for_group(group_id, state)}


def _render_user_groups(participant: str, state: dict[str, Any], active_group: Any | None) -> None:
    groups = {group.group_id: group for group in state["groups"]}
    memberships = [membership for membership in state["memberships"] if membership.participant == participant]
    if not memberships:
        st.caption("Aun no tienes grupos.")
        return
    for membership in memberships:
        group = groups.get(membership.group_id)
        if not group:
            continue
        active_marker = "Activo" if active_group and active_group.group_id == group.group_id else membership.status
        st.markdown(
            f"""
            <div class="active-user-row">
              <strong>{escape(group.name)}</strong>
              <span>{escape(active_marker)} - {escape(membership.role)} - Codigo {escape(group.invite_code)}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )


def _score_rows_by_group(state: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ranking_rows: list[dict[str, Any]] = []
    detail_rows: list[dict[str, Any]] = []
    for group in state["groups"]:
        if not group.active:
            continue
        ranking, detail = _score_state(state, group.group_id)
        for row in ranking:
            ranking_rows.append({"group_id": group.group_id, **row})
        for row in detail:
            detail_rows.append({"group_id": group.group_id, **row})
    return ranking_rows, detail_rows


def _final_picks_setting_key(group: Any) -> str:
    if group.competition_mode == "full" and group.invite_code == "EXE2":
        return "final_picks_closed"
    return f"final_picks_closed_{group.invite_code}"


def _predicted_match_counts(
    predictions: list[Any],
    results: list[MatchResult],
    group_id: str | None = None,
) -> dict[str, int]:
    closed_match_ids = {result.match_id for result in results if result.confirmed}
    match_ids_by_participant: dict[str, set[str]] = defaultdict(set)
    for prediction in predictions:
        if group_id is not None and prediction.group_id != group_id:
            continue
        if prediction.goals_a_pred is None or prediction.goals_b_pred is None:
            continue
        if prediction.match_id not in closed_match_ids:
            continue
        match_ids_by_participant[prediction.participant].add(prediction.match_id)
    return {
        participant: len(match_ids)
        for participant, match_ids in match_ids_by_participant.items()
    }


def _team_html(team: str) -> str:
    code = TEAM_CODES.get(team)
    safe_team = escape(team)
    if not code:
        return safe_team
    return f'<span class="team-with-flag"><img src="https://flagcdn.com/{code}.svg" alt="" loading="lazy" />{safe_team}</span>'


def _group_date_filters(matches: list[MatchResult], key_prefix: str) -> tuple[str, date | None]:
    phases = sorted({match.phase or "Sin fase" for match in matches})
    date_options = _date_filter_options(matches)
    col_group, col_date = st.columns(2)
    selected_phase = col_group.selectbox("Grupo o fase", ["Todos"] + phases, key=f"{key_prefix}_phase_filter")
    all_dates = col_date.checkbox("Todas las fechas", value=False, key=f"{key_prefix}_all_dates")
    selected_date = None
    if not all_dates:
        selected_date = col_date.date_input(
            "Fecha",
            value=_default_filter_date(date_options),
            min_value=min(date_options) if date_options else None,
            max_value=max(date_options) if date_options else None,
            key=f"{key_prefix}_date_filter",
        )
    return selected_phase, selected_date


def _filter_matches(matches: list[MatchResult], selected_phase: str, selected_date: date | None) -> list[MatchResult]:
    return sorted(
        [
            match
            for match in matches
            if _matches_phase(match, selected_phase) and _matches_date(match, selected_date)
        ],
        key=lambda item: item.kickoff_at or datetime.max.replace(tzinfo=BOGOTA),
    )


def _matches_phase(match: MatchResult, selected_phase: str) -> bool:
    return selected_phase == "Todos" or (match.phase or "Sin fase") == selected_phase


def _matches_date(match: MatchResult, selected_date: date | None, include_before: bool = False) -> bool:
    if selected_date is None:
        return True
    if not match.kickoff_at:
        return False
    match_date = match.kickoff_at.date()
    return match_date <= selected_date if include_before else match_date == selected_date


def _date_filter_options(matches: list[MatchResult]) -> list[date]:
    return sorted({match.kickoff_at.date() for match in matches if match.kickoff_at})


def _filter_detail_rows(
    detail: list[dict[str, Any]],
    matches: list[MatchResult],
    participant: str,
    selected_date: date | None,
) -> list[dict[str, Any]]:
    matches_by_id = {match.match_id: match for match in matches}
    rows = []
    for row in detail:
        if participant != "Todos" and row.get("participant") != participant:
            continue
        match = matches_by_id.get(str(row.get("match_id", "")))
        if selected_date is not None and (
            not match
            or not match.kickoff_at
            or match.kickoff_at.date() != selected_date
        ):
            continue
        rows.append(row)
    return sorted(
        rows,
        key=lambda row: (
            matches_by_id.get(str(row.get("match_id", ""))).kickoff_at
            if matches_by_id.get(str(row.get("match_id", "")))
            and matches_by_id[str(row.get("match_id", ""))].kickoff_at
            else datetime.max.replace(tzinfo=BOGOTA),
            str(row.get("participant", "")),
        ),
    )


def _default_filter_date(options: list[date]) -> date:
    today = now_bogota().date()
    if not options:
        return today
    if today < min(options):
        return min(options)
    if today > max(options):
        return max(options)
    return today


def _standings_groups_for_filter(
    standings_by_group: dict[str, list[Any]],
    matches: list[MatchResult],
    selected_phase: str,
) -> list[str]:
    if selected_phase == "Todos":
        return sorted(standings_by_group)
    if selected_phase in standings_by_group:
        return [selected_phase]
    selected_teams = set(_teams_by_group(matches).get(selected_phase, []))
    if not selected_teams:
        return []
    matches_by_overlap = []
    for group, rows in standings_by_group.items():
        row_teams = {row.team for row in rows}
        overlap = len(selected_teams & row_teams)
        if overlap:
            matches_by_overlap.append((overlap, group))
    return [group for _overlap, group in sorted(matches_by_overlap, reverse=True)[:1]]


def _standings_group_results(
    filtered_results: list[MatchResult],
    group: str,
    selected_date: date | None,
) -> None:
    rows = _filter_matches(filtered_results, group, selected_date)
    if not rows:
        st.markdown('<div class="group-results-empty">Sin resultados confirmados para este filtro.</div>', unsafe_allow_html=True)
        return
    st.markdown(f'<div class="mini-section-title">Resultados del grupo <span>{len(rows)}</span></div>', unsafe_allow_html=True)
    for result in rows:
        st.markdown(_compact_result_html(result), unsafe_allow_html=True)


def _prediction_comparison_html(
    match: MatchResult,
    participants: list[str],
    predictions: dict[tuple[str, str], Any],
) -> str:
    rows = ""
    for participant in participants:
        prediction = predictions.get((participant, match.match_id))
        if not prediction or prediction.goals_a_pred is None or prediction.goals_b_pred is None:
            continue
        score = f"{prediction.goals_a_pred} - {prediction.goals_b_pred}"
        qualifier = prediction.qualified_team_pred or prediction.winner_pred
        if is_knockout_phase(match.phase) and qualifier:
            score += f" | {qualifier}"
        rows += (
            '<div class="shared-prediction-row">'
            f'<span class="shared-prediction-user">{escape(participant)}</span>'
            f'<strong class="prediction-available">{escape(score)}</strong>'
            "</div>"
        )
    if not rows:
        rows = '<div class="shared-predictions-empty">Nadie registro una prediccion para este partido.</div>'
    kickoff = match.kickoff_at.strftime("%Y-%m-%d %H:%M") if match.kickoff_at else "Horario por definir"
    return (
        '<div class="shared-predictions-card">'
        f'<div class="shared-predictions-meta">{escape(kickoff)}</div>'
        f"{rows}"
        "</div>"
    )


def _standings_table_html(rows: list[Any]) -> str:
    body = ""
    for idx, row in enumerate(rows, start=1):
        body += (
            "<tr>"
            f'<td class="standing-rank">{idx}</td>'
            f'<td class="standing-team">{_team_html(row.team)}</td>'
            f"<td>{row.played}</td>"
            f"<td>{row.won}</td>"
            f"<td>{row.drawn}</td>"
            f"<td>{row.lost}</td>"
            f"<td>{row.goals_for}</td>"
            f"<td>{row.goals_against}</td>"
            f"<td>{row.goal_difference:+d}</td>"
            f'<td class="standing-points">{row.points}</td>'
            "</tr>"
        )
    return (
        '<div class="standings-wrap"><table class="standings-table"><thead><tr>'
        "<th>#</th><th>Equipo</th><th>PJ</th><th>PG</th><th>PE</th><th>PP</th><th>GF</th><th>GC</th><th>DG</th><th>Pts</th>"
        f"</tr></thead><tbody>{body}</tbody></table></div>"
    )


def _compact_result_html(result: MatchResult) -> str:
    score = _score_text(result.goals_a_real, result.goals_b_real)
    kickoff = result.kickoff_at.strftime("%Y-%m-%d %H:%M") if result.kickoff_at else "Horario por definir"
    source = escape(result.source or "Automatico")
    qualifier = f"Clasifica {result.qualified_team}" if result.qualified_team else source
    extra = ""
    if result.final_goals_a is not None and result.final_goals_b is not None and (
        result.final_goals_a != result.goals_a_real or result.final_goals_b != result.goals_b_real
    ):
        extra += f" | Final {result.final_goals_a}-{result.final_goals_b}"
    if result.penalties_a is not None and result.penalties_b is not None:
        extra += f" | Penales {result.penalties_a}-{result.penalties_b}"
    return (
        '<div class="compact-result">'
        f'<span class="match-id">{escape(result.match_id)}</span>'
        f'<span>{_team_html(result.team_a)}</span>'
        f"<strong>{escape(score)}</strong>"
        f'<span>{_team_html(result.team_b)}</span>'
        f'<small>{escape(kickoff)} - {escape(qualifier + extra)} - {source}</small>'
        "</div>"
    )


def _standings_source_text(payload: Any, use_saved: bool, filtered_results: list[MatchResult]) -> str:
    if use_saved:
        if isinstance(payload, str):
            import json
            payload = json.loads(payload)
        source = (payload or {}).get("source") or "standings guardados"
        updated_at = (payload or {}).get("updated_at")
        suffix = f" - Actualizado: {updated_at}" if updated_at else ""
        return f"Tabla oficial/curada desde {source}{suffix}."
    source_names = sorted({result.source for result in filtered_results if result.source})
    source_text = ", ".join(source_names) if source_names else "resultados confirmados"
    return f"Tabla calculada hasta la fecha seleccionada. Fuente: {source_text}."


def _broadcast_channels(broadcasts: dict[str, Any], match_id: str) -> list[str]:
    matches = broadcasts.get("matches") or {}
    channels = matches.get(match_id) or []
    return [str(channel) for channel in channels if channel]


def _broadcast_html(channels: list[str]) -> str:
    if not channels:
        return ""
    chips = "".join(f'<span>{escape(channel)}</span>' for channel in channels)
    return f'<div class="broadcast-row"><strong>TV</strong>{chips}</div>'


def _clean_participant(value: str) -> str:
    return " ".join(value.strip().split())


def _clean_group_name(value: str) -> str:
    return " ".join(value.strip().split())


def _clean_invite_code(value: str) -> str:
    cleaned = "".join(char for char in value.upper().replace(" ", "-") if char.isalnum() or char == "-")
    return cleaned[:20]


def _user_by_participant(users: list[Any], participant: str) -> Any | None:
    return next((user for user in users if user.participant == participant), None)


def _registration_error(participant: str, pin: str, confirm_pin: str, users: list[Any]) -> str | None:
    if not participant:
        return "Escribe un nombre corto."
    if len(participant) > 40:
        return "El nombre corto debe tener maximo 40 caracteres."
    if any(user.participant.casefold() == participant.casefold() for user in users):
        return "Ese nombre ya existe o esta pendiente de aprobacion."
    if len(pin) < 4:
        return "El PIN debe tener minimo 4 caracteres."
    if pin != confirm_pin:
        return "El PIN y la confirmacion no coinciden."
    return None


def _group_creation_error(name: str, invite_code: str, groups: list[Any]) -> str | None:
    if not name:
        return "Escribe un nombre de grupo."
    if len(name) > 50:
        return "El nombre del grupo debe tener maximo 50 caracteres."
    if len(invite_code) < 3:
        return "El codigo debe tener minimo 3 caracteres."
    if any(group.invite_code.casefold() == invite_code.casefold() for group in groups):
        return "Ese codigo de grupo ya existe."
    return None


def _username_suggestions(participant: str, users: list[Any]) -> list[str]:
    existing = {user.participant.casefold() for user in users}
    base = "".join(char for char in participant if char.isalnum()) or "Jugador"
    candidates = [
        f"{base}2",
        f"{base}2026",
        f"{base}FC",
        f"{base}_1",
        f"{base}Gol",
    ]
    return [candidate for candidate in candidates if candidate.casefold() not in existing][:3]


def _send_join_request_email(participant: str, group: Any) -> str | None:
    try:
        cfg = load_json(config_path("alertas.json"))

        smtp_user_env = cfg.get("smtp_user_env", "POLLA_SMTP_USER")
        smtp_password_env = cfg.get("smtp_password_env", "POLLA_SMTP_PASSWORD")

        cfg["smtp_user"] = st.secrets.get(smtp_user_env)
        cfg["smtp_password"] = st.secrets.get(smtp_password_env)

        if not cfg["smtp_user"]:
            return f"No se encontró el secret {smtp_user_env} en Streamlit Secrets."

        if not cfg["smtp_password"]:
            return f"No se encontró el secret {smtp_password_env} en Streamlit Secrets."

        message = build_group_join_request_email(
            participant=participant,
            group_name=group.name,
            invite_code=group.invite_code,
            requested_at=now_bogota().isoformat(),
            cfg=cfg,
        )

        send_messages([message], cfg, dry_run=bool(cfg.get("dry_run", False)))

    except Exception as exc:
        return str(exc)

    return None

def _pin_update_error(participant: str, current_pin: str, new_pin: str, confirm_pin: str, stored_hash: str) -> str | None:
    if not verify_pin(participant, current_pin, stored_hash):
        return "El PIN actual no es correcto."
    if len(new_pin) < 4:
        return "El nuevo PIN debe tener minimo 4 caracteres."
    if new_pin != confirm_pin:
        return "El nuevo PIN y la confirmacion no coinciden."
    if verify_pin(participant, new_pin, stored_hash):
        return "El nuevo PIN debe ser diferente al actual."
    return None


def _metric_card(container: Any, label: str, value: int, variant: str) -> None:
    container.markdown(
        f"""
        <div class="metric-card metric-{variant}">
          <span>{escape(label)}</span>
          <strong>{value}</strong>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _score_text(goals_a: int | None, goals_b: int | None) -> str:
    if goals_a is None or goals_b is None:
        return "- : -"
    return f"{goals_a} - {goals_b}"


def _default_int(value: int | None) -> int:
    return int(value) if value is not None else 0


def _index(options: list[str], value: str | None) -> int:
    return options.index(value) if value in options else 0


def _fit_detail_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    headers = ["group_id", "participant", "match_id", "team_a", "team_b", "pred_score", "real_score", "points"]
    return [{header: row.get(header, "") for header in headers} for row in rows]


def inject_styles() -> None:
    st.markdown(
        """
        <style>
        :root {
            --exe-bg: #ffffff;
            --exe-surface: #ffffff;
            --exe-surface-soft: #f6f8fb;
            --exe-ink: #071421;
            --exe-muted: #64748b;
            --exe-border: #dbe4ee;
            --exe-blue: #1155d9;
            --exe-blue-dark: #082142;
            --exe-cyan: #06b6d4;
            --exe-green: #39e600;
            --exe-green-soft: #e8ffe5;
            --exe-red: #e11d48;
            --exe-gold: #f5c542;
            --exe-shadow: 0 12px 30px rgba(8, 33, 66, 0.08);
        }
        .stApp {
            background: var(--exe-bg);
            color: var(--exe-ink);
        }
        .block-container {
            max-width: 1180px;
            padding-top: 0.85rem;
            padding-bottom: 3rem;
        }
        header[data-testid="stHeader"] {
            background: rgba(255, 255, 255, 0.82);
            backdrop-filter: blur(10px);
        }
        .app-shell-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 1rem;
            margin-bottom: 0.55rem;
            padding: 0.8rem 1rem;
            border: 1px solid var(--exe-border);
            border-radius: 10px;
            background: linear-gradient(135deg, #ffffff 0%, #f8fbff 58%, #effff0 100%);
            box-shadow: var(--exe-shadow);
        }
        .brand-lockup {
            display: flex;
            align-items: center;
            gap: 0.95rem;
            min-width: 0;
        }
        .brand-lockup img {
            width: 82px;
            height: 82px;
            object-fit: contain;
            flex: 0 0 auto;
            border-radius: 8px;
            background: #ffffff;
        }
        .brand-copy h1 {
            margin: 0;
            color: var(--exe-ink);
            font-size: clamp(1.45rem, 2.4vw, 2.25rem);
            line-height: 1.02;
            font-weight: 900;
            letter-spacing: 0;
        }
        .brand-copy p {
            margin: 0.3rem 0 0;
            color: #33526f;
            font-size: 0.96rem;
            font-weight: 650;
        }
        .header-session,
        .session-chip {
            display: inline-flex;
            align-items: center;
            width: fit-content;
            gap: 0.35rem;
            color: #39546d;
            background: var(--exe-surface-soft);
            border: 1px solid var(--exe-border);
            border-radius: 999px;
            padding: 0.36rem 0.7rem;
            font-size: 0.82rem;
            font-weight: 650;
        }
        .stTabs [data-baseweb="tab-list"] {
            gap: 0.25rem;
            border-bottom: 1px solid var(--exe-border);
            padding-bottom: 0;
            overflow-x: auto;
        }
        .stTabs [data-baseweb="tab"] {
            min-height: 38px;
            height: 38px;
            border-radius: 8px 8px 0 0;
            color: #31465b;
            font-size: 0.92rem;
            font-weight: 800;
            padding: 0.35rem 0.8rem;
            border: 1px solid transparent;
            white-space: nowrap;
        }
        .stTabs [aria-selected="true"] {
            background: var(--exe-blue-dark);
            border-color: var(--exe-blue-dark);
            color: #ffffff;
        }
        .stSelectbox label,
        .stNumberInput label,
        .stTextInput label {
            color: #25384b;
            font-weight: 750;
            font-size: 0.88rem;
        }
        .stButton > button,
        .stFormSubmitButton > button {
            min-height: 38px;
            border-radius: 8px;
            border: 1px solid #0d3da1;
            background: linear-gradient(135deg, var(--exe-blue), #0b2f74);
            color: #ffffff;
            font-weight: 850;
            letter-spacing: 0;
            box-shadow: 0 6px 14px rgba(17, 85, 217, 0.16);
        }
        .stButton > button:hover,
        .stFormSubmitButton > button:hover {
            border-color: var(--exe-green);
            color: #ffffff;
            filter: brightness(1.04);
        }
        .stButton > button:disabled,
        .stFormSubmitButton > button:disabled {
            background: #e8edf3;
            border-color: #d7e0ea;
            color: #8795a5;
            box-shadow: none;
        }
        .metric-card {
            min-height: 96px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            gap: 0.35rem;
            border: 1px solid var(--exe-border);
            border-radius: 8px;
            padding: 0.85rem 0.95rem;
            background: var(--exe-surface);
            box-shadow: 0 8px 22px rgba(8, 33, 66, 0.06);
        }
        .metric-card span {
            color: var(--exe-muted);
            font-size: 0.83rem;
            font-weight: 750;
        }
        .metric-card strong {
            color: var(--exe-ink);
            font-size: 2.05rem;
            line-height: 1;
            font-weight: 900;
        }
        .metric-open { border-top: 4px solid var(--exe-green); }
        .metric-closed { border-top: 4px solid var(--exe-red); }
        .metric-score { border-top: 4px solid var(--exe-blue); }
        div[data-testid="stVerticalBlockBorderWrapper"] {
            border-color: var(--exe-border);
            border-radius: 8px;
            background: rgba(255, 255, 255, 0.98);
            box-shadow: 0 8px 20px rgba(8, 33, 66, 0.06);
        }
        div[data-testid="stVerticalBlockBorderWrapper"] > div {
            border-radius: 8px;
        }
        .match-card-top,
        .match-head {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            gap: 0.75rem;
            margin-bottom: 0.35rem;
        }
        .match-id {
            color: var(--exe-blue);
            font-size: 0.76rem;
            font-weight: 900;
            letter-spacing: 0.02em;
        }
        .match-status {
            border-radius: 999px;
            font-size: 0.72rem;
            font-weight: 850;
            padding: 0.18rem 0.55rem;
            white-space: nowrap;
        }
        .match-badges {
            display: inline-flex;
            align-items: center;
            justify-content: flex-end;
            flex-wrap: wrap;
            gap: 0.3rem;
        }
        .prediction-saved-flag {
            border-radius: 999px;
            font-size: 0.72rem;
            font-weight: 900;
            padding: 0.18rem 0.55rem;
            color: #14532d;
            background: #dcfce7;
            border: 1px solid #86efac;
            white-space: nowrap;
        }
        .prediction-saved-note {
            margin-top: 0.48rem;
            padding: 0.42rem 0.55rem;
            border-radius: 8px;
            color: #14532d;
            background: #dcfce7;
            border: 1px solid #86efac;
            font-size: 0.78rem;
            font-weight: 850;
        }
        .match-status.open {
            background: var(--exe-green-soft);
            color: #166534;
            border: 1px solid #bdf7bb;
        }
        .match-status.locked {
            background: #fff1f2;
            color: var(--exe-red);
            border: 1px solid #fecdd3;
        }
        .match-title {
            display: grid;
            grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
            align-items: center;
            gap: 0.55rem;
            min-height: 38px;
            font-size: 0.98rem;
            font-weight: 850;
            line-height: 1.15;
        }
        .match-title span {
            min-width: 0;
            overflow-wrap: anywhere;
        }
        .match-title span:last-child {
            text-align: right;
        }
        .team-with-flag {
            display: inline-flex;
            align-items: center;
            gap: 0.42rem;
            min-width: 0;
        }
        .team-with-flag img {
            width: 25px;
            height: 18px;
            border-radius: 3px;
            object-fit: cover;
            box-shadow: 0 0 0 1px rgba(7, 20, 33, 0.14);
            flex: 0 0 auto;
        }
        .versus {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            color: #ffffff;
            background: var(--exe-blue-dark);
            border-radius: 999px;
            font-size: 0.68rem;
            text-transform: uppercase;
            font-weight: 900;
            width: 30px;
            height: 22px;
        }
        .match-time {
            color: var(--exe-muted);
            font-size: 0.78rem;
            margin-top: 0.16rem;
        }
        .match-lock-time {
            color: var(--exe-red);
            font-size: 0.7rem;
            font-weight: 850;
            margin-top: 0.12rem;
        }
        .broadcast-row {
            display: flex;
            align-items: center;
            flex-wrap: wrap;
            gap: 0.28rem;
            margin-top: 0.48rem;
        }
        .broadcast-row strong,
        .broadcast-row span {
            display: inline-flex;
            align-items: center;
            min-height: 22px;
            border-radius: 999px;
            font-size: 0.72rem;
            font-weight: 850;
            line-height: 1;
        }
        .broadcast-row strong {
            padding: 0 0.42rem;
            color: #ffffff;
            background: var(--exe-blue-dark);
        }
        .broadcast-row span {
            padding: 0 0.5rem;
            color: #0f2a44;
            background: #eef5ff;
            border: 1px solid #d9e8ff;
        }
        .score-separator {
            display: flex;
            align-items: center;
            justify-content: center;
            height: 38px;
            color: var(--exe-blue-dark);
            font-weight: 900;
            font-size: 1.25rem;
        }
        .section-title {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin: 0.35rem 0 0.85rem;
            color: var(--exe-ink);
            font-size: 1.05rem;
            font-weight: 900;
        }
        .section-title span {
            color: var(--exe-blue);
            background: #eef5ff;
            border: 1px solid #d9e8ff;
            border-radius: 999px;
            padding: 0.14rem 0.5rem;
            font-size: 0.78rem;
        }
        .mini-section-title {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin: 0.35rem 0 0.45rem;
            color: var(--exe-muted);
            font-size: 0.82rem;
            font-weight: 900;
            text-transform: uppercase;
        }
        .mini-section-title span {
            color: var(--exe-blue);
            font-size: 0.74rem;
        }
        .group-results-empty {
            margin: 0.35rem 0 1.2rem;
            padding: 0.55rem 0.7rem;
            border: 1px dashed var(--exe-border);
            border-radius: 8px;
            color: var(--exe-muted);
            background: var(--exe-surface-soft);
            font-size: 0.78rem;
            font-weight: 750;
        }
        .result-row {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 1rem;
        }
        .result-title {
            display: grid;
            grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
            align-items: center;
            gap: 0.85rem;
            margin-top: 0.36rem;
            font-size: 1.02rem;
            font-weight: 900;
        }
        .result-title strong {
            color: #ffffff;
            background: var(--exe-blue-dark);
            border: 1px solid #0f335f;
            border-radius: 8px;
            padding: 0.28rem 0.7rem;
            white-space: nowrap;
            box-shadow: inset 0 -2px 0 rgba(57, 230, 0, 0.25);
        }
        .result-title span:last-child {
            justify-content: flex-end;
            text-align: right;
        }
        .compact-result {
            display: grid;
            grid-template-columns: auto minmax(0, 1fr) auto minmax(0, 1fr);
            align-items: center;
            gap: 0.5rem;
            margin-bottom: 0.45rem;
            padding: 0.55rem 0.65rem;
            border: 1px solid var(--exe-border);
            border-radius: 8px;
            background: var(--exe-surface);
        }
        .compact-result strong {
            color: #ffffff;
            background: var(--exe-blue-dark);
            border-radius: 7px;
            padding: 0.2rem 0.5rem;
            font-weight: 950;
            white-space: nowrap;
        }
        .compact-result small {
            grid-column: 2 / -1;
            color: var(--exe-muted);
            font-size: 0.72rem;
            font-weight: 750;
        }
        .shared-predictions-card {
            margin-bottom: 1rem;
            overflow: hidden;
            border: 1px solid var(--exe-border);
            border-radius: 8px;
            background: var(--exe-surface);
            box-shadow: 0 8px 18px rgba(8, 33, 66, 0.05);
        }
        .shared-predictions-meta {
            padding: 0.45rem 0.7rem;
            color: var(--exe-muted);
            background: var(--exe-surface-soft);
            border-bottom: 1px solid var(--exe-border);
            font-size: 0.74rem;
            font-weight: 800;
        }
        .shared-prediction-row {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.75rem;
            min-height: 42px;
            padding: 0.48rem 0.7rem;
            border-bottom: 1px solid var(--exe-border);
        }
        .shared-prediction-row:last-child {
            border-bottom: 0;
        }
        .shared-prediction-user {
            min-width: 0;
            color: var(--exe-ink);
            font-weight: 850;
            overflow-wrap: anywhere;
        }
        .shared-prediction-row strong {
            border-radius: 999px;
            padding: 0.2rem 0.58rem;
            font-size: 0.82rem;
            font-weight: 950;
            white-space: nowrap;
        }
        .prediction-available {
            color: #ffffff;
            background: var(--exe-blue-dark);
        }
        .shared-predictions-empty {
            padding: 0.8rem;
            text-align: center;
            color: var(--exe-muted);
            font-size: 0.8rem;
            font-weight: 750;
        }
        .standings-wrap {
            width: 100%;
            overflow-x: auto;
            margin-bottom: 1rem;
            border: 1px solid var(--exe-border);
            border-radius: 8px;
            background: var(--exe-surface);
            box-shadow: 0 8px 18px rgba(8, 33, 66, 0.05);
        }
        .standings-table {
            width: 100%;
            min-width: 680px;
            border-collapse: collapse;
            font-size: 0.86rem;
        }
        .standings-table th,
        .standings-table td {
            padding: 0.58rem 0.62rem;
            border-bottom: 1px solid var(--exe-border);
            text-align: center;
            white-space: nowrap;
        }
        .standings-table th {
            color: var(--exe-muted);
            background: var(--exe-surface-soft);
            font-size: 0.72rem;
            font-weight: 900;
            text-transform: uppercase;
        }
        .standings-table tr:last-child td {
            border-bottom: 0;
        }
        .standings-team {
            min-width: 190px;
            text-align: left !important;
            color: var(--exe-ink);
            font-weight: 900;
        }
        .standing-rank {
            color: var(--exe-muted);
            font-weight: 900;
        }
        .standing-points {
            color: var(--exe-blue-dark);
            font-size: 1rem;
            font-weight: 950;
        }
        .ranking-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 1rem;
            margin-bottom: 0.55rem;
            padding: 0.72rem 0.85rem;
            border: 1px solid var(--exe-border);
            border-radius: 8px;
            background: #ffffff;
            box-shadow: 0 8px 18px rgba(8, 33, 66, 0.05);
        }
        .ranking-row.rank-1 {
            border-color: rgba(245, 197, 66, 0.75);
            background: linear-gradient(135deg, #fffaf0 0%, #ffffff 70%);
        }
        .ranking-row.rank-2,
        .ranking-row.rank-3 {
            background: linear-gradient(135deg, #f8fbff 0%, #ffffff 78%);
        }
        .rank-left {
            display: inline-flex;
            align-items: center;
            min-width: 0;
            gap: 0.7rem;
        }
        .rank-medal {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 32px;
            height: 32px;
            border-radius: 999px;
            background: var(--exe-blue-dark);
            color: #ffffff;
            font-weight: 900;
        }
        .rank-1 .rank-medal { background: var(--exe-gold); color: #241a00; }
        .rank-name {
            color: var(--exe-ink);
            font-weight: 900;
        }
        .rank-stats {
            display: grid;
            grid-template-columns: auto minmax(84px, auto);
            align-items: center;
            gap: 0.85rem;
        }
        .rank-points {
            display: inline-flex;
            align-items: baseline;
            gap: 0.25rem;
            color: var(--exe-muted);
        }
        .rank-points strong {
            color: var(--exe-blue-dark);
            font-size: 1.35rem;
            font-weight: 950;
        }
        .rank-ratio {
            display: flex;
            flex-direction: column;
            align-items: flex-end;
            gap: 0.08rem;
            padding-left: 0.85rem;
            border-left: 1px solid var(--exe-border);
        }
        .rank-ratio span {
            color: var(--exe-muted);
            font-size: 0.68rem;
            font-weight: 800;
            white-space: nowrap;
        }
        .rank-ratio strong {
            color: var(--exe-ink);
            font-size: 1rem;
            font-weight: 950;
        }
        .detail-card {
            margin-bottom: 0.6rem;
            padding: 0.75rem 0.85rem;
            border: 1px solid var(--exe-border);
            border-radius: 8px;
            background: #ffffff;
            box-shadow: 0 8px 18px rgba(8, 33, 66, 0.05);
        }
        .detail-top {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            flex-wrap: wrap;
        }
        .detail-participant {
            color: var(--exe-muted);
            font-size: 0.8rem;
            font-weight: 800;
        }
        .points-pill {
            margin-left: auto;
            border-radius: 999px;
            background: var(--exe-green-soft);
            color: #166534;
            border: 1px solid #bdf7bb;
            padding: 0.16rem 0.5rem;
            font-size: 0.75rem;
            font-weight: 900;
        }
        .detail-match {
            margin-top: 0.35rem;
            color: var(--exe-ink);
            font-weight: 900;
        }
        .detail-score-grid {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 0.55rem;
            margin-top: 0.55rem;
        }
        .detail-score-grid div {
            border: 1px solid #e7edf4;
            border-radius: 8px;
            background: #f8fbff;
            padding: 0.48rem 0.6rem;
        }
        .detail-score-grid span {
            display: block;
            color: var(--exe-muted);
            font-size: 0.72rem;
            font-weight: 800;
            text-transform: uppercase;
        }
        .detail-score-grid strong {
            display: block;
            color: var(--exe-blue-dark);
            font-size: 1.08rem;
            font-weight: 950;
        }
        .user-approval-row,
        .active-user-row {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.75rem;
            min-height: 42px;
            margin-bottom: 0.45rem;
            padding: 0.58rem 0.72rem;
            border: 1px solid var(--exe-border);
            border-radius: 8px;
            background: #ffffff;
        }
        .user-approval-row strong,
        .active-user-row strong {
            color: var(--exe-ink);
            font-weight: 900;
        }
        .user-approval-row span,
        .active-user-row span {
            color: var(--exe-muted);
            font-size: 0.78rem;
            font-weight: 800;
            text-transform: uppercase;
        }
        @media (prefers-color-scheme: dark) {
            :root {
                --exe-bg: #07111e;
                --exe-surface: #0d1828;
                --exe-surface-soft: #111f33;
                --exe-ink: #f7fbff;
                --exe-muted: #a6b4c4;
                --exe-border: #203047;
                --exe-shadow: 0 12px 30px rgba(0, 0, 0, 0.28);
            }
            .stApp { background: var(--exe-bg); }
            header[data-testid="stHeader"] { background: rgba(7, 17, 30, 0.82); }
            .app-shell-header,
            .metric-card,
            .ranking-row,
            .detail-card,
            .user-approval-row,
            .active-user-row,
            div[data-testid="stVerticalBlockBorderWrapper"] {
                background: var(--exe-surface);
            }
            .app-shell-header {
                background: linear-gradient(135deg, #0d1828 0%, #0a1423 60%, #102315 100%);
            }
            .brand-lockup img { background: #ffffff; }
            .brand-copy p,
            .session-chip,
            .header-session { color: var(--exe-muted); }
            .stTabs [data-baseweb="tab"] { color: #d5deea; }
            .stSelectbox label,
            .stNumberInput label,
            .stTextInput label {
                color: #dbe7f5;
            }
            .stNumberInput input,
            .stTextInput input,
            .stSelectbox [data-baseweb="select"] {
                background: #111f33;
                border-color: #2a3b55;
                color: #f7fbff;
            }
            .stNumberInput input,
            .stTextInput input {
                -webkit-text-fill-color: #f7fbff;
            }
            .detail-score-grid div { background: #111f33; border-color: #203047; }
            .result-title strong { border-color: #1d3b63; }
            .ranking-row.rank-1 { background: linear-gradient(135deg, rgba(245, 197, 66, 0.14), var(--exe-surface) 68%); }
            .ranking-row.rank-2,
            .ranking-row.rank-3 { background: linear-gradient(135deg, rgba(17, 85, 217, 0.16), var(--exe-surface) 74%); }
            .rank-points strong,
            .rank-ratio strong,
            .detail-score-grid strong,
            .standing-points,
            .score-separator {
                color: #f7fbff;
            }
            .compact-result strong {
                background: #1d4ed8;
                color: #ffffff;
            }
            .prediction-available {
                background: #1d4ed8;
                color: #ffffff;
            }
            .rank-points span,
            .metric-card span,
            .detail-score-grid span {
                color: #a6b4c4;
            }
            .match-status.locked {
                background: rgba(225, 29, 72, 0.16);
                color: #fecdd3;
                border-color: rgba(254, 205, 211, 0.32);
            }
            .match-status.open {
                background: rgba(57, 230, 0, 0.12);
                color: #bbf7d0;
                border-color: rgba(187, 247, 208, 0.28);
            }
            .prediction-saved-flag,
            .prediction-saved-note {
                color: #bbf7d0;
                background: rgba(34, 197, 94, 0.14);
                border-color: rgba(187, 247, 208, 0.32);
            }
            .broadcast-row strong {
                background: #1d4ed8;
                color: #ffffff;
            }
            .broadcast-row span {
                background: #111f33;
                border-color: #2a3b55;
                color: #dbe7f5;
            }
        }
        @media (max-width: 760px) {
            .block-container { padding-top: 0.55rem; }
            .app-shell-header {
                align-items: flex-start;
                flex-direction: column;
                gap: 0.65rem;
                padding: 0.75rem;
            }
            .brand-lockup { align-items: center; }
            .brand-lockup img { width: 62px; height: 62px; }
            .brand-copy h1 { font-size: 1.35rem; }
            .brand-copy p { font-size: 0.82rem; }
            .stTabs [data-baseweb="tab"] {
                min-height: 36px;
                height: 36px;
                padding: 0.3rem 0.62rem;
                font-size: 0.84rem;
            }
            .metric-card { min-height: 82px; padding: 0.68rem; }
            .metric-card strong { font-size: 1.55rem; }
            .match-title {
                grid-template-columns: 1fr;
                gap: 0.35rem;
            }
            .match-title span:last-child { text-align: left; }
            .versus { width: 28px; height: 20px; }
            .result-row {
                align-items: flex-start;
                flex-direction: column;
            }
            .result-title {
                grid-template-columns: 1fr;
                gap: 0.45rem;
            }
            .result-title span:last-child {
                justify-content: flex-start;
                text-align: left;
            }
            .points-pill { margin-left: 0; }
            .detail-score-grid { grid-template-columns: 1fr; }
            .ranking-row {
                gap: 0.55rem;
            }
            .rank-left {
                gap: 0.45rem;
            }
            .rank-stats {
                gap: 0.45rem;
            }
            .rank-ratio {
                min-width: 72px;
                padding-left: 0.45rem;
            }
            .rank-ratio span {
                font-size: 0.6rem;
            }
            .compact-result {
                grid-template-columns: auto minmax(0, 1fr) auto;
            }
            .compact-result span:nth-of-type(3) {
                grid-column: 2 / -1;
            }
            .compact-result small {
                grid-column: 2 / -1;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
