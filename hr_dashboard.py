import streamlit as st
from google.api_core.exceptions import GoogleAPIError

# Import klientów z głównego modułu
try:
    from Rekruter_AI import bigquery_client, model, GCP_PROJECT_ID, BIGQUERY_DATASET_ID, BIGQUERY_TABLE_ID
except ImportError:
    pass  # Obsłużone w app.py


def get_candidates():
    if not bigquery_client: return []
    q = f"SELECT id_kandydata, nazwa_pliku_cv, data_aplikacji, status_rekrutacji FROM `{GCP_PROJECT_ID}.{BIGQUERY_DATASET_ID}.{BIGQUERY_TABLE_ID}` WHERE event_type='cv_uploaded' ORDER BY data_aplikacji DESC LIMIT 50"
    try:
        return [dict(row) for row in bigquery_client.query(q).result()]
    except:
        return []


def generate_report(cid, job_desc):
    st.info(f"Generowanie raportu dla {cid}...")
    q = f"""
    SELECT t1.umiejetnosci_tech, t2.transkrypcja_rozmowy_ai 
    FROM `{GCP_PROJECT_ID}.{BIGQUERY_DATASET_ID}.{BIGQUERY_TABLE_ID}` t1
    LEFT JOIN `{GCP_PROJECT_ID}.{BIGQUERY_DATASET_ID}.{BIGQUERY_TABLE_ID}` t2 
    ON t1.id_kandydata = t2.id_kandydata AND t2.event_type='transcript_saved'
    WHERE t1.id_kandydata='{cid}' AND t1.event_type='cv_uploaded'
    """
    try:
        data = next(bigquery_client.query(q).result(), None)
        if not data: st.error("Brak danych"); return

        prompt = f"""
        Oceń kandydata pod kątem ogłoszenia: {job_desc}
        CV: {data.umiejetnosci_tech}
        Rozmowa: {data.transkrypcja_rozmowy_ai}
        Stwórz raport: 1. Dopasowanie CV, 2. Ocena rozmowy, 3. Rekomendacja (Tak/Nie).
        """
        resp = model.generate_content(prompt)
        st.markdown(resp.text)
    except Exception as e:
        st.error(f"Błąd raportu: {e}")