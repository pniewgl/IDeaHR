import streamlit as st

# TO MUSI BYĆ PIERWSZA LINIA
st.set_page_config(page_title="Fabian AI Recruiter", layout="wide")

# Importy
import Rekruter_AI
import hr_dashboard

# --- DIAGNOSTYKA STARTOWA ---
if not st.session_state.get("gcp_clients_initialized"):
    st.error("❌ APLIKACJA NIEDOSTĘPNA - Błąd inicjalizacji chmury.")
    st.code(st.session_state.get('gcp_init_error', 'Nieznany błąd.'), language="text")
    st.stop()

# --- INTERFEJS ---
st.title("Fabian: Platforma AI Rekrutera")

tab1, tab2 = st.tabs(["🤖 Rozmowa z Kandydatem", "📊 Panel HR"])

with tab1:
    Rekruter_AI.run_candidate_interface()

with tab2:
    st.header("Panel Zarządzania Rekrutacją")

    col1, col2 = st.columns([2, 1])
    with col1:
        desc = st.text_area("Wklej ogłoszenie o pracę", height=150, key="hr_desc")
        if st.button("Zapisz ogłoszenie"):
            st.session_state.active_job_description = desc
            st.success("Zapisano!")

    with col2:
        if st.button("Odśwież listę"): st.rerun()

    candidates = hr_dashboard.get_candidates()

    if candidates:
        st.dataframe(candidates, use_container_width=True)
        selected_id = st.selectbox("Wybierz kandydata", [c['id_kandydata'] for c in candidates])

        if st.button("Generuj Raport"):
            if not st.session_state.get("active_job_description"):
                st.warning("Najpierw wklej treść ogłoszenia!")
            else:
                hr_dashboard.generate_report(selected_id, st.session_state.get("active_job_description"))
    else:
        st.info("Brak kandydatów w bazie.")