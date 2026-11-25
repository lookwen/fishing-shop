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

## Inicjalizacja katalogu

Na komputerze uruchamiającym import potrzebujesz Pythona 3.10 lub nowszego i istniejących zależności scrapera. Zainstaluj je jednorazowo poleceniem `python -m pip install -r scraper/requirements.txt`.

Po uruchomieniu sklepu wykonaj w katalogu głównym repozytorium:

```sh
python deploy/init-catalog.py
```

Skrypt sprawdza `scraper-results/products.json` według schematu scrapera, przygotowuje zdjęcia i przekazuje katalog do działającego kontenera `shop`. Kategorie zachowują źródłową hierarchię i przypisania, a gałęzie bez produktów są nieaktywne. Po udanym imporcie skrypt usuwa rozpoznane produkty demonstracyjne instalatora. Produkty powiązane z zamówieniami zachowuje i zgłasza w konsoli.

Ponowne uruchomienie aktualizuje rekordy po identyfikatorach źródłowych i przypisuje zdjęcia po adresach URL w obrębie produktu. Import przywraca deterministyczny stan magazynowy od 0 do 10 sztuk, więc ponowne uruchomienie zastępuje ręczne zmiany ilości. Dla obecnego pliku 92 z 915 produktów otrzymują stan 0 i są niedostępne do zamówienia. Warianty nie są częścią tego importu W3.

Domyślną walutą sklepu musi być PLN, a podatki muszą być włączone. PrestaShop przechowuje cenę netto wyliczoną z ceny brutto i stawki VAT. Przy braku stawki skrypt zachowuje podaną kwotę bez naliczania podatku i wykazuje taki rekord w raporcie. Obecny eksport podaje stawkę 23% dla wszystkich produktów. Wagi z eksportu są w kilogramach. Przy braku wagi PrestaShop używa technicznej wartości `0`, która oznacza brak wartości i jest zliczana w raporcie. W danych źródłowych wagę ma 17 produktów.

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

## Zatrzymanie

```sh
docker compose --env-file deploy/.env -f deploy/compose.yaml down
```

Wolumeny `db_data`, `shop_data` i `shop_tls` zachowują dane bazy, pliki sklepu i certyfikat na kolejny start.
