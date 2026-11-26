

|Data i autor|Narzędzia i model|Zadanie|Co otrzymano|Co było błędne|Weryfikacja|
|-|-|-|-|-|-|
|2026-11-10, Jan Jarzębiński|OpenAI Codex|Stworznie struktury projektu|Struktura projektu scraper/, ustawienia UserAgent, logowanie, instrukcja uruchomienia|W User-Agent nie było kontaktu do zespołu|testy, odpalenie ręczne i prześledzenie logów, review drugiego członka zespołu|

|2026-11-10, Jan Jarzębiński|OpenAI Codex|Dodanie schematu danych do scrapera|Schemat danych dla źródła, kategorii, podkategorii i przykładowy produkt.|Przykładowy produkt zawierał błędny url|Ręcznie sprawdzono pola json i porównano z wymaganiami, review|

|2026-11-12, Jan Jarzębiński|OpenAI Codex|Dodanie pipeline|Workflow CI uruchamiany dla pull requestów, testy ustawień scrapera|Błąd niepotrzebnego importu Path|Ręczne uruchomienie i analiza logów, wykonanie testów scraper/tests, review|

|2026-11-14, Jan Jarzębiński|OpenAI Codex|Fetchowanie strony|pobieranie stron, uwzględnienie robots.txt, logi błędów, obsługa przekierowań, limiter żądań|Konieczność poprawnienia importów i usunięcia kilku zbędnych|Ręczne uruchomienie, anliza logów, testy Ruff, review|

|2026-11-15, Jan Jarzębiński|OpenAI Codex|Dodanie parsera kategorii|Parser HTML, wykrywa kategorie i podkategorie wraz z nazwami, URL i relacją parent-child. Zapisuje wynik do pliku JSON.|Pierwsza wersja szukała ul.top-menu, którego nie było w HTML. (błędny selektor)|Testy jednostkowe, ręczne odpalenie i prześledzenie logów, review|

|2026-11-15, Jan Paluch|OpenAI Codex|Wielowątkowy odczyt danych produktów|Parser nazw, opisów, cen, VAT, cech, wagi, wariantów i URL-i zdjęć|Czas pobierania, dodano wątki|33 testy, ręczne odpalenie, test regresji, review|

|2026-11-21, Jan Paluch|OpenAI Codex|Pobieranie i przygotowanie zdjęć produktów|Pobieranie z limitem zapytań, domyślnie 10 wątków, wspólna komenda z pomiarem czasu, JPEG 800–1600 px do 300 KB, wznowienie, raport, archiwum i odtwarzanie z Releases|Poprawiono kolejność importów wskazaną przez Ruff; brak wcześniejszych błędnych ścieżek w ponownym eksporcie|54 testy, Ruff; pełny przebieg 18,46 min: 916 produktów i 966 poprawnych zdjęć, archiwum 51,6 MB|

|2026-11-22, Jan Jarzębiński|OpenAI Codex|Obsługa przerwania i wznowienia pobierania danych|Scraper zapisuje postęp pobierania produktów w UTF-8. Dodano testy wznowienia i resetu.|Brak zainstalowanych odpowiednich zależności, współdzielenie checkpointu --fresh ze zwykłym trybem --> mimo że cache było puste, program mógł nie pobrać danych bo bazował na progress.json stworzonym przez zwykły tryb.|Uruchomienie testów, ręczne sprawdznie dla --fresh, --fresh z przerwaniem, oraz --restart-fresh z przerwaniem, review|

|2026-11-25, Wojciech Goike|OpenAI Codex|Issue #31: uruchomienie PrestaShop przez Docker Compose|Przygotowano lokalną konfigurację HTTPS z przekierowaniem HTTP, konfigurację polskiego sklepu, poczty, płatności i przewoźników.|Błąd Dockera - engine uruchamiał i zamykał się w około 10 sekundowych odstępach z bliżej nieokreślonych przyczyn.|Statyczny przegląd konfiguracji i `docker compose config --quiet`; |

|2026-11-25, Wojciech Goike|OpenAI Codex|Issue #32: inicjalizacja katalogu PrestaShop z istniejących wyników scrapera|Dodano skrypt `deploy/init-catalog.py` oraz importer PHP.|Brak błędów.|Przegląd kodu i testów dodanych w `deploy/tests/`|

|2026-11-25, Wojciech Goike|OpenAI Codex|Issue #33: konfiguracja i weryfikacja polskiego sklepu, płatności i dostawy|Inicjalizacja włącza wyszukiwarkę i produkty na stronie głównej, buduje menu z aktywnych kategorii i ustawia polski checkout. Dodano testy Playwright, opis konfiguracji i polecenia w README.|Pierwsza próba Playwright zaczęła się przed końcem importu. Poprawiono oczekiwany temat wiadomości o prefiks PrestaShop, sprawdzanie odnośnika do regulaminu i selektor zdjęcia.|Start na świeżych wolumenach i przekierowanie 301. Import 915 produktów i 965 zdjęć w 9 min 24 s. Przeszło 60 testów Pythona, pięć przypadków dostawy i oba scenariusze Playwright w 9,3 s, łącznie z weryfikacją dwóch polskich e-maili.|
