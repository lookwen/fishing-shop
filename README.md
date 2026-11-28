# Fishing Shop

Lokalny sklep działa na PrestaShop 8.2.8 z PHP 8.1 i Apache, MySQL 8.0.46 oraz Mailpit. Przy pierwszym starcie PrestaShop instaluje się automatycznie z językiem polskim i konfiguracją dla Polski.

## Wymagania i konfiguracja

Potrzebujesz Dockera z uruchomionym silnikiem dla kontenerów Linux, Docker Compose v2 i dostępu do Docker Hub. Compose używa obrazów `linux/amd64`. Na komputerze ARM silnik musi obsługiwać emulację tej architektury. Porty `8080`, `8443` i `8025` muszą być wolne na `127.0.0.1`.

Skopiuj `deploy/.env.example` do `deploy/.env`. Wpisz różne lokalne hasła w `MYSQL_ROOT_PASSWORD`, `MYSQL_PASSWORD` i `ADMIN_PASSWD`. `ADMIN_MAIL` i `ADMIN_PASSWD` określają konto administratora tworzone podczas pierwszej instalacji. Dla istniejących wolumenów zachowaj dotychczasowe dane dostępowe do bazy, a hasło administratora zmieniaj w panelu. Git ignoruje `deploy/.env`.

## Uruchomienie

W katalogu głównym repozytorium wykonaj jedną komendę:

```sh
docker compose --env-file deploy/.env -f deploy/compose.yaml up --build --wait --wait-timeout 480
```

Compose czeka na działające połączenie z MySQL i odpowiedź sklepu przez HTTPS. Pierwszy start obejmuje pobranie obrazów, utworzenie certyfikatu i instalację sklepu. W razie problemów użyj `docker compose --env-file deploy/.env -f deploy/compose.yaml logs db shop mailpit`.

