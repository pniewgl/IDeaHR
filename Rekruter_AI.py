# Rekruter_AI.py - Moduł logiki GCP
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
import tempfile
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

# --- ZMIENNE GLOBALNE (Klienci) ---
bigquery_client = None
storage_client = None
search_client = None
model = None


# --- FUNKCJA INICJALIZUJĄCA GCP (Krytyczna) ---
@st.cache_resource
def setup_gcp_clients():
    """Inicjalizuje wszystkich klientów GCP raz i bezpiecznie pobiera poświadczenia z secrets."""
    global bigquery_client, storage_client, search_client, model

    if 'gcp_service_account' not in st.secrets:
        raise Exception("Brak sekcji 'gcp_service_account' w secrets.toml.")

    service_account_info = json.loads(st.secrets["gcp_service_account"]["keyfile_json"])
    credentials = service_account.Credentials.from_service_account_info(service_account_info)

    # Tworzenie tymczasowego pliku dla Vertex AI (najbezpieczniejszy sposób)
    temp_file = tempfile.NamedTemporaryFile(mode="w", delete=False)
    json.dump(service_account_info, temp_file)
    temp_file.close()

    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = temp_file.name

    try:
        # Inicjalizacja Klientów
        bigquery_client = bigquery.Client(credentials=credentials, project=GCP_PROJECT_ID)
        storage_client = storage.Client(credentials=credentials, project=GCP_PROJECT_ID)

        client_options = ClientOptions(api_endpoint=f"{GCP_SEARCH_LOCATION}-discoveryengine.googleapis.com")
        search_client = discoveryengine.SearchServiceClient(client_options=client_options, credentials=credentials)

        vertexai.init(project=GCP_PROJECT_ID, location=GCP_GEMINI_LOCATION)
        model = GenerativeModel(MODEL_NAME)

        # Opcjonalne usunięcie pliku po inicjalizacji
        os.remove(temp_file.name)

        return bigquery_client, storage_client, search_client, model

    except Exception as e:
        if os.path.exists(temp_file.name):
            os.remove(temp_file.name)
        raise Exception(f"Błąd inicjalizacji klienta GCP: {e}")


# --- GLOBALNE WYWOŁANIE INICJALIZACJI ---
try:
    bigquery_client, storage_client, search_client, model = setup_gcp_clients()
    st.session_state.gcp_clients_initialized = True
except Exception as e:
    st.session_state.gcp_clients_initialized = False
    st.session_state.gcp_init_error = str(e)


# --- FUNKCJE POMOCNICZE (LOGIKA) ---
# Wklej tutaj wszystkie funkcje logiczne (upload_to_gcs, analyze_cv_with_gemini, search_in_knowledge_base, chat_with_ai_agent_via_llm)
# Zwróć uwagę, że nie ma tu już funkcji 'set_background' ani żadnych 'st.title/st.header'

def upload_to_gcs(uploaded_file, bucket_name):
    if not storage_client: raise Exception("Storage client not initialized.")
    try:
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(uploaded_file.name)
        blob.upload_from_file(uploaded_file, rewind=True)
        return f"gs://{bucket_name}/{uploaded_file.name}"
    except GoogleAPIError as e:
        raise Exception(f"Błąd podczas przesyłania do GCS: {e}")


# ... (Wklej resztę funkcji logicznych, które korzystają z bigquery_client, model, search_client, itp.)
# [UWAGA: Zostawiam miejsce na resztę twojej logiki - nie wklejam jej dla zwięzłości, ale muszą tu być!]

# --- STUB dla braku logiki ---
def analyze_cv_with_gemini(cv_text):
    if not model: return {"summary": "Błąd: Model AI niedostępny.", "last_job": None, "last_company": None,
                          "candidate_name": None}
    # ... (Pełna logika analizy CV) ...
    return {"summary": "Analiza CV gotowa", "last_job": "Dev", "last_company": "X", "candidate_name": "Test"}


def search_in_knowledge_base(query: str, data_store_id: str) -> str:
    if not search_client: return ""
    # ... (Pełna logika RAG) ...
    return "Kontekst z bazy wiedzy"


def chat_with_ai_agent_via_llm(conversation_history_list, job_description):
    if not model: return "Przepraszam, model AI jest niedostępny.", True
    # ... (Pełna logika czatu z promptami) ...
    return "To jest odpowiedź bota.", False
# -----------------------------