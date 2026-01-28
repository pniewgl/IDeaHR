import streamlit as st

# Ustawienie strony musi być PIERWSZĄ komendą Streamlit
st.set_page_config(page_title="Fabian AI Recruiter", layout="wide")

# Importy
import Rekruter_AI
import hr_dashboard

# --- KONTROLA STANU GCP ---
# Sprawdzamy czy inicjalizacja w Rekruter_AI się powiodła
gcp_initialized = st.session_state.get("gcp_clients_initialized", False)

if not gcp_initialized:
    st.error("❌ APLIKACJA NIEDOSTĘPNA - Błąd połączenia z chmurą Google.")

    error_msg = st.session_state.get('gcp_init_error', 'Nieznany błąd inicjalizacji.')
    st.code(error_msg, language="text")

    st.warning("""
    Wskazówki naprawcze:
    1. Sprawdź czy plik secrets.toml w Streamlit Cloud ma poprawną strukturę JSON.
    2. Sprawdź czy włączone są API: Vertex AI, BigQuery, Storage w Google Cloud Console.
    3. Sprawdź czy service account ma uprawnienia (Vertex AI User, BigQuery Admin, Storage Admin).
    """)
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
        desc = st.text_area("Wklej treść ogłoszenia o pracę (Kontekst dla AI)", height=150, key="hr_desc")
        if st.button("💾 Zapisz kontekst ogłoszenia"):
            st.session_state.active_job_description = desc
            st.success("Zapisano! AI będzie teraz oceniać kandydatów pod kątem tego ogłoszenia.")

    with col2:
        if st.button("🔄 Odśwież listę kandydatów"):
            st.rerun()

    st.divider()

    # Pobranie listy
    candidates = hr_dashboard.get_candidates()

    if candidates:
        st.dataframe(candidates, use_container_width=True)

        st.subheader("Generowanie Raportu AI")
        selected_id = st.selectbox(
            "Wybierz kandydata do analizy:",
            options=[c['id_kandydata'] for c in candidates],
            format_func=lambda x: f"ID: {x}..."
        )

        if st.button("📝 Generuj Raport i Rekomendację"):
            if not st.session_state.get("active_job_description"):
                st.warning("Najpierw wklej i zapisz treść ogłoszenia powyżej!")
            else:
                hr_dashboard.generate_report(selected_id, st.session_state.get("active_job_description"))
    else:
        st.info("Brak kandydatów w bazie. Prześlij CV w pierwszej zakładce, aby zobaczyć dane.")