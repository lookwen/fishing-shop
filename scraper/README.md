# Schemat danych scrapera

Plik `schema.json` opisuje format eksportu danych w UTF-8 jako dokument JSON. Jeden dokument zawiera informacje o sklepie źródłowym, kategorie wraz z podkategoriami oraz produkty. Schemat określa typy danych, pola wymagane i podstawowe ograniczenia wartości.

## Pola głównego dokumentu

| Pole | Wymagane | Znaczenie |
| --- | --- | --- |
| `source` | Tak | Informacje o sklepie, z którego pochodzą dane. |
| `categories` | Tak | Lista kategorii i podkategorii. Może być pusta, jeśli źródło nie udostępniło kategorii. |
| `products` | Tak | Lista produktów. Może być pusta, jeśli źródło nie udostępniło produktów. |

## Źródło

| Pole | Wymagane | Znaczenie |
| --- | --- | --- |
| `source.name` | Tak | Nazwa sklepu źródłowego, niepusty tekst. |
| `source.base_url` | Tak | Absolutny adres HTTP lub HTTPS sklepu źródłowego. |

## Kategorie i podkategorie

Każda kategoria i podkategoria jest osobnym elementem `categories`. Kategorię główną wskazuje `parent_source_id: null`; podkategoria zawiera identyfikator nadrzędnej kategorii.

| Pole | Wymagane | Znaczenie |
| --- | --- | --- |
| `source_id` | Tak | Stabilny, niepusty identyfikator kategorii w danych źródłowych. Służy do łączenia rekordów. |
| `name` | Tak | Niepusta nazwa kategorii. |
| `url` | Tak | Absolutny adres HTTP lub HTTPS strony kategorii. |
| `parent_source_id` | Tak | Identyfikator kategorii nadrzędnej albo `null` dla kategorii głównej. Pole jest wymagane także wtedy, gdy jego wartość to `null`, aby jednoznacznie opisać hierarchię. |

## Odkryte linki produktów

Eksport z etapu odkrywania zapisuje również tablicę `product_listings`. Każdy wpis zawiera `source_id` (stabilny identyfikator wyliczony z URL), `name` (nazwę wyświetlaną na karcie produktu), `url` (pełny adres strony produktu w sklepie źródłowym) i `category_ids` (identyfikatory kategorii, w których produkt został znaleziony). Pełne rekordy `products` pozostają osobną częścią schematu i mogą być uzupełnione w następnym kroku scrapowania.

## Produkty

| Pole | Wymagane | Znaczenie |
| --- | --- | --- |
| `source_id` | Tak | Stabilny identyfikator produktu w sklepie źródłowym. |
| `url` | Tak | Absolutny adres HTTP lub HTTPS strony produktu. |
| `name` | Tak | Niepusta nazwa produktu. |
| `description` | Tak | Niepusty opis produktu. |
| `price_gross` | Tak | Cena brutto jako liczba nieujemna. |
| `currency` | Tak | Waluta ceny; obecny schemat dopuszcza wyłącznie `PLN`. |
| `category_ids` | Tak | Niepusta lista identyfikatorów kategorii przypisanych do produktu. Identyfikatory nie mogą się powtarzać. |
| `images` | Tak | Niepusta lista zdjęć. Każdy produkt musi mieć co najmniej jedno zdjęcie. |
| `price_net` | Nie | Cena netto jako liczba nieujemna lub `null`, gdy źródło jej nie podaje. |
| `vat_rate` | Nie | Stawka VAT w procentach, od 0 do 100, albo `null`, gdy nie jest dostępna. |
| `weight_kg` | Nie | Waga w kilogramach jako liczba nieujemna lub `null`, jeśli nie jest dostępna. |
| `brand` | Nie | Niepusta nazwa marki albo `null`, gdy brak informacji. |
| `reference` | Nie | Niepusty numer katalogowy/referencyjny albo `null`, gdy brak informacji. |
| `attributes` | Nie | Lista dodatkowych cech produktu, np. koloru lub materiału. Domyślnie brak cech oznacza pustą listę. |
| `variants` | Nie | Lista wariantów produktu, np. rozmiarów. Produkt bez wariantów może pominąć pole albo podać pustą listę. |

### Atrybuty

Każdy element `attributes` ma wymagane pola `name` i `value`, oba niepustymi tekstami. Na przykład: `{ "name": "Kolor", "value": "Czarny" }`.

### Warianty

Każdy element `variants` wymaga:

| Pole | Wymagane | Znaczenie |
| --- | --- | --- |
| `source_id` | Tak | Identyfikator wariantu w źródle. |
| `attributes` | Tak | Mapa cech wariantu, np. `{ "size": "M" }`. Mapa może być pusta, jeśli źródło wariantu nie podaje cech. |
| `price_gross` | Tak | Cena brutto wariantu jako liczba nieujemna. |
| `availability_text` | Nie | Tekst dostępności ze źródła albo `null`, jeśli nie został podany. |

