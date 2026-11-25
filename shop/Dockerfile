FROM prestashop/prestashop:8.2.8-8.1-apache

RUN command -v openssl && command -v curl \
    && a2enmod ssl \
    && a2dissite 000-default

COPY shop/apache-local.conf /etc/apache2/sites-available/fishing-shop.conf
COPY shop/configure-local-shop.php /usr/local/share/fishing-shop/configure-local-shop.php
COPY shop/import-catalog.php /usr/local/share/fishing-shop/import-catalog.php
COPY --chmod=755 deploy/init-shop.sh /tmp/init-scripts/50-fishing-shop

RUN sed -i 's/\r$//' /tmp/init-scripts/50-fishing-shop \
    && a2ensite fishing-shop
