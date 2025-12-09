import streamlit as st
from google.cloud import storage, bigquery
from google.api_core.exceptions import GoogleAPIError
from google.oauth2 import service_account
from google.cloud import discoveryengine_v1 as discoveryengine
from google.api_core.client_options import ClientOptions
import vertexai
from vertexai.preview.generative_models import GenerativeModel
import uuid
from datetime import datetime
import json
from PyPDF2 import PdfReader
import os
import time

# --- KONFIGURACJA STAŁYCH ---
BUCKET_NAME = "demo-cv-rekrutacja-hrdreamer2"
GCP_PROJECT_ID = "ai-recruiter-prod"
GCP_GEMINI_LOCATION = "europe-central2"
GCP_SEARCH_LOCATION = "eu"
DATA_STORE_ID = "ai-rekruter-wiedza_1759606950652"
BIGQUERY_DATASET_ID = "rekrutacja_hr"
BIGQUERY_TABLE_ID = "Kandydaci"
MODEL_NAME = "gemini-2.5-flash-lite"

# --- ZMIENNE GLOBALNE I INICJALIZACJA GCP ---
bigquery_client = None
storage_client = None
search_client = None
model = None


@st.cache_resource
def setup_gcp_clients():
    """Inicjalizuje wszystkich klientów GCP raz i bezpiecznie pobiera poświadczenia z secrets.toml."""

    if 'gcp_service_account' not in st.secrets:
        # Zgłoś błąd, który zostanie obsłużony niżej w kodzie
        raise Exception("Brak sekcji 'gcp_service_account' w secrets.toml.")

    # 1. Przygotowanie Poświadczeń
    service_account_info = json.loads(st.secrets["gcp_service_account"]["keyfile_json"])
    credentials = service_account.Credentials.from_service_account_info(service_account_info)

    # Tworzenie pliku tymczasowego dla Vertex AI
    temp_gcp_key_path = "temp_gcp_credentials.json"
    with open(temp_gcp_key_path, "w") as f:
        json.dump(service_account_info, f)
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = temp_gcp_key_path

    # 2. Tworzenie Klientów
    bq_client = bigquery.Client(credentials=credentials, project=GCP_PROJECT_ID)
    st_client = storage.Client(credentials=credentials, project=GCP_PROJECT_ID)
    client_options = ClientOptions(api_endpoint=f"{GCP_SEARCH_LOCATION}-discoveryengine.googleapis.com")
    sr_client = discoveryengine.SearchServiceClient(client_options=client_options, credentials=credentials)
    vertexai.init(project=GCP_PROJECT_ID, location=GCP_GEMINI_LOCATION)
    ai_model = GenerativeModel(MODEL_NAME)

    return bq_client, st_client, sr_client, ai_model


# Globalne wywołanie inicjalizacji
try:
    bigquery_client, storage_client, search_client, model = setup_gcp_clients()
    st.session_state.gcp_clients_initialized = True
except Exception as e:
    st.session_state.gcp_clients_initialized = False
    st.session_state.gcp_init_error = str(e)

# --- ZMIENNE STANU SESJI ---
if "messages" not in st.session_state:
    st.session_state.messages = []
if "cv_uploaded_id" not in st.session_state:
    st.session_state.cv_uploaded_id = None
if "active_job_description" not in st.session_state:
    st.session_state.active_job_description = ""


# --- FUNKCJE POMOCNICZE (LOGIKA) ---
# Uwaga: Funkcje logiczne, które były w hr_dashboard.py, zostają w Rekruter_AI.py
# aby zminimalizować ryzyko błędów importu

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
        st.error(f"Błąd podczas pobierania danych z BigQuery: {e}")
        return []


def evaluate_candidate_with_gemini(candidate_id: str, job_description: str):
    """Generuje raport dopasowania z AI."""
    if not bigquery_client or not model:
        st.error("Błąd: Usługi GCP nie są dostępne.")
        return

    st.info(f"Rozpoczynam zaawansowaną ocenę kandydata {candidate_id}...")
    # ... (Pełna definicja promptu, tak jak w ostatniej poprawnej wersji) ...
    # Zastąp ten komentarz pełnym promptem z funkcją query do BigQuery i generacją raportu:
    st.error("Kod promptu do oceny został celowo skrócony. Wklej go tutaj z poprzedniej wersji.")
    # Koniec funkcji, reszta logiki musi być wklejona z poprzedniej wersji


# --- RUNTIME FUNKCJE GŁÓWNE ---

def run_hr_dashboard_interface():
    """Rysuje interfejs HR Dashboard w bocznym pasku."""

    st.sidebar.title("📋 HR Dashboard")

    # ... (Wklej tutaj cały kod UI z pliku hr_dashboard.py, np. st.header, st.text_area, st.button, st.dataframe,
    #       ale wewnątrz st.sidebar.xxx)
    # Ze względu na długość, wklej całą logikę UI HR Dashboard tutaj.


def run_candidate_interface():
    """Rysuje interfejs kandydata w głównym oknie."""

    st.title("🤖 Fabian: Wirtualna Rekrutacja AI")

    if not st.session_state.gcp_clients_initialized:
        st.error(f"Usługi GCP nie zostały poprawnie zainicjalizowane. Błąd: {st.session_state.gcp_init_error}")
        return

    # ... (Wklej tutaj całą logikę UI Kandydata z Rekruter_AI.py: st.markdown, st.file_uploader, st.chat_input) ...
    # ... (Funkcje: upload_to_gcs, analyze_cv_with_gemini, chat_with_ai_agent_via_llm muszą być wklejone lub zaimportowane)


# --- WYWOŁANIE GŁÓWNE ---
# Rysujemy dashboard w bocznym pasku i interfejs kandydata w głównym oknie
run_hr_dashboard_interface()
run_candidate_interface()