### Zdjęcia

Każdy element `images` wymaga:

| Pole | Wymagane | Znaczenie |
| --- | --- | --- |
| `source_url` | Tak | Absolutny adres HTTP lub HTTPS zdjęcia w sklepie źródłowym. |
| `position` | Tak | Pozycja zdjęcia jako liczba całkowita od 1 wzwyż. |
| `local_path` | Nie | Ścieżka do lokalnej kopii zdjęcia, jeśli została pobrana, albo `null`. |

## Zasady walidacji i ograniczenia

- Obiekty na najwyższym poziomie, kategorie, produkty, atrybuty, warianty i zdjęcia nie przyjmują nieopisanych pól (`additionalProperties: false`).
- URL-e muszą być absolutnymi adresami HTTP lub HTTPS.
- Wartości tekstowe identyfikatorów i nazw, które mają `minLength: 1`, nie mogą być puste.
- Kwoty, wagi oraz pozycje zdjęć nie mogą być ujemne; `position` zaczyna się od 1.
- `vat_rate` jest ograniczone do zakresu 0–100.
- JSON Schema sprawdza strukturę pojedynczego dokumentu, ale nie sprawdza powiązań między rekordami. Osobna walidacja powinna potwierdzić m.in., że `category_ids` i `parent_source_id` wskazują istniejące kategorie oraz że identyfikatory są unikalne.
- Wymóg odpowiedniej rozdzielczości i rozmiaru plików zdjęć (dłuższy bok 800–1600 px, maks. 300 KB) wymaga walidacji pobranych plików; sam adres URL nie pozwala go sprawdzić.

Wymagane pola są wymagane, ponieważ stanowią minimum potrzebne do rozpoznania źródła, umiejscowienia produktu w katalogu, wyświetlenia podstawowej oferty (nazwa, opis i cena) oraz pobrania przynajmniej jednego zdjęcia. VAT, waga, cena netto, marka, referencja i dostępność wariantu są opcjonalne, bo sklep źródłowy może ich nie publikować; brak danych nie powinien uniemożliwiać zapisania produktu. Kategorie wymagają jawnego `parent_source_id`, aby rekord sam rozstrzygał, czy jest kategorią główną, czy podkategorią.

## Uruchamianie narzędzia

Wymagany jest Python 3.10 lub nowszy. Z katalogu głównego repozytorium zainstaluj zależność:

```powershell
python -m pip install -r scraper/requirements.txt
```

Skopiuj `scraper/config/.env.example` do `scraper/config/.env` i dostosuj wartości, w szczególności kontakt w `SCRAPER_USER_AGENT`. Plik `.env` jest lokalny i nie należy go commitować. Zmienne ustawione w środowisku procesu mają pierwszeństwo przed wartościami z `.env`.

| Zmienna | Domyślna wartość | Znaczenie |
| --- | --- | --- |
| `SCRAPER_SOURCE_URL` | `https://flyhouse.pl/pl/` | Adres strony źródłowej. |
| `SCRAPER_OUTPUT_PATH` | `scraper-results/products.json` | Docelowa ścieżka eksportu; ścieżki względne są liczone od katalogu głównego repozytorium. |
| `SCRAPER_LOG_PATH` | `scraper/logs/scraper.log` | Plik logu; katalog nadrzędny jest tworzony automatycznie. |
| `SCRAPER_CACHE_DIR` | `scraper/cache/pages` | Lokalny cache HTML używany do wznowienia pracy bez ponownego pobierania zapisanych stron. Cache jest wykluczony z Git. |
| `SCRAPER_USER_AGENT` | `FishingShopEducationalScraper/1.0 (course project; contact: team@example.invalid)` | Opisowy nagłówek User-Agent wysyłany z żądaniami HTTP. Zastąp przykładowy kontakt właściwym kontaktem zespołu. |
| `SCRAPER_REQUEST_TIMEOUT` | `20` | Limit czasu pojedynczego żądania w sekundach, od 0 do 120 (wartość musi być większa od 0). |
| `SCRAPER_WORKERS` | `10` | Liczba wątków produktów i zdjęć, od 1 do 16; wspólny limit nadal wynosi 2 zapytania/s. |
| `SCRAPER_MAX_RETRIES` | `2` | Maksymalna liczba ponowień po pierwszym żądaniu, od 0 do 5. |

Uruchom program z katalogu głównego repozytorium:

```powershell
python scraper/src/main.py
```

