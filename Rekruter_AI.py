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

# --- ZMIENNE GLOBALNE (Zostaną ustawione przez cache_resource) ---
bigquery_client = None
storage_client = None
search_client = None
model = None


# --- Inicjalizacja usług GCP (Jednorazowa, WYSŁUGA CLOUD) ---
@st.cache_resource
def setup_gcp_clients():
    """Inicjalizuje wszystkich klientów GCP raz i bezpiecznie pobiera poświadczenia z secrets."""

    if 'gcp_service_account' not in st.secrets:
        # Ten błąd jest przechwytywany w app.py, ale dla pewności go zwracamy
        raise Exception("Brak sekcji 'gcp_service_account' w secrets.toml.")

    # 1. Przygotowanie Poświadczeń
    service_account_info = json.loads(st.secrets["gcp_service_account"]["keyfile_json"])
    credentials = service_account.Credentials.from_service_account_info(service_account_info)

    # 2. Tworzenie Klientów
    try:
        # Klient BigQuery
        bq_client = bigquery.Client(credentials=credentials, project=GCP_PROJECT_ID)

        # Klient Storage
        st_client = storage.Client(credentials=credentials, project=GCP_PROJECT_ID)

        # Klient Discovery Engine (Search/RAG)
        client_options = ClientOptions(api_endpoint=f"{GCP_SEARCH_LOCATION}-discoveryengine.googleapis.com")
        sr_client = discoveryengine.SearchServiceClient(client_options=client_options, credentials=credentials)

        # Klient Vertex AI (Gemini)
        # UWAGA: Vertex AI używa GOOGLE_APPLICATION_CREDENTIALS. Tworzymy tymczasowy plik.
        temp_gcp_key_path = "temp_gcp_credentials.json"
        with open(temp_gcp_key_path, "w") as f:
            json.dump(service_account_info, f)
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = temp_gcp_key_path

        vertexai.init(project=GCP_PROJECT_ID, location=GCP_GEMINI_LOCATION)
        ai_model = GenerativeModel(MODEL_NAME)

        # Usuwamy tymczasowy plik (najlepiej po zakończeniu sesji, ale dla uproszczenia zostawiamy)
        # os.remove(temp_gcp_key_path)

        return bq_client, st_client, sr_client, ai_model

    except Exception as e:
        raise Exception(f"Błąd inicjalizacji klienta GCP: {e}")


# Uruchomienie inicjalizacji i ustawienie zmiennych globalnych modułu
try:
    bigquery_client, storage_client, search_client, model = setup_gcp_clients()
    st.session_state.gcp_clients_initialized = True
except Exception as e:
    st.session_state.gcp_clients_initialized = False
    print(f"KRYTYCZNY BŁĄD GLOBALNY (Rekruter_AI): {e}")

# --- ZMIENNE STANU SESJI ---
if "messages" not in st.session_state:
    st.session_state.messages = []
if "cv_uploaded_id" not in st.session_state:
    st.session_state.cv_uploaded_id = None
if "active_job_description" not in st.session_state:
    st.session_state.active_job_description = ""


# --- FUNKCJE POMOCNICZE (LOGIKA) ---

def upload_to_gcs(uploaded_file, bucket_name):
    if not storage_client: raise Exception("Storage client not initialized.")
    try:
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(uploaded_file.name)
        blob.upload_from_file(uploaded_file, rewind=True)
        return f"gs://{bucket_name}/{uploaded_file.name}"
    except GoogleAPIError as e:
        raise Exception(f"Błąd podczas przesyłania do GCS: {e}")


# (Wstaw resztę funkcji - analyze_cv_with_gemini, search_in_knowledge_base, chat_with_ai_agent_via_llm - są one merytorycznie poprawne,
# ale muszą używać globalnych zmiennych bigquery_client, model, search_client)
def analyze_cv_with_gemini(cv_text):
    if not cv_text or not model:
        return {"summary": "Błąd: Brak tekstu do analizy lub model AI niezaładowany.", "last_job": None,
                "last_company": None, "candidate_name": None}
    prompt = f"""
    Jesteś analitykiem HR. Przeanalizuj poniższe CV i wykonaj dwa zadania:
    1.  **Wyciągnij Informacje:** Zidentyfikuj imię kandydata, ostatnie (najnowsze) stanowisko i nazwę firmy. Zwróć je w formacie:
        Imię: [Imię Kandydata]
        Stanowisko: [Nazwa Stanowiska]
        Firma: [Nazwa Firmy]
    2.  **Wygeneruj Podsumowanie:** Stwórz podsumowanie CV w sekcjach: Kluczowe Umiejętności Techniczne, Doświadczenie Zawodowe, Wykształcenie.
    CV: {cv_text}
    """
    try:
        response = model.generate_content(prompt, generation_config={"max_output_tokens": 1024})
        summary = response.text
        last_job, last_company, candidate_name = None, None, None
        for line in response.text.split('\n'):
            if line.lower().startswith("imię:"):
                candidate_name = line.split(":", 1)[1].strip()
            if line.lower().startswith("stanowisko:"):
                last_job = line.split(":", 1)[1].strip()
            if line.lower().startswith("firma:"):
                last_company = line.split(":", 1)[1].strip()
        return {"summary": summary, "last_job": last_job, "last_company": last_company,
                "candidate_name": candidate_name}
    except Exception as e:
        return {"summary": f"Błąd analizy AI: {e}", "last_job": None, "last_company": None, "candidate_name": None}


