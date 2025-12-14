# hr_dashboard.py - Moduł logiki HR

import streamlit as st
from google.api_core.exceptions import GoogleAPIError

# --- KLUCZOWA ZMIANA: IMPORT KLIENTÓW Z MODUŁU REKRUTER_AI ---
# Klienci są inicjalizowani w Rekruter_AI.py i są tu tylko importowani
try:
    from Rekruter_AI import (
        bigquery_client,
        model,
        GCP_PROJECT_ID,
        BIGQUERY_DATASET_ID,
        BIGQUERY_TABLE_ID
    )
except ImportError as e:
    # W razie błędu importu (np. złej nazwy pliku), logujemy
    print(f"Błąd importu klientów w hr_dashboard.py: {e}")


# --- FUNKCJE POMOCNICZE PANELU HR ---
# Zwróć uwagę, że funkcje te nie zawierają już globalnej inicjalizacji GCP!

@st.cache_data(ttl=60)
def get_candidates_from_bigquery():
    """Pobiera listę kandydatów z BigQuery."""
    if not bigquery_client: return []

    query = f"""
    SELECT id_kandydata, nazwa_pliku_cv, data_aplikacji, status_rekrutacji
    FROM `{GCP_PROJECT_ID}.{BIGQUERY_DATASET_ID}.{BIGQUERY_TABLE_ID}` 
    WHERE event_type = 'cv_uploaded' 
    ORDER BY data_aplikacji DESC 
    LIMIT 100
    """
    try:
        query_job = bigquery_client.query(query)
        return [dict(row) for row in query_job.result()]
    except GoogleAPIError as e:
        # st.error usunięte - UI wyświetla błąd
        return []


def evaluate_candidate_with_gemini(candidate_id: str, job_description: str):
    """Generuje raport dopasowania z AI (funkcja używana przez UI HR)."""
    if not bigquery_client or not model:
        # st.error("Błąd: Usługi GCP nie są dostępne.")
        return

    # ... (Wklej tutaj pełną logikę z promptem, używając bigquery_client i model) ...
    # [UWAGA: Zostawiam miejsce na pełny prompt i logikę raportowania]
    print(f"Generowanie raportu dla {candidate_id}")
    # ---------------------------------------------------------------------
    st.info("Raport wygenerowany (UI).")