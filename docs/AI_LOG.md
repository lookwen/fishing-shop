

|Data i autor|Narzędzia i model|Zadanie|Co otrzymano|Co było błędne|Weryfikacja|
|-|-|-|-|-|-|
|2026-11-15, Jan Paluch|OpenAI Codex|Wielowątkowy odczyt danych produktów|Parser nazw, opisów, cen, VAT, cech, wagi, wariantów i URL-i zdjęć|Czas pobierania, dodano wątki|33 testy, ręczne odpalenie, test regresji, review|



|2026-11-21, Jan Paluch|OpenAI Codex|Pobieranie i przygotowanie zdjęć produktów|Pobieranie z limitem zapytań, domyślnie 10 wątków, wspólna komenda z pomiarem czasu, JPEG 800–1600 px do 300 KB, wznowienie, raport, archiwum i odtwarzanie z Releases|Poprawiono kolejność importów wskazaną przez Ruff; brak wcześniejszych błędnych ścieżek w ponownym eksporcie|54 testy, Ruff; pełny przebieg 18,46 min: 916 produktów i 966 poprawnych zdjęć, archiwum 51,6 MB|
