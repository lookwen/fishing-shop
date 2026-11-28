<?php

$_SERVER['REQUEST_URI'] = '/';
$action = getenv('FISHING_BACKUP_ACTION');
$path = '/var/www/html/app/config/parameters.php';

if ($action === 'restore') {
    $parameters = require $path;
    foreach (['database_host' => 'DB_SERVER', 'database_name' => 'DB_NAME',
              'database_user' => 'DB_USER', 'database_password' => 'DB_PASSWD'] as $key => $environment) {
        $parameters['parameters'][$key] = getenv($environment);
    }
    $parameters['parameters']['database_port'] = '3306';
    if (file_put_contents($path, '<?php return ' . var_export($parameters, true) . ';', LOCK_EX) === false) {
        throw new RuntimeException('Cannot update restored database credentials.');
    }
    chmod($path, 0640);
}

require '/var/www/html/config/config.inc.php';
$keys = ['PS_SHOP_NAME', 'PS_WEIGHT_UNIT', 'PS_TAX', 'PS_INVOICE', 'PS_CONDITIONS',
         'PS_SHIPPING_FREE_PRICE', 'PS_SHIPPING_FREE_WEIGHT', 'PS_SHIPPING_HANDLING',
         'PS_DETECT_LANG', 'PS_DETECT_COUNTRY', 'PS_CATALOG_MODE'];

if ($action === 'restore' || $action === 'apply') {
    $data = json_decode(base64_decode(getenv('FISHING_BACKUP_SETTINGS')), true, 512, JSON_THROW_ON_ERROR);
    $supplied = array_keys($data['settings']);
    sort($supplied);
    $expected = $keys;
    sort($expected);
    if ($data['version'] !== 1 || $supplied !== $expected) {
        throw new RuntimeException('Invalid public settings export.');
    }
    foreach ($data['settings'] as $name => $value) {
        if (!Configuration::updateValue($name, $value)) {
            throw new RuntimeException('Cannot restore public setting ' . $name);
        }
    }
}

if ($action === 'restore') {
    $shop = (int) Configuration::get('PS_SHOP_DEFAULT');
    $url = ShopUrl::getShopUrls($shop)->where('main', '=', 1)->getFirst();
    $url->domain = getenv('PS_DOMAIN');
    $url->domain_ssl = getenv('PS_DOMAIN');
    if (!$url->update()
        || !Configuration::updateValue('PS_SHOP_DOMAIN', getenv('PS_DOMAIN'))
        || !Configuration::updateValue('PS_SHOP_DOMAIN_SSL', getenv('PS_DOMAIN'))
        || !Tools::generateHtaccess()) {
        throw new RuntimeException('Cannot configure the restored shop URL.');
    }
}

$settings = [];
foreach ($keys as $name) {
    $settings[$name] = Configuration::get($name);
}
$counts = [];
foreach (['product', 'category', 'image', 'customer', 'orders'] as $table) {
    $counts[$table] = (int) Db::getInstance()->getValue('SELECT COUNT(*) FROM `' . _DB_PREFIX_ . $table . '`');
}
echo json_encode(['settings' => $settings, 'counts' => $counts, 'prestashop_version' => _PS_VERSION_], JSON_THROW_ON_ERROR), PHP_EOL;