| Usługa | Adres |
| --- | --- |
| Sklep | [https://localhost:8443/](https://localhost:8443/) |
| Panel administracyjny | [https://localhost:8443/admin-dev/](https://localhost:8443/admin-dev/) |
| Wejście HTTP z przekierowaniem 301 | [http://localhost:8080/](http://localhost:8080/) |
| Skrzynka Mailpit | [http://localhost:8025/](http://localhost:8025/) |

Apache używa samopodpisanego certyfikatu dla `localhost`. Możesz zaufać publicznemu certyfikatowi lokalnie w systemie lub przeglądarce. Aby skopiować certyfikat do katalogu tymczasowego w Windows, wykonaj w PowerShell:

```powershell
docker compose --env-file deploy/.env -f deploy/compose.yaml cp shop:/etc/apache2/local-tls/localhost.crt "$env:TEMP/localhost.crt"
```

Certyfikat jest ważny 365 dni od wygenerowania. Klucz prywatny pozostaje w wolumenie `shop_tls`. PrestaShop wysyła pocztę na `mailpit:1025` w sieci Compose. W panelu administracyjnym, w sekcji **Zaawansowane → E-mail**, możesz wysłać wiadomość testową i odczytać ją w Mailpit.

## Inicjalizacja sklepu i katalogu

Na komputerze uruchamiającym import potrzebujesz Pythona 3.10 lub nowszego i istniejących zależności scrapera. Zainstaluj je jednorazowo poleceniem `python -m pip install -r scraper/requirements.txt`.

Po uruchomieniu sklepu wykonaj w katalogu głównym repozytorium:

```sh
python deploy/init-catalog.py
```

Ta komenda konfiguruje polski sklep i checkout, sprawdza `scraper-results/products.json` według schematu scrapera, przygotowuje zdjęcia i importuje katalog do kontenera `shop`. Konfiguracja nie wymaga logowania do panelu administracyjnego. Kategorie zachowują źródłową hierarchię i przypisania, a gałęzie bez produktów są nieaktywne. Po udanym imporcie skrypt usuwa rozpoznane produkty demonstracyjne instalatora, ustawia menu na aktywne kategorie i odświeża indeks wyszukiwania. Produkty demonstracyjne powiązane z zamówieniami ukrywa i zachowuje w historii.

Ponowne uruchomienie aktualizuje rekordy po identyfikatorach źródłowych i przypisuje zdjęcia po adresach URL w obrębie produktu. Import przywraca deterministyczny zapas od 0 do 10 sztuk dla prostych produktów i demonstracyjnych wariantów D3, więc ponowne uruchomienie zastępuje ręczne zmiany tych ilości. Produkt prosty lub wariant ze stanem 0 jest niedostępny do zamówienia. Po imporcie obecnego pliku 91 z 915 produktów ma łączny stan 0.

Inicjalizacja ustawia PLN i włącza podatki. PrestaShop przechowuje cenę netto wyliczoną z ceny brutto i stawki VAT. Przy braku stawki skrypt zachowuje podaną kwotę bez naliczania podatku i wykazuje taki rekord w raporcie. Obecny eksport podaje stawkę 23% dla wszystkich produktów. Wagi z eksportu są w kilogramach. Przy braku wagi PrestaShop używa technicznej wartości `0`, która oznacza brak wartości i jest zliczana w raporcie. W danych źródłowych wagę ma 17 produktów.

### Promocje i warianty

Te same polecenia uruchomienia i importu tworzą **20 aktywnych obniżek** jako ceny specjalne PrestaShop i **13 kombinacji dla 5 produktów**. Konfiguracja demonstracyjna wskazuje produkty i warianty po identyfikatorach eksportu. Ceny bazowe pochodzą z katalogu, a każdy wariant ma własny zapas. Log importu zawiera liczniki `d3_promotions` i `d3_products_with_combinations`. [Konfiguracja D3](shop/d3-demo.json)

Moduł sklepu oblicza minimum z okresów obowiązywania cen brutto lub netto, osobno dla każdego wariantu, względem daty rozpoczęcia wybranej obniżki. Listy produktów, karta produktu, szybki podgląd i koszyk korzystają z tego samego minimum. Widoczny procent obniżki odnosi się do ceny historycznej. Ponowny import zachowuje daty istniejących promocji i ich historię. [Wytyczne UOKiK](https://prawakonsumenta.uokik.gov.pl/prawo-do-informacji/informacje-o-obnizkach-cen/)

### Witryna i zakup

Sklep ustawia język polski, kraj Polska i walutę PLN. Stopka zawiera strony O sklepie, Regulamin, Polityka prywatności, Dostawa i Formy płatności oraz informację o cookies. Wiadomości rejestracyjne i potwierdzenia zamówień trafiają do Mailpit.

- Dostępne są płatność przy odbiorze i przelew tradycyjny. W `deploy/.env` ustaw razem `BANK_WIRE_OWNER` (odbiorca), `BANK_WIRE_DETAILS` (numer konta i instrukcja) oraz `BANK_WIRE_ADDRESS` (adres odbiorcy). Puste pola włączają instrukcję demonstracyjną. Po zmianie wartości odtwórz kontener poleceniem startowym i ponów inicjalizację.
- Przesyłka standardowa kosztuje 16,90 zł, a ekspresowa 24,90 zł. Dostawa jest bezpłatna od 2 000,01 zł brutto wartości produktów i niedostępna po przekroczeniu 50 kg.

### Zdjęcia

Ustaw `CATALOG_IMAGES_ARCHIVE_URL` w `deploy/.env` na bezpośredni adres ZIP-a `product-images.zip` z GitHub Releases albo przekaż go przez `--archive-url`. ZIP używa ścieżek `images/<identyfikator>.jpg` zgodnych z [eksportem scrapera](scraper/README.md#pobieranie-zdjęć). Import wykorzystuje zweryfikowane pliki z `deploy/cache/catalog/images/` i `scraper-results/images/`. W razie braków korzysta z archiwum, a następnie z adresów źródłowych w JSON-ie. Pobieranie respektuje `robots.txt` i limit 2 żądań/s. Kontakt w nagłówku User-Agent ustaw w `scraper/config/.env` przez `SCRAPER_USER_AGENT`.

Skrypt wymaga co najmniej jednego zdjęcia na produkt oraz dwóch dla co najmniej 50 produktów. Oryginały zapisywane w sklepie są JPEG-ami o dłuższym boku 800–1600 px i rozmiarze do 300 000 bajtów. PrestaShop dostaje też miniatury potrzebne do wyświetlania katalogu. Pełen zestaw zdjęć pozostaje w ignorowanych lokalnych katalogach, w wolumenie sklepu oraz w opcjonalnym archiwum wydania.

Konsola podaje liczbę przygotowanych zdjęć oraz liczniki rekordów utworzonych, zaktualizowanych i odrzuconych przez PrestaShop. Błędy wskazują etap lub źródłowy identyfikator produktu. Brak wymaganych zdjęć przerywa inicjalizację przed zapisem w sklepie. Błędy zapisu kończą komendę kodem 1. Po usunięciu przyczyny można uruchomić tę samą komendę i dokończyć zapis.

### Liczba produktów

Obecny eksport ma 918 unikalnych odkrytych adresów produktów i 915 poprawnych rekordów gotowych do importu. [Raport scrapera](scraper-results/products-report.json) wyjaśnia różnicę:

| Oferta | Przyczyna odrzucenia |
| --- | --- |
| Linka Scientific Anglers Sonar Titan | Strona zakończyła się odpowiedzią HTTP 404. |
| Fly Dip Floatant Revolution | Brak zdjęcia w zebranych danych. |
| Orvis Co T-shirt | Brak opisu, ceny, waluty i zdjęcia w zebranych danych. |

Poprzedni zapis w repozytorium miał 916 poprawnych rekordów z 919 odkrytych. Powtórne przejście po menu i stronicowaniu z lokalnego cache odczytało 105 stron, 104 kategorie i 917 ofert. W porównaniu z bieżącym plikiem dwie oferty były tylko w cache, a trzy tylko w eksporcie. Obie listy łącznie obejmowały 920 identyfikatorów. W bieżącym eksporcie 12 kategorii głównych ma co najmniej dwie bezpośrednie podkategorie z produktami.

Wyniki opisują katalog widoczny w zapisanych przebiegach scrapera. Potwierdzenie wyjątku W3 od progu 1000 wymaga pełnej aktualnej listy ze źródła, np. kompletnej mapy produktów, albo potwierdzenia liczby ofert przez Flyhouse. Inicjalizacja importuje 915 poprawnych rekordów i zgłasza liczbę poniżej progu.

## Weryfikacja witryny i dostawy

Na działającym lokalnym sklepie po inicjalizacji zainstaluj Node.js (co najmniej 18), zależności testów i Chromium:

```sh
npm --prefix tests ci
cd tests
npx playwright install chromium
cd ..
```

Polecenie `npm --prefix tests test` uruchamia wszystkie zestawy. Domyślny adres sklepu to `https://localhost:8443/`, a Mailpit `http://localhost:8025`. Adres sklepu możesz zmienić zmienną `SHOP_URL`. Jeśli masz już Chrome lub Edge, możesz zamiast instalowania Chromium ustawić `PLAYWRIGHT_CHANNEL` odpowiednio na `chrome` lub `msedge`. Testy zakupu tworzą konta i zamówienia oraz zmniejszają stan magazynowy kupionych produktów.

Raport HTML trafia do `tests/playwright-report/`, a zrzuty po błędzie do `tests/test-results/`. Z katalogu głównego otworzysz raport poleceniem `node tests/node_modules/playwright/cli.js show-report tests/playwright-report`.

### Testy witryny (W3)

Uruchom `npm --prefix tests run test:storefront`. Testy sprawdzają katalog, wyszukiwarkę, CMS i cookies oraz rejestrację, logowanie, podstawowy zakup i wiadomości. Domyślny adres Mailpit to `http://localhost:8025/`. Możesz go zmienić zmienną `MAILPIT_URL`.

### Pełny zakup z fakturą VAT (W4)

Uruchom `npm --prefix tests run test:checkout`. Test sprawdza dodawanie i usuwanie produktów, rejestrację klienta, wybór dostawy, płatność przy odbiorze, status zamówienia i pobranie faktury VAT. Fakturowanie włącza inicjalizacja sklepu. Test działa bez Mailpit.

### Test reguł dostawy

Test reguł dostawy jest osobnym testem PHP wykonywanym na zainicjalizowanym sklepie. Sprawdza m.in. koszyki o wartości 2 000,00 i 2 000,01 zł oraz wadze 50 i 50,000001 kg, w tym odrzucenie przewoźnika zapasowego. Test wycofuje tymczasowe rekordy po zakończeniu.

```powershell
Get-Content -Raw deploy/tests/storefront_shipping.php |
  docker compose --env-file deploy/.env -f deploy/compose.yaml exec -T --user www-data shop php
```

### Wynik próby W3 i ograniczenia

- Próba z 25.11.2026 na świeżych wolumenach zapisała 915 produktów, 104 kategorie i 965 zdjęć z opublikowanego ZIP-a, bez odrzuconych produktów. 50 produktów otrzymało dwa zdjęcia, a 92 miały zerowy stan magazynowy. Próg 1 000 wymaga potwierdzenia wyjątku dotyczącego wielkości katalogu źródłowego.
- Oba scenariusze Playwright przeszły w 9,3 s w lokalnym Chrome w trybie headless. Test PHP potwierdził pięć przypadków dostawy, w tym opłaty na granicy 2 000 zł i blokadę koszyka ważącego ponad 50 kg.
- Git nadal śledzi 20 próbek w `scraper-results/sample-images/`. Zgodność z wymaganiem przechowywania zdjęć poza repozytorium wymaga usunięcia tych próbek z Git.
- W tej próbie komenda inicjalizacji zajęła 9 min 24 s, w tym pobranie ZIP-a, przygotowanie plików, import i indeksowanie. Compose osiągnął stan `healthy` na świeżych wolumenach przy wcześniej pobranych obrazach bazowych. Czasu komendy startowej nie mierzono. W PowerShell czas samej inicjalizacji zmierzysz przez `Measure-Command { python deploy/init-catalog.py | Out-Host }`.

## Zatrzymanie

```sh
docker compose --env-file deploy/.env -f deploy/compose.yaml down
```

Wolumeny `db_data`, `shop_data` i `shop_tls` zachowują dane bazy, pliki sklepu i certyfikat na kolejny start.

## Backup i odtwarzanie (D4)

Kopia obejmuje zrzut bazy MySQL, pliki sklepu ze zdjęciami i konfiguracją oraz certyfikat z kluczem. Cache i logi aplikacji są pomijane. Podczas wykonywania kopii skrypt zatrzymuje tylko usługę `shop`, aby zamówienia i pliki nie zmieniały się w trakcie zapisu; na końcu ponownie ją uruchamia, również po błędzie. Baza musi działać.

```powershell
python deploy/backup.py
```

Komenda wypisuje katalog `deploy/backups/backup-*`. Kopia zawiera `database.sql`, `shop.tar.gz`, `tls.tar.gz`, `settings.json` i manifest z sumami SHA-256 oraz licznikami rekordów. Nie nadpisuje istniejącej kopii. Backup jest prywatny: może zawierać dane klientów, hasła konfiguracji i klucz certyfikatu. `deploy/backups/` jest wykluczony z Git; nie publikuj tych kopii w Releases.

Do repo trafia wyłącznie `deploy/shop-settings.json`: jawna lista dozwolonych ustawień sklepu, podatków i dostawy. Backup aktualizuje ten eksport, pomijając dane kont, pocztę, hasła, klucze API i dane bankowe. Pozostała odtwarzalna konfiguracja znajduje się w skryptach inicjalizacji oraz Compose. Same publiczne ustawienia można zastosować na działającym sklepie:

```powershell
python deploy/restore.py --settings-only
```

### Odtworzenie na czystym środowisku

Przygotuj `deploy/.env.restore` na podstawie `.env.example`, ustaw lokalne hasła i, gdy obecny sklep działa, inne wolne porty, np.:

```dotenv
SHOP_HTTP_PORT=18080
SHOP_HTTPS_PORT=18443
MAILPIT_HTTP_PORT=18025
```

`deploy/.env.restore` jest ignorowany przez Git. Nowe hasło bazy może różnić się od hasła w kopii: skrypt dostosuje połączenie PrestaShop do docelowej konfiguracji, zachowując pozostałe klucze aplikacji.

Wskaż rzeczywisty katalog kopii i nową nazwę projektu:

```powershell
python deploy/restore.py deploy/backups/backup-NAZWA --project fishing-restore --env-file deploy/.env.restore
```

Skrypt sprawdza kompletność i sumy kontrolne, buduje obraz sklepu, uruchamia nową bazę, odtwarza bazę i pliki oraz ustawia docelowy adres HTTPS. Porównuje liczby produktów, kategorii, zdjęć, klientów i zamówień z kopią. Następnie czeka na gotowość usług i wypisuje czas całej operacji. Nie uruchamia scrapera ani ponownego importu katalogu. Docelowy projekt nie może mieć istniejących kontenerów ani wolumenów; skrypt odmawia nadpisania takiego środowiska. Po nieudanej próbie użyj kolejnej nowej nazwy projektu.

Dla przykładowych portów sprawdź `https://localhost:18443/`, przekierowanie z `http://localhost:18080/` i panel `https://localhost:18443/admin-dev/`. Hasło administratora pozostaje takie jak w kopii bazy. Hasło z `ADMIN_PASSWD` nie resetuje istniejących kont.

Kolejne komendy Compose kieruj do tego samego projektu i pliku konfiguracji:

```powershell
docker compose --project-name fishing-restore --env-file deploy/.env.restore -f deploy/compose.yaml ps
```

Przed odbiorem wykonaj próbę z pełnym katalogiem, sprawdź zdjęcia, logowanie i zamówienia oraz czas odtworzenia do 10 minut. Pomiar obejmuje budowanie/pobieranie obrazów; zależy również od dostępności sieci i sprzętu. Skrypt nie potwierdza zaliczenia limitu samym zakończeniem bez błędów — porównaj wypisany czas z progiem.

Testy Pythona dla scrapera, inicjalizacji i backupu:

```powershell
python -m pytest scraper/tests deploy/tests -q
```

Próba D4 z 27.11.2026: odtworzono pełny sklep z 915 zaimportowanymi produktami i 965 zdjęciami w 1,30 min na nowych wolumenach, z wcześniej pobranymi obrazami Dockera. Kopia zachowała również rekordy demonstracyjne powiązane z historią: łącznie 921 rekordów produktów, 113 kategorii, 973 zdjęcia, 3 klientów i 5 zamówień. Sklep docelowy używał innych portów i nowego hasła bazy. Potwierdzono zgodność wszystkich JPEG-ów produktów i miniatur, hasła konta testowego, klucza aplikacji, ustawień, certyfikatu, odpowiedzi HTTPS 200 i przekierowania HTTP 301. Osobna próba przywróciła zmieniony próg dostawy z `shop-settings.json`. Próba odtwarzania na istniejącym projekcie została odrzucona bez zmiany jego rekordów.
