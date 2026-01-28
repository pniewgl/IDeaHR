import streamlit as st

# --- IMPORT KLIENTÓW ---
# Pobieramy gotowe obiekty z Rekruter_AI.py
# NIE ROBIMY TU ŻADNEGO vertexai.init() ANI bigquery.Client()
try:
    from Rekruter_AI import (
        bigquery_client, 
        model, 
        GCP_PROJECT_ID, 
        BIGQUERY_DATASET_ID, 
        BIGQUERY_TABLE_ID
    )
except ImportError:
    bigquery_client = None
    model = None

def get_candidates():
    if not bigquery_client: 
        # Cicha obsługa błędu, by nie wywalać błędu Metadata
        return []
        
    q = f"""
    SELECT id_kandydata, nazwa_pliku_cv, data_aplikacji, status_rekrutacji 
    FROM `{GCP_PROJECT_ID}.{BIGQUERY_DATASET_ID}.{BIGQUERY_TABLE_ID}` 
    WHERE event_type='cv_uploaded' 
    ORDER BY data_aplikacji DESC LIMIT 50
    """
    try:
        return [dict(row) for row in bigquery_client.query(q).result()]
    except Exception:
        return []

def generate_report(cid, job_desc):
    if not bigquery_client or not model:
        st.error("Usługi AI niedostępne - sprawdź konfigurację w Rekruter_AI.")
        return

    st.info(f"Generowanie raportu dla {cid}...")
    
    q = f"""
    SELECT t1.umiejetnosci_tech, t2.transkrypcja_rozmowy_ai 
    FROM `{GCP_PROJECT_ID}.{BIGQUERY_DATASET_ID}.{BIGQUERY_TABLE_ID}` t1
    LEFT JOIN `{GCP_PROJECT_ID}.{BIGQUERY_DATASET_ID}.{BIGQUERY_TABLE_ID}` t2 
    ON t1.id_kandydata = t2.id_kandydata AND t2.event_type='transcript_saved'
    WHERE t1.id_kandydata='{cid}' AND t1.event_type='cv_uploaded'
    """
    
    try:
        query_job = bigquery_client.query(q)
        results = list(query_job.result())
        
        if not results:
            st.warning("Brak danych transkrypcji.")
            return
            
        data = results[0]
        
        prompt = f"""
        Jesteś Senior Rekruterem. Oceń kandydata pod kątem ogłoszenia: {job_desc}
        ANALIZA CV: {data.umiejetnosci_tech}
        PRZEBIEG ROZMOWY: {data.transkrypcja_rozmowy_ai}
        Stwórz raport: 1. Dopasowanie (%), 2. Mocne strony, 3. Decyzja.
        """
        
        resp = model.generate_content(prompt)
        st.success("Raport gotowy:")
        st.markdown(resp.text)
        
    except Exception as e:
        st.error(f"Błąd generowania raportu: {e}")
