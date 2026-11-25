#!/bin/sh
set -eu

tls_dir=/etc/apache2/local-tls
if [ ! -s "$tls_dir/localhost.crt" ] || [ ! -s "$tls_dir/localhost.key" ]; then
    umask 077
    staging_dir=$(mktemp -d "$tls_dir/.new.XXXXXX")
    trap 'rm -f "$staging_dir/localhost.key" "$staging_dir/localhost.crt"; rmdir "$staging_dir"' EXIT

    openssl req -x509 -nodes -newkey rsa:2048 -sha256 -days 365 \
        -subj '/CN=localhost' -addext 'subjectAltName=DNS:localhost' \
        -keyout "$staging_dir/localhost.key" -out "$staging_dir/localhost.crt"
    chmod 644 "$staging_dir/localhost.crt"
    mv "$staging_dir/localhost.key" "$tls_dir/localhost.key"
    mv "$staging_dir/localhost.crt" "$tls_dir/localhost.crt"
    rmdir "$staging_dir"
    trap - EXIT
fi

test -s /var/www/html/app/config/parameters.php
exec runuser -u www-data -- php /usr/local/share/fishing-shop/configure-local-shop.php
