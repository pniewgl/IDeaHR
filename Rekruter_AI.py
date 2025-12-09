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
import tempfile  # Używamy modułu do bezpiecznego tworzenia plików tymczasowych

# --- KONFIGURACJA STAŁYCH ---
BUCKET_NAME = "demo-cv-rekrutacja-hrdreamer2"
GCP_PROJECT_ID = "ai-recruiter-prod"
GCP_GEMINI_LOCATION = "europe-central2"
GCP_SEARCH_LOCATION = "eu"
DATA_STORE_ID = "ai-rekruter-wiedza_1759606950652"
BIGQUERY_DATASET_ID = "rekrutacja_hr"
BIGQUERY_TABLE_ID = "Kandydaci"
MODEL_NAME = "gemini-2.5-flash-lite"

# --- ZMIENNE GLOBALNE (Zostaną ustawione po inicjalizacji) ---
bigquery_client = None
storage_client = None
search_client = None
model = None


# --- Inicjalizacja usług GCP (Wymuszenie nowego cache'u: v3) ---
@st.cache_resource
def setup_gcp_clients_v3():
    """Inicjalizuje wszystkich klientów GCP raz i bezpiecznie pobiera poświadczenia z secrets.toml."""

    if 'gcp_service_account' not in st.secrets:
        raise Exception("Brak sekcji 'gcp_service_account' w secrets.toml.")

    # 1. Przygotowanie Poświadczeń
    service_account_info = json.loads(st.secrets["gcp_service_account"]["keyfile_json"])
    credentials = service_account.Credentials.from_service_account_info(service_account_info)

    # 2. Utworzenie tymczasowego pliku dla Vertex AI (najbardziej niezawodna metoda)
    # Tworzymy plik tymczasowy, aby Vertex AI mógł go bezpiecznie użyć i odczytać jako env
    # Zapisujemy JSON do pliku tymczasowego
    with tempfile.NamedTemporaryFile(mode="w", delete=False) as temp_file:
        json.dump(service_account_info, temp_file)

    temp_file_path = temp_file.name
    # Ustawiamy zmienną środowiskową na ścieżkę do pliku tymczasowego
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = temp_file_path

    try:
        # Klient BigQuery
        bq_client = bigquery.Client(credentials=credentials, project=GCP_PROJECT_ID)

        # Klient Storage
        st_client = storage.Client(credentials=credentials, project=GCP_PROJECT_ID)

        # Klient Discovery Engine (Search/RAG)
        client_options = ClientOptions(api_endpoint=f"{GCP_SEARCH_LOCATION}-discoveryengine.googleapis.com")
        sr_client = discoveryengine.SearchServiceClient(client_options=client_options, credentials=credentials)

        # Klient Vertex AI (Gemini)
        vertexai.init(project=GCP_PROJECT_ID, location=GCP_GEMINI_LOCATION)
        ai_model = GenerativeModel(MODEL_NAME)

        # Klucze zostały pomyślnie załadowane i użyte
        return bq_client, st_client, sr_client, ai_model

    except Exception as e:
        # Jeśli wystąpi błąd, usuwamy plik tymczasowy i rzucamy wyjątek
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
        raise Exception(f"Błąd inicjalizacji klienta GCP: {e}")

    finally:
        # Usuwamy plik tymczasowy po udanej inicjalizacji
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)


# --- GLOBALNE WYWOŁANIE INICJALIZACJI ---
try:
    bigquery_client, storage_client, search_client, model = setup_gcp_clients_v3()
    st.session_state.gcp_clients_initialized = True
except Exception as e:
    # Zapisujemy błąd w sesji, aby mógł go wyświetlić interfejs
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

def upload_to_gcs(uploaded_file, bucket_name):
    if not storage_client: raise Exception("Storage client not initialized.")
    try:
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(uploaded_file.name)
        blob.upload_from_file(uploaded_file, rewind=True)
        return f"gs://{bucket_name}/{uploaded_file.name}"
    except GoogleAPIError as e:
        raise Exception(f"Błąd podczas przesyłania do GCS: {e}")


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
        return "Przepraszam, wystąpił problem.", True


# --- HR DASHBOARD LOGICZNY (FUNKCJE, KTÓRYCH UŻYWA HR) ---

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
        st.error(f"Błąd podczas pobierania danych z BigQuery: {e}")
        return []


