import streamlit as st
from google.cloud import bigquery
from google.api_core.exceptions import GoogleAPIError

# --- KLUCZOWA ZMIANA: IMPORT KLIENTÓW Z MODUŁU REKRUTER_AI ---
# Musimy zaimportować klientów i stan inicjalizacji z głównego modułu
try:
    from Rekruter_AI import bigquery_client, model, st_client, search_client, bigquery_client, st, GCP_PROJECT_ID, \
        BIGQUERY_DATASET_ID, BIGQUERY_TABLE_ID
except ImportError as e:
    st.error(
        f"Krytyczny błąd importu z Rekruter_AI: {e}. Upewnij się, że plik Rekruter_AI.py istnieje i nie zawiera błędów składni.")
    st.stop()

# --- ZMIENNE STANU SESJI ---
# Używamy zmiennej stanu z głównego pliku
if "active_job_description" not in st.session_state:
    st.session_state.active_job_description = ""


# --- FUNKCJE POMOCNICZE PANELU HR ---
def evaluate_candidate_with_gemini(candidate_id: str, job_description: str):
    # Sprawdzenie dostępności (klientów zainicjowanych w Rekruter_AI)
    if not bigquery_client or not model:
        st.error("Błąd: Usługi GCP nie są dostępne. Sprawdź logs w Rekruter_AI.py.")
        return

    st.info(f"Rozpoczynam zaawansowaną ocenę kandydata {candidate_id}...")
    try:
        # --- BigQuery Query ---
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

        # --- GEMINI PROMPT (Nowy format) ---
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

        with st.spinner("AI generuje zaawansowany raport dopasowania..."):
            # Używamy modelu zaimportowanego z Rekruter_AI
            response = model.generate_content(
                evaluation_prompt,
                generation_config={"max_output_tokens": 3000, "temperature": 0.3}
            )
            st.success("Raport dopasowania został wygenerowany!")
            st.markdown("### Wynik Dopasowania Kandydata do Ogłoszenia")
            st.markdown(response.text)
    except Exception as e:
        st.error(f"Wystąpił błąd podczas generowania raportu: {e}")


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


# --- INTERFEJS PANELU REKRUTERA ---
def run_hr_dashboard_interface():
    """Rysuje interfejs HR Dashboard wewnątrz zakładki w app.py."""

    # Sprawdzamy stan inicjalizacji z głównego pliku
    if not st.session_state.gcp_clients_initialized:
        st.warning("Oczekiwanie na zainicjalizowanie usług GCP...")
        return

    st.header("Aktywne Ogłoszenie o Pracę")
    st.markdown(
        "Wklej tutaj ogłoszenie, na które prowadzona będzie rekrutacja. Wszyscy nowi kandydaci będą rozmawiali w kontekście tego ogłoszenia.")

    active_job_desc_input = st.text_area(
        "Treść ogłoszenia:",
        value=st.session_state.get("active_job_description", ""),
        height=250
    )

    if st.button("Ustaw jako Aktywne Ogłoszenie dla Kandydatów"):
        st.session_state.active_job_description = active_job_desc_input
        st.success("Ogłoszenie zostało zapisane i będzie używane podczas rozmów z nowymi kandydatami.")

    st.divider()

    st.header("Lista Kandydatów")
    if st.button("Odśwież listę"):
        st.cache_data.clear()
        st.rerun()

    candidates_data = get_candidates_from_bigquery()

    if candidates_data:
        st.dataframe(candidates_data, use_container_width=True)

        st.header("Wygeneruj Raport Dopasowania (po rozmowie)")

        selected_candidate_id_report = st.selectbox(
            "Wybierz ID kandydata do wygenerowania raportu:",
            [""] + [c["id_kandydata"] for c in candidates_data]
        )

        if st.button("Generuj Raport"):
            active_job_description = st.session_state.get("active_job_description", "")
            if selected_candidate_id_report and active_job_description:
                evaluate_candidate_with_gemini(selected_candidate_id_report, active_job_description)
            else:
                st.warning(
                    "Proszę wybrać kandydata i upewnić się, że aktywne ogłoszenie o pracę jest ustawione powyżej.")
    else:
        st.info("Brak kandydatów w bazie danych. Poczekaj, aż kandydaci załadują swoje CV na stronie głównej.")