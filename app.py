from __future__ import annotations

import base64
from collections import defaultdict
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

import streamlit as st

from polla.config import config_path, load_json
from polla.models import FinalPicks, GroupPick, MatchResult
from polla.scoring import score_all
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
    "Curaçao": "cw",
    "Czech Republic": "cz",
    "Côte d'Ivoire": "ci",
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
    "Türkiye": "tr",
    "United States": "us",
    "Uruguay": "uy",
    "Uzbekistan": "uz",
}

TEAM_CODES.update(
    {
        "Curaçao": "cw",
        "Côte d'Ivoire": "ci",
        "Türkiye": "tr",
    }
)


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

    tabs = ["Mis marcadores", "Resultados", "Top 3 grupos", "Finales", "Ranking", "Detalle", "Mi cuenta"]
    if role == "admin" or _is_group_admin(participant, active_group.group_id, state):
        tabs.append("Admin")
    rendered_tabs = st.tabs(tabs)
    with rendered_tabs[0]:
        match_predictions_view(participant, state)
    with rendered_tabs[1]:
        results_view(state)
    with rendered_tabs[2]:
        group_picks_view(participant, state)
    with rendered_tabs[3]:
        final_picks_view(participant, state)
    with rendered_tabs[4]:
        ranking_view(state, active_group.group_id)
    with rendered_tabs[5]:
        detail_view(state, active_group.group_id)
    with rendered_tabs[6]:
        account_view(participant, state, active_group)
    if role == "admin" or _is_group_admin(participant, active_group.group_id, state):
        with rendered_tabs[7]:
            admin_view(participant, state, active_group)


def render_header(participant: str | None = None, active_group: Any | None = None) -> None:
    logo_data = base64.b64encode(LOGO_PATH.read_bytes()).decode("ascii")
    group_label = f" · {escape(active_group.name)}" if active_group else ""
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
    active_users = [user for user in state["users"] if user.active]
    names = [user.participant for user in active_users]
    with st.form("login"):
        participant = st.selectbox("Usuario", names)
        pin = st.text_input("PIN", type="password")
        submitted = st.form_submit_button("Entrar")
    if submitted:
        user = next((item for item in active_users if item.participant == participant), None)
        if not user or not verify_pin(participant, pin, user.pin_hash):
            st.error("Usuario o PIN invalido.")
        else:
            st.session_state["participant"] = user.participant
            st.session_state["role"] = user.role
            st.rerun()

    st.divider()
    with st.expander("Registrarme como nuevo usuario"):
        with st.form("register_user"):
            new_participant = st.text_input("Nombre corto")
            new_pin = st.text_input("PIN", type="password", key="register_pin")
            confirm_pin = st.text_input("Confirmar PIN", type="password", key="register_confirm_pin")
            invite_code = st.text_input("Codigo de grupo (opcional)").strip().upper()
            register_submitted = st.form_submit_button("Enviar solicitud")
        if register_submitted:
            cleaned_participant = _clean_participant(new_participant)
            validation_error = _registration_error(cleaned_participant, new_pin, confirm_pin, state["users"])
            if validation_error:
                st.error(validation_error)
                if any(user.participant.casefold() == cleaned_participant.casefold() for user in state["users"]):
                    st.info("Sugerencias disponibles: " + ", ".join(_username_suggestions(cleaned_participant, state["users"])))
                return
            invite_group = None
            if invite_code:
                invite_group = store.group_by_invite_code(invite_code)
                if not invite_group:
                    st.error("El codigo de grupo no existe.")
                    return
            try:
                store.create_user(cleaned_participant, hash_pin(cleaned_participant, new_pin), role="player", active=True)
                if invite_group:
                    store.create_membership(invite_group.group_id, cleaned_participant, role="player", status="pending")
            except Exception:
                st.error("No se pudo crear la solicitud. Revisa si el nombre ya existe e intenta de nuevo.")
                return
            load_state.clear()
            if invite_group:
                st.success("Usuario creado. Tu solicitud de grupo quedo pendiente de aprobacion.")
            else:
                st.success("Usuario creado. Entra y crea un grupo o solicita unirte a uno.")

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
    _metric_card(metric_cols[0], "Marcadores guardados", saved_count, "score")
    _metric_card(metric_cols[1], "Partidos abiertos", open_count, "open")
    _metric_card(metric_cols[2], "Partidos cerrados", locked_count, "closed")

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


