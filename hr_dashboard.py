import streamlit as st

# --- KLUCZOWE: Importujemy zainicjalizowanych klientów z Rekruter_AI ---
# Dzięki temu nie musimy ponownie się logować i unikamy błędu metadata
try:
    from Rekruter_AI import (
        bigquery_client,
        model,
        GCP_PROJECT_ID,
        BIGQUERY_DATASET_ID,
        BIGQUERY_TABLE_ID
    )
except ImportError:
    # Ten błąd obsłuży app.py, tutaj tylko pass
    bigquery_client = None
    model = None
    pass


def get_candidates():
    if not bigquery_client:
        st.error("Błąd: Brak połączenia z BigQuery (Klient niezainicjowany).")
        return []

    q = f"""
    SELECT id_kandydata, nazwa_pliku_cv, data_aplikacji, status_rekrutacji 
    FROM `{GCP_PROJECT_ID}.{BIGQUERY_DATASET_ID}.{BIGQUERY_TABLE_ID}` 
    WHERE event_type='cv_uploaded' 
    ORDER BY data_aplikacji DESC LIMIT 50
    """
    try:
        return [dict(row) for row in bigquery_client.query(q).result()]
    except Exception as e:
        st.error(f"Błąd pobierania listy kandydatów: {e}")
        return []


def generate_report(cid, job_desc):
    if not bigquery_client or not model:
        st.error("Usługi AI niedostępne.")
        return

    st.info(f"Generowanie raportu dla {cid}...")

    # Pobieranie danych kandydata
    q = f"""
    SELECT t1.umiejetnosci_tech, t2.transkrypcja_rozmowy_ai 
    FROM `{GCP_PROJECT_ID}.{BIGQUERY_DATASET_ID}.{BIGQUERY_TABLE_ID}` t1
    LEFT JOIN `{GCP_PROJECT_ID}.{BIGQUERY_DATASET_ID}.{BIGQUERY_TABLE_ID}` t2 
    ON t1.id_kandydata = t2.id_kandydata AND t2.event_type='transcript_saved'
    WHERE t1.id_kandydata='{cid}' AND t1.event_type='cv_uploaded'
    """

    try:
        query_job = bigquery_client.query(q)
        # Pobieramy pierwszy wynik
        results = list(query_job.result())

        if not results:
            st.warning("Nie znaleziono pełnych danych kandydata (może brak transkrypcji rozmowy?).")
            return

        data = results[0]

        prompt = f"""
        Jesteś Senior Rekruterem. Oceń kandydata pod kątem ogłoszenia: {job_desc}

        ANALIZA CV: {data.umiejetnosci_tech}
        PRZEBIEG ROZMOWY: {data.transkrypcja_rozmowy_ai}

        Stwórz raport w formacie Markdown:
        1. Stopień dopasowania (0-100%)
        2. Mocne strony
        3. Czerwone flagi
        4. Decyzja: Zaprosić na II etap?
        """

        resp = model.generate_content(prompt)
        st.success("Raport gotowy:")
        st.markdown(resp.text)

    except Exception as e:
        st.error(f"Błąd generowania raportu: {e}")