def search_in_knowledge_base(query: str, data_store_id: str) -> str:
    if not search_client: return ""
    serving_config = f"projects/{GCP_PROJECT_ID}/locations/{GCP_SEARCH_LOCATION}/collections/default_collection/dataStores/{data_store_id}/servingConfigs/default_config"
    content_search_spec = discoveryengine.SearchRequest.ContentSearchSpec.SnippetSpec(return_snippet=True)
    request = discoveryengine.SearchRequest(serving_config=serving_config, query=query, page_size=3,
                                            content_search_spec=discoveryengine.SearchRequest.ContentSearchSpec(
                                                snippet_spec=content_search_spec))
    try:
        response = search_client.search(request)
        context_snippets = [result.document.derived_struct_data["snippets"][0]["snippet"] for result in response.results
                            if
                            "snippets" in result.document.derived_struct_data and result.document.derived_struct_data[
                                "snippets"]]
        if not context_snippets: return ""
        return "\n---\n".join(context_snippets)
    except Exception as e:
        # st.warning(f"Błąd wyszukiwania w bazie wiedzy: {e}")
        return ""


def chat_with_ai_agent_via_llm(conversation_history_list, job_description):
    if not model: return "Przepraszam, model AI jest niedostępny.", True
    user_query = conversation_history_list[-1]["content"]
    context_from_query = search_in_knowledge_base(user_query, DATA_STORE_ID)

    job_context_info = ""
    if job_description:
        job_context_info = search_in_knowledge_base(job_description[:50], DATA_STORE_ID)

    combined_knowledge_context = ""
    if job_context_info: combined_knowledge_context += f"Ogólne informacje o stanowisku:\n{job_context_info}\n\n"
    if context_from_query: combined_knowledge_context += f"Informacje związane z pytaniem kandydata:\n{context_from_query}"

    job_context_prompt = f"Prowadzisz rozmowę na stanowisko opisane w tym ogłoszeniu:\n---OGŁOSZENIE---\n{job_description}\n----------------" if job_description else ""

    base_instructions = f"""
    Jesteś profesjonalnym, ale i pomocnym rekruterem IT. {job_context_prompt}

    Twoje zadanie ma dwa priorytety:
    1.  **REAGUJ NA KANDYDATA:** Jeśli ostatnia wiadomość kandydata jest pytaniem (np. zaczyna się od "czym jest", "jakie są", "czy mogę"), w pierwszej kolejności odpowiedz na nie, korzystając z informacji w sekcji "POŁĄCZONY KONTEKST Z BAZY WIEDZY". Jeśli nie znajdziesz tam odpowiedzi, poinformuj o tym.
    2.  **PROWADŹ ROZMOWĘ:** Po udzieleniu odpowiedzi na pytanie kandydata, LUB jeśli jego ostatnia wiadomość nie była pytaniem, kontynuuj swoje główne zadanie - prowadzenie rozmowy kwalifikacyjnej. Zadaj kolejne, trafne pytanie rekrutacyjne, aby dowiedzieć się więcej o jego doświadczeniu.

    **POŁĄCZONY KONTEKST Z BAZY WIEDZY:**
    {combined_knowledge_context if combined_knowledge_context else "Brak dodatkowych informacji w bazie wiedzy."}

    Na końcu całej rozmowy (gdy zbierzesz wystarczająco informacji lub kandydat chce zakończyć), podziękuj i dodaj frazę [KONIEC ROZMOWY]. Używaj języka polskiego.
    **Historia rozmowy:**
    """

    formatted_history = "\n".join([f"{msg['role']}: {msg['content']}" for msg in conversation_history_list])
    full_prompt = f"{base_instructions}\n{formatted_history}\nassistant: "
    try:
        response = model.generate_content(full_prompt, generation_config={"max_output_tokens": 500, "temperature": 0.3})
        is_user_ending = any(phrase in user_query.lower() for phrase in ["dziękuję", "do widzenia", "koniec"])
        is_conversation_end = "[KONIEC ROZMOWY]" in response.text.upper() or is_user_ending
        return response.text.replace("[KONIEC ROZMOWY]", "").strip(), is_conversation_end
    except Exception as e:
        # st.error(f"Błąd podczas rozmowy z AI: {e}")
        return "Przepraszam, wystąpił problem.", True


