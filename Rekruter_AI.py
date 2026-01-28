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

# --- KONFIGURACJA ---
BUCKET_NAME = "rekrutacja-pliki-2026"
GCP_PROJECT_ID = "ai-rekruter"
GCP_GEMINI_LOCATION = "europe-central2"
GCP_SEARCH_LOCATION = "global"
DATA_STORE_ID = "wiedza-rekruter_1768770519228"
BIGQUERY_DATASET_ID = "rekrutacja_hr"
BIGQUERY_TABLE_ID = "Kandydaci"
MODEL_NAME = "gemini-2.5-flash-lite"

# --- ZMIENNE GLOBALNE ---
bigquery_client = None
storage_client = None
search_client = None
model = None


# --- INICJALIZACJA GCP (METODA BEZPOŚREDNIA) ---
@st.cache_resource
def setup_gcp_clients():
    # Sprawdzenie czy secrets istnieją
    if 'gcp_service_account' not in st.secrets:
        raise Exception("Brak sekcji [gcp_service_account] w secrets.toml na Streamlit Cloud.")

    try:
        # 1. Pobranie klucza bezpośrednio z secrets
        # json.loads parsuje string do słownika
        key_info = json.loads(st.secrets["gcp_service_account"]["keyfile_json"])
        credentials = service_account.Credentials.from_service_account_info(key_info)

        # 2. Inicjalizacja klientów z jawnym przekazaniem credentials
        bq_client = bigquery.Client(credentials=credentials, project=GCP_PROJECT_ID)
        st_client = storage.Client(credentials=credentials, project=GCP_PROJECT_ID)

        if GCP_SEARCH_LOCATION == "global":
            api_endpoint = "discoveryengine.googleapis.com"
        else:
            api_endpoint = f"{GCP_SEARCH_LOCATION}-discoveryengine.googleapis.com"

        client_options = ClientOptions(api_endpoint=api_endpoint)
        sr_client = discoveryengine.SearchServiceClient(
            client_options=client_options,
            credentials=credentials
        )

        vertexai.init(
            project=GCP_PROJECT_ID,
            location=GCP_GEMINI_LOCATION,
            credentials=credentials
        )
        ai_model = GenerativeModel(MODEL_NAME)

        return bq_client, st_client, sr_client, ai_model

    except Exception as e:
        raise Exception(f"Błąd inicjalizacji GCP w Rekruter_AI: {str(e)}")


# Wywołanie inicjalizacji (Tylko raz!)
try:
    bigquery_client, storage_client, search_client, model = setup_gcp_clients()
    st.session_state.gcp_clients_initialized = True
except Exception as e:
    st.session_state.gcp_clients_initialized = False
    st.session_state.gcp_init_error = str(e)


# --- FUNKCJE LOGICZNE ---

def upload_to_gcs(uploaded_file, bucket_name):
    if not storage_client: raise Exception("Klient Storage nie jest zainicjowany.")
    try:
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(uploaded_file.name)
        blob.upload_from_file(uploaded_file, rewind=True)
        return f"gs://{bucket_name}/{uploaded_file.name}"
    except Exception as e:
        st.error(f"Błąd GCS: {e}")
        return None


def analyze_cv_with_gemini(cv_text):
    if not model: return {"summary": "Model niedostępny", "candidate_name": "Nieznany"}
    prompt = f"""
    Jesteś analitykiem HR. Przeanalizuj CV:
    1. Wyciągnij: Imię, Ostatnie Stanowisko, Nazwę Firmy.
    Format: Imię: [X], Stanowisko: [Y], Firma: [Z].
    2. Stwórz podsumowanie umiejętności i doświadczenia.
    CV: {cv_text}
    """
    try:
        response = model.generate_content(prompt)
        text = response.text
        name, job, company = None, None, None
        for line in text.split('\n'):
            if "imię:" in line.lower(): name = line.split(":", 1)[1].strip()
            if "stanowisko:" in line.lower(): job = line.split(":", 1)[1].strip()
            if "firma:" in line.lower(): company = line.split(":", 1)[1].strip()
        return {"summary": text, "candidate_name": name, "last_job": job, "last_company": company}
    except Exception as e:
        return {"summary": f"Błąd AI: {e}", "candidate_name": None}