def evaluate_candidate_with_gemini_hr(candidate_id: str, job_description: str):
    """Generuje raport dopasowania z AI (funkcja używana przez UI HR)."""
    if not bigquery_client or not model:
        st.error("Błąd: Usługi GCP nie są dostępne.")
        return

    st.info(f"Rozpoczynam zaawansowaną ocenę kandydata {candidate_id}...")
    try:
        query = f"""
        SELECT 
            t1.umiejetnosci_tech AS cv_analysis,
            t2.transkrypcja_rozmowy_ai AS conversation_transcript
        FROM `{GCP_PROJECT_ID}.{BIGQUERY_DATASET_ID}.{BIGQUERY_TABLE_ID}` AS t1
        LEFT JOIN (
            SELECT id_kandydata, transkrypcja_rozmowy_ai
            FROM `{GCP_PROJECT_ID}.{BIGQUERY_DATASET_ID}.{BIGQUERY_TABLE_ID}`
            WHERE id_kandydata = '{candidate_id}' AND event_type = 'transcript_saved'
            ORDER BY data_aplikacji DESC LIMIT 1
        ) AS t2 ON t1.id_kandydata = t2.id_kandydata
        WHERE t1.id_kandydata = '{candidate_id}' AND t1.event_type = 'cv_uploaded'
        """
        query_job = bigquery_client.query(query)
        candidate_data = next(query_job.result(), None)

        if not candidate_data:
            st.error("Nie znaleziono danych kandydata do oceny.")
            return

        cv_analysis = candidate_data.cv_analysis or "Brak analizy CV."
        conversation_transcript = candidate_data.conversation_transcript or "Brak transkrypcji rozmowy."

        # Używamy pełnego promptu z sekcją 1b. Historia Zatrudnienia
        evaluation_prompt = f"""
        Jesteś wysoce analitycznym rekruterem IT. Twoim zadaniem jest stworzenie szczegółowego raportu dopasowania kandydata do oferty pracy na podstawie trzech źródeł: analizy CV, transkrypcji rozmowy oraz treści ogłoszenia.
        Raport musi składać się z trzech odrębnych sekcji:

        **1. Ocena Dopasowania CV do Oferty:**
        - **Analiza Słów Kluczowych:** Porównaj umiejętności i technologie z CV z wymaganiami w ogłoszeniu. Wymień dopasowania i braki.
        - **Ocena Doświadczenia:** Oceń, czy długość i rodzaj doświadczenia zawodowego kandydata odpowiada wymaganiom stanowiska.
        - **Wstępny Wniosek (na podstawie CV):** Krótka ocena, czy na podstawie samego CV kandydat jest obiecujący.

        **1b. Historia Zatrudnienia:**
        - **Lista i Okresy:** Na podstawie sekcji doświadczenia w CV, stwórz listę firm, w których kandydat pracował. Dla każdej firmy podaj okres zatrudnienia i oblicz łączny czas pracy w tej firmie w latach i miesiącach (jeśli jest możliwe). **Wymagany format dla każdej pozycji to: [Nazwa Firmy] (MM.RRRR – MM.RRRR) – [Łączny Czas np. 2 lata, 3 miesiące].**

        **2. Ocena Rozmowy Kwalifikacyjnej:**
        - **Weryfikacja Umiejętności:** Oceń, czy podczas rozmowy kandydat potwierdził umiejętności z CV. Zwróć uwagę na spójność.
        - **Kompetencje Miękkie:** Na podstawie rozmowy oceń komunikatywność, motywację i sposób myślenia kandydata.
        - **Wnioski z Rozmowy:** Co nowego dowiedzieliśmy się o kandydacie podczas rozmowy? Czy pojawiły się jakieś czerwone flagi?

        **3. Podsumowanie i Ostateczna Ocena Dopasowania:**
        - **Połączona Analiza (CV + Rozmowa):** Stwórz całościowy obraz kandydata, łącząc wnioski z obu powyższych sekcji.
        - **Stopień Dopasowania do Ogłoszenia (w %):** Oszacuj w procentach, na ile kandydat pasuje do oferty, i krótko uzasadnij.
        - **Rekomendacja:** Jednoznaczna rekomendacja (Rekomenduję / Nie rekomenduję / Rekomenduję z zastrzeżeniami) wraz z finalnym uzasadnieniem.
        ---
        **DANE DO ANALIZY**
        **OGŁOSZENIE O PRACĘ:** {job_description}
        **ANALIZA CV KANDDATA:** {cv_analysis}
        **TRANSKRYPCJA ROZMOWY Z KANDDATEM:** {conversation_transcript}
        ---
        """

        response = model.generate_content(
            evaluation_prompt,
            generation_config={"max_output_tokens": 3000, "temperature": 0.3}
        )
        st.success("Raport dopasowania został wygenerowany!")
        st.markdown("### Wynik Dopasowania Kandydata do Ogłoszenia")
        st.markdown(response.text)
    except Exception as e:
        st.error(f"Wystąpił błąd podczas generowania raportu: {e}")