def run_candidate_interface():
    """Rysuje interfejs kandydata wewnątrz zakładki w app.py."""

    if not st.session_state.gcp_clients_initialized:
        st.error("Usługi GCP nie zostały poprawnie zainicjalizowane. Sprawdź plik secrets.toml.")
        return

    st.markdown(
        "Prześlij swoje CV, aby rozpocząć. Nasz inteligentny asystent przeanalizuje je i rozpocznie z Tobą spersonalizowaną rozmowę.")

    if not st.session_state.cv_uploaded_id:
        uploaded_file = st.file_uploader("Załaduj swoje CV (tylko .pdf)", type=["pdf"])

        if uploaded_file:
            with st.spinner("Przetwarzanie CV..."):
                cv_text = ""
                try:
                    reader = PdfReader(uploaded_file)
                    for page in reader.pages:
                        cv_text += page.extract_text() or ""
                except Exception as e:
                    st.error(f"Błąd odczytu pliku PDF: {e}")
                    return

                try:
                    gcs_url = upload_to_gcs(uploaded_file, BUCKET_NAME)
                except Exception as e:
                    st.error(f"Nie udało się przesłać CV do GCS: {e}")
                    return

                analysis_result = analyze_cv_with_gemini(cv_text)
                analysis_summary = analysis_result.get("summary", "Błąd analizy.")
                candidate_id = str(uuid.uuid4())

                row_to_insert = {"id_kandydata": candidate_id, "nazwa_pliku_cv": uploaded_file.name,
                                 "url_cv_gcs": gcs_url,
                                 "data_aplikacji": datetime.now().isoformat(), "tresc_cv": cv_text,
                                 "umiejetnosci_tech": analysis_summary, "status_rekrutacji": "CV przesłane",
                                 "event_type": "cv_uploaded"}

                table_ref = bigquery_client.dataset(BIGQUERY_DATASET_ID).table(BIGQUERY_TABLE_ID)
                errors = bigquery_client.insert_rows_json(table_ref, [row_to_insert])

                if not errors:
                    st.session_state.cv_uploaded_id = candidate_id

                    candidate_name = analysis_result.get("candidate_name")
                    last_job = analysis_result.get("last_job")
                    last_company = analysis_result.get("last_company")

                    if candidate_name and last_job and last_company:
                        welcome_message = f"Witaj, {candidate_name}! Dziękuję za przesłanie CV. Widzę, że Twoje ostatnie stanowisko to {last_job} w firmie {last_company}. Opowiedz mi proszę więcej o swoich obowiązkach."
                    elif candidate_name:
                        welcome_message = f"Witaj, {candidate_name}! Dziękuję za CV. Opowiedz mi proszę o swoim ostatnim doświadczeniu zawodowym."
                    else:
                        welcome_message = "Dziękuję za przesłanie CV. Opowiedz mi proszę o swoim ostatnim doświadczeniu zawodowym."

                    st.session_state.messages = [{"role": "assistant", "content": welcome_message}]
                    st.success("Twoje CV zostało przetworzone! Rozpoczynamy rozmowę.")
                    st.rerun()
                else:
                    st.error(f"Błąd zapisu danych do BigQuery: {errors}")

    if st.session_state.cv_uploaded_id:
        job_desc = st.session_state.get("active_job_description", "")
        if job_desc:
            with st.expander("Zobacz opis stanowiska, na które aplikujesz"):
                st.markdown(job_desc)

        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

        if user_input := st.chat_input("Twoja odpowiedź..."):
            st.session_state.messages.append({"role": "user", "content": user_input})
            with st.chat_message("user"):
                st.markdown(user_input)

            with st.chat_message("assistant"):
                with st.spinner("AI myśli..."):
                    response_text, conversation_ended = chat_with_ai_agent_via_llm(st.session_state.messages, job_desc)
                    st.markdown(response_text)
                    st.session_state.messages.append({"role": "assistant", "content": response_text})

                if conversation_ended:
                    st.success("Dziękujemy za rozmowę! Twój profil zostanie teraz przekazany do rekrutera.")
                    with st.spinner("Zapisywanie transkrypcji..."):
                        candidate_id_to_save = st.session_state.cv_uploaded_id
                        full_transcript = "\n".join(
                            [f"{msg['role']}: {msg['content']}" for msg in st.session_state.messages])
                        row_to_insert = {
                            "id_kandydata": candidate_id_to_save,
                            "data_aplikacji": datetime.now().isoformat(),
                            "transkrypcja_rozmowy_ai": full_transcript,
                            "status_rekrutacji": "Rozmowa AI zakończona",
                            "event_type": "transcript_saved"
                        }
                        table_ref = bigquery_client.dataset(BIGQUERY_DATASET_ID).table(BIGQUERY_TABLE_ID)
                        errors = bigquery_client.insert_rows_json(table_ref, [row_to_insert])
                        if errors:
                            st.error(f"Nie udało się zapisać transkrypcji: {errors}")
                        else:
                            st.info("Transkrypcja rozmowy została zapisana.")