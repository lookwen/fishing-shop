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

## Katalog i konfiguracja sklepu

Do próbnego importu zapisz poniższy plik CSV w UTF-8 i w panelu wybierz **Zaawansowane → Importuj** oraz encję **Produkty**. Ustaw separator `;`, pomiń pierwszy wiersz, przypisz kolumny do nazwy, aktywności, ceny netto i ilości, po czym uruchom import. Produkt można sprawdzić w **Katalog → Produkty**, a ustawienia witryny zmienić w **Parametry sklepu**.

```csv
Nazwa;Aktywny;Cena netto;Ilość
Przynęta testowa;1;12.50;3
```

Eksport scrapera `scraper-results/products.json` ma osobny schemat opisany w [dokumentacji scrapera](scraper/README.md). Do zasilenia nim katalogu potrzebny jest etap importu danych.

## Zatrzymanie

```sh
docker compose --env-file deploy/.env -f deploy/compose.yaml down
```

Wolumeny `db_data`, `shop_data` i `shop_tls` zachowują dane bazy, pliki sklepu i certyfikat na kolejny start.
