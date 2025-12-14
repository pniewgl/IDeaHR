# app.py - Główny plik startowy UI

import streamlit as st
# Importujemy moduły logiki i ich funkcje
import Rekruter_AI
import hr_dashboard

# --- Ustawienia Strony ---
st.set_page_config(layout="wide", page_title="Fabian AI Recruiter")

# --- KONTROLA STANU GCP ---
# Inicjalizacja jest wykonywana, gdy Streamlit wczytuje Rekruter_AI.py
gcp_initialized = st.session_state.get("gcp_clients_initialized", False)

if not gcp_initialized:
    st.error("❌ APLIKACJA NIEDOSTĘPNA")
    st.markdown(f"**Nie udało się nawiązać połączenia z usługami Google Cloud Platform.**")
    st.code(st.session_state.get('gcp_init_error', 'Brak szczegółowego błędu. Sprawdź logi.'), language="text")
    st.markdown("---")
    st.markdown(
        "⚠️ **Potencjalne rozwiązanie:** Upewnij się, że klucz `keyfile_json` w pliku `secrets.toml` jest poprawny (invalid_grant: Invalid grant).")
    st.stop()

# --- INTERFEJS GŁÓWNY (UI) ---
st.title("Fabian: Platforma AI Rekrutera")

tab1, tab2 = st.tabs(["🤖 Rekruter AI (Kandydat)", "📊 HR Dashboard (Raporty)"])

with tab1:
    # Używamy funkcji run_candidate_interface z modułu Rekruter_AI
    Rekruter_AI.run_candidate_interface()

with tab2:
    # W tym miejscu musisz ręcznie narysować UI HR Dashboard i wywołać funkcje z hr_dashboard

    st.header("Aktywne Ogłoszenie o Pracę")
    st.markdown("Wklej tutaj ogłoszenie, na które prowadzona będzie rekrutacja.")

    # ... (Wklej całą logikę UI HR Dashboard z poprzedniego pliku - st.text_area, st.button, st.dataframe, st.selectbox)
    # Wywołanie funkcji logicznych z zaimportowanego modułu:

    # Przykład:
    candidates_data = hr_dashboard.get_candidates_from_bigquery()
    if candidates_data:
        st.dataframe(candidates_data)
        # Inny przykład:
        if st.button("Generuj Raport"):
            # UWAGA: Musisz pobrać ID i Job_desc z UI, a następnie wywołać funkcję
            hr_dashboard.evaluate_candidate_with_gemini("example_id", "example_job_desc")
    else:
        st.info("Brak kandydatów.")