def ranking_view(state: dict[str, Any], group_id: str) -> None:
    ranking, _detail = _score_state(state, group_id)
    if not ranking:
        st.info("Todavía no hay puntos calculados.")
        return
    st.markdown('<div class="section-title">Tabla de posiciones</div>', unsafe_allow_html=True)
    for idx, row in enumerate(ranking, start=1):
        raw_rank = row.get("rank") or idx
        try:
            rank_num = int(raw_rank)
        except (TypeError, ValueError):
            rank_num = idx
        participant = escape(str(row.get("participant", "")))
        points = escape(str(row.get("points", 0)))
        medal = {1: "1", 2: "2", 3: "3"}.get(rank_num, str(raw_rank))
        st.markdown(
            f"""
            <div class="ranking-row rank-{rank_num}">
              <div class="rank-left">
                <span class="rank-medal">{medal}</span>
                <span class="rank-name">{participant}</span>
              </div>
              <div class="rank-points"><strong>{points}</strong><span>pts</span></div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def results_view(state: dict[str, Any]) -> None:
    results = sorted(
        [result for result in state["results"] if result.confirmed],
        key=lambda item: item.kickoff_at or datetime.max.replace(tzinfo=BOGOTA),
    )
    if not results:
        st.info("Todavía no hay resultados reales confirmados.")
        return

    st.markdown(f'<div class="section-title">Resultados confirmados <span>{len(results)}</span></div>', unsafe_allow_html=True)
    for result in results:
        score = _score_text(result.goals_a_real, result.goals_b_real)
        kickoff = result.kickoff_at.strftime("%Y-%m-%d %H:%M") if result.kickoff_at else "Horario por definir"
        source = result.source or "Automático"
        with st.container(border=True):
            st.markdown(
                f"""
                <div class="result-row">
                  <div>
                    <div class="match-id">{result.match_id} · {result.phase or "Sin fase"}</div>
                    <div class="result-title">
                      <span>{_team_html(result.team_a)}</span>
                      <strong>{score}</strong>
                      <span>{_team_html(result.team_b)}</span>
                    </div>
                    <div class="match-time">{kickoff} · Fuente: {source}</div>
                  </div>
                  <span class="match-status open">Confirmado</span>
                </div>
                """,
                unsafe_allow_html=True,
            )


def detail_view(state: dict[str, Any], group_id: str) -> None:
    _ranking, detail = _score_state(state, group_id)
    if not detail:
        st.info("Todavía no hay detalle de puntos.")
        return
    participants = sorted({str(row.get("participant", "")) for row in detail if row.get("participant")})
    selected = st.selectbox("Participante", ["Todos"] + participants, key="detail_participant")
    rows = [row for row in detail if selected == "Todos" or row.get("participant") == selected]
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
            invite_code = st.text_input("Codigo de invitacion").strip().upper()
            join_submitted = st.form_submit_button("Unirme a grupo")
        if join_submitted:
            group = store.group_by_invite_code(invite_code)
            if not group:
                st.error("El codigo de grupo no existe.")
            elif _membership_for(participant, group.group_id, state):
                st.info("Ya tienes una solicitud o membresia en ese grupo.")
            else:
                store.create_membership(group.group_id, participant, role="player", status="pending")
                load_state.clear()
                st.success("Solicitud enviada al admin del grupo.")
                st.rerun()

    with group_cols[1]:
        with st.form("create_group"):
            group_name = st.text_input("Nombre del grupo")
            desired_code = st.text_input("Codigo de invitacion").strip().upper()
            create_submitted = st.form_submit_button("Crear grupo")
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
        ranking, detail = _score_rows_by_group(state)
        store.replace_rows("Ranking", ranking)
        store.replace_rows("Detail", _fit_detail_rows(detail))
        load_state.clear()
        st.success("Ranking guardado en Supabase.")


def _score_state(state: dict[str, Any], group_id: str | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ranking, detail = score_all(
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
    if not group_id:
        return ranking, detail
    participants = _active_participants_for_group(group_id, state)
    ranking = [row for row in ranking if row.get("participant") in participants]
    for idx, row in enumerate(ranking, start=1):
        row["rank"] = idx
    detail = [row for row in detail if row.get("participant") in participants]
    return ranking, detail


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
            <div class="match-card-top">
              <div>
                <span class="match-id">{match.match_id}</span>
                <div class="match-time">{caption}</div>
              </div>
              <span class="match-status {'locked' if locked else 'open'}">{status}</span>
            </div>
            <div class="match-title">
              <span>{_team_html(match.team_a)}</span>
              <span class="versus">vs</span>
              <span>{_team_html(match.team_b)}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        with st.form(f"pred_{match.match_id}"):
            col_a, score_sep, col_b, col_save = st.columns([0.8, 0.18, 0.8, 0.75], vertical_alignment="bottom")
            goals_a = col_a.number_input(
                match.team_a,
                min_value=0,
                max_value=20,
                value=_default_int(pred.goals_a_pred if pred else None),
                step=1,
                disabled=locked,
                key=f"{match.match_id}_a",
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
                key=f"{match.match_id}_b",
                label_visibility="collapsed",
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
    group = f' · Grupo: <strong>{escape(active_group.name)}</strong>' if active_group else ""
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
              <span>{escape(active_marker)} · {escape(group.invite_code)}</span>
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


def _team_html(team: str) -> str:
    code = TEAM_CODES.get(team)
    safe_team = escape(team)
    if not code:
        return safe_team
    return f'<span class="team-with-flag"><img src="https://flagcdn.com/{code}.svg" alt="" loading="lazy" />{safe_team}</span>'


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
            .detail-score-grid div { background: #111f33; border-color: #203047; }
            .result-title strong { border-color: #1d3b63; }
            .ranking-row.rank-1 { background: linear-gradient(135deg, rgba(245, 197, 66, 0.14), var(--exe-surface) 68%); }
            .ranking-row.rank-2,
            .ranking-row.rank-3 { background: linear-gradient(135deg, rgba(17, 85, 217, 0.16), var(--exe-surface) 74%); }
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
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