def search_in_knowledge_base(query):
    if not search_client: return ""
    serving_config = f"projects/{GCP_PROJECT_ID}/locations/{GCP_SEARCH_LOCATION}/collections/default_collection/dataStores/{DATA_STORE_ID}/servingConfigs/default_config"
    req = discoveryengine.SearchRequest(
        serving_config=serving_config, query=query, page_size=3,
        content_search_spec=discoveryengine.SearchRequest.ContentSearchSpec(
            snippet_spec=discoveryengine.SearchRequest.ContentSearchSpec.SnippetSpec(return_snippet=True)
        )
    )
    try:
        resp = search_client.search(req)
        snippets = [r.document.derived_struct_data["snippets"][0]["snippet"] for r in resp.results if
                    "snippets" in r.document.derived_struct_data]
        return "\n---\n".join(snippets)
    except Exception:
        return ""


def chat_with_ai(history, job_desc):
    if not model: return "Błąd modelu.", True
    user_msg = history[-1]["content"]

    rag_context = search_in_knowledge_base(user_msg)
    if job_desc:
        rag_context += "\n" + search_in_knowledge_base(job_desc[:50])

    prompt = f"""
    Jesteś rekruterem IT (Fabian). 
    Twoje zasady:
    1. Odpowiadaj na pytania kandydata używając: {rag_context}
    2. Jeśli nie ma pytań, prowadź wywiad rekrutacyjny dot. stanowiska: {job_desc}
    3. Na koniec podziękuj i dodaj [KONIEC ROZMOWY].

    Historia:
    {history}
    """
    try:
        resp = model.generate_content(prompt)
        end = "[KONIEC ROZMOWY]" in resp.text or any(x in user_msg.lower() for x in ["dziękuję", "koniec"])
        return resp.text.replace("[KONIEC ROZMOWY]", ""), end
    except Exception as e:
        return f"Błąd: {e}", True


def run_candidate_interface():
    st.header("🤖 Witaj w Wirtualnej Rekrutacji AI")

    if "cv_uploaded_id" not in st.session_state:
        st.session_state.cv_uploaded_id = None
        st.session_state.messages = []

    if not st.session_state.cv_uploaded_id:
        uploaded = st.file_uploader("Prześlij CV (PDF)", type="pdf")
        if uploaded:
            with st.spinner("Analiza..."):
                text = ""
                try:
                    pdf = PdfReader(uploaded)
                    for p in pdf.pages: text += p.extract_text()
                except:
                    st.error("Błąd PDF"); st.stop()

                url = upload_to_gcs(uploaded, BUCKET_NAME)
                analysis = analyze_cv_with_gemini(text)
                cid = str(uuid.uuid4())

                row = {
                    "id_kandydata": cid, "nazwa_pliku_cv": uploaded.name, "url_cv_gcs": url,
                    "data_aplikacji": datetime.now().isoformat(), "tresc_cv": text,
                    "umiejetnosci_tech": analysis["summary"], "status_rekrutacji": "CV przesłane",
                    "event_type": "cv_uploaded"
                }

                if bigquery_client:
                    errors = bigquery_client.dataset(BIGQUERY_DATASET_ID).table(BIGQUERY_TABLE_ID).insert_rows_json(
                        [row])
                    if not errors:
                        st.session_state.cv_uploaded_id = cid
                        msg = f"Cześć {analysis.get('candidate_name', 'Kandydacie')}! Opowiedz o swoim doświadczeniu."
                        st.session_state.messages = [{"role": "assistant", "content": msg}]
                        st.rerun()
                    else:
                        st.error(f"Błąd zapisu do BigQuery: {errors}")
                else:
                    st.error("Klient BigQuery nie został zainicjowany.")

    if st.session_state.cv_uploaded_id:
        for m in st.session_state.messages:
            with st.chat_message(m["role"]): st.markdown(m["content"])

        if user_in := st.chat_input("Twoja odpowiedź..."):
            st.session_state.messages.append({"role": "user", "content": user_in})
            with st.chat_message("user"):
                st.markdown(user_in)

            with st.chat_message("assistant"):
                with st.spinner("Thinking..."):
                    reply, ended = chat_with_ai(st.session_state.messages,
                                                st.session_state.get("active_job_description"))
                    st.markdown(reply)
                    st.session_state.messages.append({"role": "assistant", "content": reply})

                    if ended:
                        st.success("Dziękujemy!")
                        full_txt = str(st.session_state.messages)
                        row = {
                            "id_kandydata": st.session_state.cv_uploaded_id,
                            "data_aplikacji": datetime.now().isoformat(),
                            "transkrypcja_rozmowy_ai": full_txt,
                            "status_rekrutacji": "Koniec rozmowy",
                            "event_type": "transcript_saved"
                        }
                        if bigquery_client:
                            bigquery_client.dataset(BIGQUERY_DATASET_ID).table(BIGQUERY_TABLE_ID).insert_rows_json(
                                [row])