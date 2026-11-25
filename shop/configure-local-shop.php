<?php

$_SERVER['REQUEST_URI'] = '/';
require '/var/www/html/config/config.inc.php';

$marker = 'FISHING_SHOP_LOCAL_CONFIGURED';
if (Configuration::getGlobalValue($marker)) {
    exit(0);
}

$shopId = (int) Configuration::get('PS_SHOP_DEFAULT');
$url = ShopUrl::getShopUrls($shopId)->where('main', '=', 1)->getFirst();
if (!$url) {
    throw new RuntimeException('Missing main PrestaShop URL.');
}

$domain = getenv('PS_DOMAIN');
$url->domain = $domain;
$url->domain_ssl = $domain;
if (!$url->update()) {
    throw new RuntimeException('Could not save the PrestaShop URL.');
}

$settings = [
    'PS_SHOP_DOMAIN' => $domain,
    'PS_SHOP_DOMAIN_SSL' => $domain,
    'PS_SSL_ENABLED' => 1,
    'PS_SSL_ENABLED_EVERYWHERE' => 1,
    'PS_MAIL_METHOD' => Mail::METHOD_SMTP,
    'PS_MAIL_SERVER' => 'mailpit',
    'PS_MAIL_SMTP_PORT' => 1025,
    'PS_MAIL_SMTP_ENCRYPTION' => 'off',
    'PS_MAIL_USER' => '',
    'PS_MAIL_PASSWD' => '',
];

foreach ($settings as $name => $value) {
    if (!Configuration::updateValue($name, $value)) {
        throw new RuntimeException('Could not save PrestaShop setting ' . $name);
    }
}

if (!Tools::generateHtaccess()) {
    throw new RuntimeException('Could not regenerate the PrestaShop Apache rules.');
}

if (!Configuration::updateGlobalValue($marker, 1)) {
    throw new RuntimeException('Could not mark local configuration as complete.');
}