Logi są wypisywane w konsoli i zapisywane do `scraper/logs/scraper.log`; plik jest rotowany po przekroczeniu 2 MB, z zachowaniem trzech kopii. Program tworzy katalog logów automatycznie. Scraper odczytuje hierarchię kategorii z menu sklepu, przechodzi po stronach kategorii i stronicowaniu, a z kart produktu zbiera nazwę i URL. Wysyła opisowy nagłówek `User-Agent`, sprawdza `robots.txt` dla każdego hosta (również po przekierowaniu), ogranicza wszystkie żądania do maksymalnie 2 na sekundę i loguje błędy. Błędy sieciowe oraz HTTP 408, 429 i 5xx są ponawiane z wykładniczym opóźnieniem, maksymalnie `SCRAPER_MAX_RETRIES` razy; pozostałe błędy 4xx nie są ponawiane. Pobrane strony są zapisywane atomowo w `SCRAPER_CACHE_DIR`, więc ponowne uruchomienie używa cache. Eksport `products.json` jest sprawdzany względem `schema.json` i zapisywany jako UTF-8. Cache można wyczyścić ręcznie, aby pobrać świeżą wersję źródła.

## Testy i lint

Zależności testowe i Ruff zainstalujesz poleceniem:

```powershell
python -m pip install -r scraper/requirements-dev.txt
```

Uruchom lokalnie te same kontrole co pipeline GitHub Actions:

```powershell
python -m ruff check scraper
python -m pytest scraper/tests -q
```

Workflow `.github/workflows/scraper-ci.yml` uruchamia się dla każdego pull requestu oraz po pushu do `dev` i `main`.

## Pobieranie zdjęć

Po pobraniu danych produktów uruchom z katalogu głównego repozytorium:

```powershell
python -m pip install -r scraper/requirements.txt
python scraper/src/images.py
```

Program pobiera co najmniej jedno zdjęcie każdego produktu i co najmniej dwa dla 50 produktów. Pobieranie pierwszych zdjęć używa `SCRAPER_WORKERS` wątków (domyślnie 10) ze wspólnym limitem 2 zapytań/s, robots.txt i User-Agent z obecnej konfiguracji. Ponowne uruchomienie pomija poprawne pliki, także po przerwaniu poprzedniego przebiegu.

Zdjęcia są zapisywane jako JPEG, z dłuższym bokiem 800–1600 px i rozmiarem do 300 000 bajtów. Źródła poniżej 800 px są odrzucane; program próbuje kolejnych adresów produktu. Ścieżki `images[].local_path` są względne wobec katalogu zawierającego `products.json`.

Wyniki:

- `scraper-results/images/` — przygotowane zdjęcia, poza Git.
- `scraper-results/products.json` — dotychczasowe dane i lokalne ścieżki zdjęć.
- `scraper-results/images-report.json` — braki i błędy; niespełnienie wymagań kończy program kodem 1.
- `scraper-results/product-images.zip` — archiwum do 1 GB, tworzone po spełnieniu wymagań, poza Git.
- `scraper-results/sample-images/` — do 20 przykładowych zdjęć do repozytorium.
- `scraper/logs/images.log` — log pobierania i błędów.

Archiwum `product-images.zip` dodaj jako załącznik w GitHub Releases. Na czystym klonie pobierz je i odtwórz zdjęcia poleceniem, podając rzeczywisty adres załącznika:

```powershell
python scraper/src/images.py --archive-url "ADRES_ZALACZNIKA_Z_RELEASE"
```

Jeśli archiwum jest niedostępne, program pobierze zdjęcia z adresów źródłowych zapisanych w `products.json`. Tę komendę należy wywołać przed importem zdjęć w skrypcie inicjalizacji sklepu. Samo uruchomienie `main.py` pobiera dane tekstowe i adresy zdjęć.

## Pełny przebieg z pomiarem czasu

```powershell
python scraper/run.py
```

Komenda uruchamia kolejno pobieranie danych i zdjęć oraz wypisuje czas obu etapów i łączny. Domyślnie korzysta z 10 wątków i istniejącego cache. Liczbę wątków zmienia `SCRAPER_WORKERS`; wspólny limit nadal wynosi 2 zapytania/s. Kategorie i dobieranie dodatkowych zdjęć są obsługiwane kolejno.

Świeży test bez usuwania poprzednich danych:

```powershell
python scraper/run.py --fresh
```

Wariant `--fresh` zapisuje HTML, JSON, zdjęcia, raporty i ZIP w nowym katalogu `scraper/cache/run-*`, wyświetlanym przy uruchomieniu. Te wyniki są poza Git. Zwykły przebieg zapisuje wyniki zgodnie z konfiguracją, domyślnie w `scraper-results/`.

Kod 1 etapu danych z nowo zapisanym JSON-em oznacza częściowy eksport i nie blokuje zdjęć. Raport odrzuconych produktów pozostaje do sprawdzenia. Brak nowego JSON-a przerywa przebieg. Końcowy kod 0 potwierdza spełnienie wymagań zdjęć dla wyeksportowanych produktów, także gdy część produktów odrzucono wcześniej.
