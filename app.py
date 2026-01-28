import streamlit as st
import Rekruter_AI
import hr_dashboard

st.set_page_config(page_title="Fabian AI", layout="wide")

# Sprawdzenie inicjalizacji
if not st.session_state.get("gcp_clients_initialized"):
    st.error("Błąd połączenia z Google Cloud.")
    st.code(st.session_state.get("gcp_init_error", "Nieznany błąd"))
    st.stop()

st.title("Fabian: System Rekrutacji AI")

tab1, tab2 = st.tabs(["Kandydat (Chat)", "HR Dashboard (Admin)"])

with tab1:
    Rekruter_AI.run_candidate_interface()

with tab2:
    st.header("Panel HR")
    desc = st.text_area("Wklej treść ogłoszenia", key="hr_desc")
    if st.button("Zapisz ogłoszenie"):
        st.session_state.active_job_description = desc
        st.success("Zapisano!")

    if st.button("Odśwież listę"): st.rerun()

    candidates = hr_dashboard.get_candidates()
    if candidates:
        st.dataframe(candidates)
        selected = st.selectbox("Wybierz kandydata", [c['id_kandydata'] for c in candidates])
        if st.button("Generuj Raport"):
            hr_dashboard.generate_report(selected, st.session_state.get("active_job_description"))
    else:
        st.info("Brak kandydatów.")