# --- INTERFEJSY ---

def run_hr_dashboard_interface():
    """Rysuje interfejs HR Dashboard w bocznym pasku."""

    st.sidebar.title("📋 HR Dashboard")

    # Sprawdzamy, czy w ogóle się uruchomiliśmy
    if not st.session_state.get("gcp_clients_initialized"):
        st.sidebar.warning("Usługi GCP w trakcie ładowania...")
        return

    st.sidebar.header("Aktywne Ogłoszenie o Pracę")
    st.sidebar.markdown("Wklej ogłoszenie, na które prowadzona będzie rekrutacja.")

    active_job_desc_input = st.sidebar.text_area(
        "Treść ogłoszenia:",
        value=st.session_state.get("active_job_description", ""),
        height=250
    )

    if st.sidebar.button("Ustaw jako Aktywne Ogłoszenie"):
        st.session_state.active_job_description = active_job_desc_input
        st.sidebar.success("Ogłoszenie zostało zapisane.")

    st.sidebar.divider()

    st.sidebar.header("Lista Kandydatów")
    if st.sidebar.button("Odśwież listę"):
        st.cache_data.clear()
        st.rerun()

    candidates_data = get_candidates_from_bigquery()

    if candidates_data:
        # Zapewnienie, że interfejs HR działa w bocznym pasku
        st.sidebar.dataframe(candidates_data, use_container_width=True)

        st.sidebar.header("Wygeneruj Raport Dopasowania")

        selected_candidate_id_report = st.sidebar.selectbox(
            "Wybierz ID kandydata do raportu:",
            [""] + [c["id_kandydata"] for c in candidates_data]
        )

        # Używamy głównego okna do wyświetlenia raportu, aby nie był zbyt mały
        if st.sidebar.button("Generuj Raport"):
            active_job_description = st.session_state.get("active_job_description", "")
            if selected_candidate_id_report and active_job_description:
                # Wywołanie funkcji w głównym oknie
                with st.container():
                    evaluate_candidate_with_gemini_hr(selected_candidate_id_report, active_job_description)
            else:
                st.sidebar.warning("Proszę wybrać kandydata i ustawić ogłoszenie.")
    else:
        st.sidebar.info("Brak kandydatów w bazie danych.")


def run_candidate_interface():
    """Rysuje interfejs kandydata w głównym oknie."""

    if not st.session_state.gcp_clients_initialized:
        st.error(f"Usługi GCP nie zostały poprawnie zainicjalizowane. Błąd: {st.session_state.gcp_init_error}")
        return

    st.header("🤖 Fabian: Wirtualna Rekrutacja AI")
    st.markdown(
        "Prześlij swoje CV, aby rozpocząć. Nasz inteligentny asystent przeanalizuje je i rozpocznie z Tobą spersonalizowaną rozmowę.")

    # ... (Wklej tutaj całą logikę UI Kandydata z Rekruter_AI.py: st.markdown, st.file_uploader, st.chat_input) ...
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


# --- WYWOŁANIE GŁÓWNE ---
if st.session_state.gcp_clients_initialized:
    st.set_page_config(page_title="Fabian: AI Recruiter", layout="wide", initial_sidebar_state="expanded")
    run_hr_dashboard_interface()  # Rysuje panel w bocznym pasku
    run_candidate_interface()  # Rysuje interfejs kandydata w głównym oknie
else:
    # Wyświetl błąd krytyczny, jeśli inicjalizacja się nie powiodła
    st.set_page_config(page_title="Błąd Krytyczny", layout="centered")
    st.error("❌ APLIKACJA NIEDOSTĘPNA")
    st.markdown(f"**Nie udało się nawiązać połączenia z usługami Google Cloud Platform.**")
    st.markdown("Sprawdź poniższe szczegóły błędu w logach Streamlit Cloud:")
    st.code(st.session_state.get('gcp_init_error', 'Brak szczegółowego błędu. Sprawdź logi.'), language="text")
    st.markdown("---")
    st.markdown(
        "⚠️ **Potencjalne rozwiązanie:** Upewnij się, że klucz `keyfile_json` w pliku `secrets.toml` jest poprawny (invalid_grant: Invalid grant).")