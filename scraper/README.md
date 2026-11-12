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
| `SCRAPER_USER_AGENT` | `FishingShopEducationalScraper/1.0 (contact: replace-with-team-contact)` | Wartość nagłówka User-Agent dla przyszłych zapytań scrapera. Zastąp tekst kontaktowy właściwym kontaktem zespołu. |

Uruchom program z katalogu głównego repozytorium:

```powershell
python scraper/src/main.py
```

Logi są wypisywane w konsoli i zapisywane do `scraper/logs/scraper.log`; plik jest rotowany po przekroczeniu 2 MB, z zachowaniem trzech kopii. Program tworzy katalog logów automatycznie. Obecny punkt startowy sprawdza i loguje konfigurację, ale jeszcze nie pobiera stron ani nie zapisuje produktów do pliku wynikowego. Ścieżka wyniku jest już skonfigurowana i gotowa do użycia przez implementację scrapowania.
