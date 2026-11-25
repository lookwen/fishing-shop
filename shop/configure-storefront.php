<?php

use PrestaShop\Module\LinkList\Model\LinkBlock;

if (PHP_SAPI !== 'cli') {
    exit(1);
}

$_SERVER['REQUEST_URI'] = '/';
require '/var/www/html/config/config.inc.php';

function storefrontCheck($result, string $message): void
{
    if (!$result) {
        throw new RuntimeException($message);
    }
}

function storefrontSettings(array $settings): void
{
    foreach ($settings as $name => $value) {
        storefrontCheck(Configuration::updateValue($name, $value), "Cannot set $name.");
    }
}

function storefrontCurrency(int $shop, array $languages): Currency
{
    $plnId = (int) Currency::getIdByIsoCode('PLN', 0, true, true);
    if ($plnId > 0) {
        $pln = new Currency($plnId, null, $shop);
        $pln->deleted = false;
    } else {
        $pln = new Currency(null, null, $shop);
        $pln->iso_code = 'PLN';
        $pln->numeric_iso_code = '985';
        $pln->iso_code_num = '985';
        $pln->precision = 2;
        $pln->conversion_rate = 1;

        $names = $symbols = [];
        foreach ($languages as $languageId) {
            $names[(int) $languageId] = 'Polski złoty';
            $symbols[(int) $languageId] = 'zł';
        }
        $pln->name = $names;
        $pln->symbol = $symbols;
        $pln->pattern = (new Currency(
            (int) Configuration::get('PS_CURRENCY_DEFAULT'),
            null,
            $shop
        ))->getLocalizedPatterns();
        storefrontCheck($pln->add(), 'Cannot create PLN currency.');
    }
    if (!$pln->active) {
        $pln->active = true;
        storefrontCheck($pln->update(), 'Cannot activate PLN currency.');
    }
    if (!$pln->isInstalled($pln->id, $shop)) {
        storefrontCheck($pln->associateTo($shop), 'Cannot enable PLN for the default shop.');
    }
    $pln->conversion_rate = 1;
    storefrontCheck($pln->update(), 'Cannot update PLN currency.');
    return $pln;
}

function storefrontModule(string $name): Module
{
    $module = Module::getInstanceByName($name);
    storefrontCheck($module && (Module::isInstalled($name) || $module->install()), "Cannot install $name.");
    storefrontCheck($module->active || $module->enable(), "Cannot enable $name.");
    return $module;
}

function storefrontPages(Db $db, int $shop, array $languages): void
{
    $pages = require __DIR__ . '/storefront-pages.php';
    $ids = [];
    foreach ($pages as $key => [$title, $slug, $content]) {
        $id = (int) Configuration::get('FISHING_CMS_' . $key);
        $page = new CMS($id ?: null, null, $shop);
        $page->id_cms_category = 1;
        $page->active = true;
        $page->indexation = true;
        $page->meta_title = array_fill_keys($languages, $title);
        $page->head_seo_title = array_fill_keys($languages, $title);
        $page->link_rewrite = array_fill_keys($languages, $slug);
        $page->content = array_fill_keys($languages, $content);
        storefrontCheck($page->save(), "Cannot save CMS page $key.");
        $ids[$key] = (int) $page->id;
        storefrontSettings(['FISHING_CMS_' . $key => $ids[$key]]);
    }

    $demo = $db->executeS('SELECT DISTINCT id_cms FROM ' . _DB_PREFIX_ . "cms_lang WHERE id_cms BETWEEN 1 AND 5 AND link_rewrite IN
        ('delivery', 'legal-notice', 'terms-and-conditions-of-use', 'about-us', 'secure-payment')");
    foreach ($demo as $row) {
        $page = new CMS((int) $row['id_cms'], null, $shop);
        if ($page->active) {
            $page->active = false;
            storefrontCheck($page->update(), 'Cannot deactivate installer CMS page.');
        }
    }

    $footer = storefrontModule('ps_linklist');
    $hookId = (int) Hook::getIdByName('displayFooter');
    $blockId = (int) Configuration::get('FISHING_FOOTER_BLOCK');
    if (!$blockId) {
        $blockId = (int) $db->getValue('SELECT id_link_block FROM ' . _DB_PREFIX_ . "link_block
            WHERE id_hook = $hookId AND JSON_CONTAINS(content, '[\"1\",\"2\",\"3\",\"4\",\"5\"]', '$.cms')");
    }
    $block = new LinkBlock($blockId ?: null, null, $shop);
    $block->id_hook = $hookId;
    $block->name = array_fill_keys($languages, 'Informacje o sklepie');
    $block->content = ['cms' => array_values($ids), 'static' => ['contact', 'sitemap'], 'product' => [], 'category' => []];
    $block->custom_content = array_fill_keys($languages, '[]');
    storefrontCheck($block->save() && $block->associateTo($shop), 'Cannot save storefront footer links.');

    $productBlock = new LinkBlock(1, null, $shop);
    if ((int) $productBlock->id_hook === $hookId && ($productBlock->content['product'] ?? []) === ['prices-drop', 'new-products', 'best-sales']) {
        $productBlock->name = array_fill_keys($languages, 'Produkty');
        $productBlock->custom_content = array_map('json_encode', $productBlock->custom_content ?: []);
        storefrontCheck($productBlock->update(), 'Cannot translate the product links block.');
    }
    $footer->hookActionGeneralPageSave();

    storefrontModule('ps_mainmenu');
    $home = (int) Configuration::get('PS_HOME_CATEGORY');
    $privacy = array_fill_keys($languages, 'Dane testowe służą do obsługi konta, zamówień i kontaktu ze sklepem.');
    storefrontSettings([
        'FISHING_FOOTER_BLOCK' => (int) $block->id,
        'PS_CONDITIONS' => 1,
        'PS_CONDITIONS_CMS_ID' => $ids['TERMS'],
        'MOD_BLOCKTOPMENU_ITEMS' => 'CAT' . $home . ',CMS' . $ids['ABOUT'],
        'CUSTPRIV_MSG_AUTH' => $privacy,
        'NW_CONDITIONS' => array_fill_keys($languages, 'Newsletter jest opcjonalny. Szczegóły znajdziesz w Polityce prywatności sklepu.'),
    ]);
}

function storefrontCarriers(Db $db, int $shop, Country $country, int $language, array $languages): array
{
    $ids = [];
    foreach ([
        'STANDARD' => ['Przesyłka standardowa', 'Dostawa w 2–3 dni robocze', 16.90],
        'EXPRESS' => ['Przesyłka ekspresowa', 'Dostawa w 1–2 dni robocze', 24.90],
    ] as $key => [$name, $delay, $fee]) {
        $reference = (int) Configuration::get('FISHING_CARRIER_' . $key);
        $previous = $reference ? Carrier::getCarrierByReference($reference) : null;
        $id = (int) ($previous->id ?? 0);
        $carrier = new Carrier($id ?: null, null, $shop);
        $carrier->name = $name;
        $carrier->delay = array_fill_keys($languages, $delay);
        $carrier->active = true;
        $carrier->is_free = false;
        $carrier->shipping_handling = false;
        $carrier->shipping_method = Carrier::SHIPPING_METHOD_WEIGHT;
        $carrier->range_behavior = true;
        $carrier->max_weight = 50;
        storefrontCheck($carrier->save() && $carrier->associateTo($shop), "Cannot save $name.");
        $id = (int) $carrier->id;
        // Carrier::add() assigns the reference in the database.
        $reference = (int) ($carrier->id_reference ?: $id);
        storefrontSettings(['FISHING_CARRIER_' . $key => $reference]);
        $ids[$reference] = $id;
        $zone = (int) $country->id_zone;
        storefrontCheck(
            Carrier::checkCarrierZone($id, $zone) || $carrier->addZone($zone),
            "Cannot assign delivery zone to $name."
        );
        storefrontCheck($carrier->setGroups(array_column(Group::getGroups($language, $shop), 'id_group')), "Cannot set groups for $name.");
        storefrontCheck($carrier->setTaxRulesGroup(0), "Cannot set final delivery price for $name.");

        $range = new RangeWeight((int) $db->getValue('SELECT id_range_weight FROM ' . _DB_PREFIX_ . "range_weight WHERE id_carrier = $id") ?: null);
        $range->id_carrier = $id;
        $range->delimiter1 = 0;
        // PrestaShop excludes the upper bound. The module checks the complete cart.
        $range->delimiter2 = 50.000001;
        storefrontCheck($range->save(), "Cannot save weight range for $name.");
        storefrontCheck($carrier->addDeliveryPrice([[
            'id_carrier' => $id,
            'id_range_price' => null,
            'id_range_weight' => (int) $range->id,
            'id_zone' => $zone,
            'price' => $fee,
        ]], true), "Cannot set delivery fee for $name.");
    }

    // Keep old carrier records for order history and prevent any alternate checkout option.
    foreach (Carrier::getCarriers($language, true, false, false, null, Carrier::ALL_CARRIERS) as $row) {
        $id = (int) $row['id_carrier'];
        if (!in_array($id, $ids, true)) {
            $carrier = new Carrier($id);
            $carrier->active = false;
            storefrontCheck($carrier->update(), 'Cannot deactivate the previous carrier.');
        }
    }
    storefrontSettings([
        'PS_CARRIER_DEFAULT' => reset($ids),
        'PS_SHIPPING_FREE_PRICE' => '2000.01',
        'PS_SHIPPING_FREE_WEIGHT' => 0,
        'PS_SHIPPING_HANDLING' => 0,
    ]);
    return array_keys($ids);
}

function storefrontBankDetails(): array
{
    $bankOptions = [
        'BANK_WIRE_OWNER' => 'Fishing Shop – projekt studencki',
        'BANK_WIRE_DETAILS' => 'Zamówienie testowe. Nie wykonuj przelewu.',
        'BANK_WIRE_ADDRESS' => 'Instalacja lokalna',
    ];
    $supplied = array_filter(array_map(static fn ($key) => trim((string) getenv($key)), array_keys($bankOptions)), 'strlen');
    storefrontCheck(!$supplied || count($supplied) === count($bankOptions), 'Set all three BANK_WIRE_* values or leave all empty.');
    return $supplied ? array_combine(array_keys($bankOptions), $supplied) : $bankOptions;
}

function storefrontPayments(Db $db, int $shop, int $country, int $currency, array $carriers): void
{
    $allowed = ['ps_wirepayment', 'ps_cashondelivery'];
    foreach ($allowed as $name) {
        $id = (int) storefrontModule($name)->id;
        foreach (['country' => [$country], 'currency' => [$currency], 'carrier' => $carriers] as $restriction => $values) {
            foreach ($values as $value) {
                storefrontCheck($db->insert('module_' . $restriction, [
                    'id_module' => $id,
                    'id_shop' => $shop,
                    ($restriction === 'carrier' ? 'id_reference' : 'id_' . $restriction) => $value,
                ], false, true, Db::INSERT_IGNORE), "Cannot enable $name for $restriction.");
            }
        }
    }
    foreach (PaymentModule::getInstalledPaymentModules() as $row) {
        $module = Module::getInstanceByName($row['name']);
        if ($module && $module->active && !in_array($module->name, $allowed, true)) {
            storefrontCheck($module->disable(), "Cannot disable payment method {$module->name}.");
        }
    }
}

try {
    $bankDetails = storefrontBankDetails();
    $db = Db::getInstance();
    // The catalog importer uses the same session lock while modifying the shop.
    $lock = pSQL('fishing-catalog:' . substr(hash('sha256', _DB_NAME_ . ':' . _DB_PREFIX_), 0, 40));
    storefrontCheck((int) $db->getValue("SELECT GET_LOCK('$lock', 0)", false) === 1, 'Another shop initialization is running.');
    $shop = (int) Configuration::get('PS_SHOP_DEFAULT');
    Shop::setContext(Shop::CONTEXT_SHOP, $shop);
    $context = Context::getContext();
    $context->shop = new Shop($shop);
    $language = (int) Language::getIdByIso('pl');
    $country = new Country((int) Country::getByIso('PL'));
    storefrontCheck($language && $country->id, 'Install PrestaShop with PS_LANGUAGE=pl and PS_COUNTRY=PL.');
    $context->language = new Language($language);
    $context->country = $country;
    $context->link = new Link('https://', 'https://');
    require_once _PS_ROOT_DIR_ . '/app/AppKernel.php';
    $kernel = new AppKernel(_PS_ENV_, _PS_MODE_DEV_);
    $kernel->boot();

    $purifierCache = _PS_CACHE_DIR_ . 'purifier';
    storefrontCheck(is_dir($purifierCache) || mkdir($purifierCache), 'Cannot create the HTML purifier cache directory.');
    $languages = Language::getIDs(false, $shop);
    $currency = storefrontCurrency($shop, $languages);
    $context->currency = $currency;

    foreach (Country::getCountries($language, true) as $enabledCountry) {
        $id = (int) $enabledCountry['id_country'];
        if ($id !== (int) $country->id) {
            $other = new Country($id);
            $other->active = false;
            storefrontCheck($other->update(), 'Cannot restrict deliveries to Poland.');
        }
    }
    if (!$country->active) {
        $country->active = true;
        storefrontCheck($country->update(), 'Cannot enable Poland.');
    }
    storefrontSettings([
        'PS_SHOP_NAME' => 'Fishing Shop',
        'PS_LANG_DEFAULT' => $language,
        'PS_COUNTRY_DEFAULT' => (int) $country->id,
        'PS_CURRENCY_DEFAULT' => (int) $currency->id,
        'PS_DETECT_LANG' => 0,
        'PS_DETECT_COUNTRY' => 0,
        'PS_CATALOG_MODE' => 0,
        'PS_TAX' => 1,
        'PS_WEIGHT_UNIT' => 'kg',
        'PS_CUSTOMER_CREATION_EMAIL' => 1,
        'PS_MAIL_METHOD' => Mail::METHOD_SMTP,
        'PS_MAIL_SERVER' => 'mailpit',
        'PS_MAIL_SMTP_PORT' => 1025,
        'PS_MAIL_SMTP_ENCRYPTION' => 'off',
        'PS_MAIL_USER' => '',
        'PS_MAIL_PASSWD' => '',
    ]);
    storefrontPages($db, $shop, $languages);
    storefrontModule('ps_searchbar');
    storefrontModule('ps_featuredproducts');
    foreach ([
        'ps_banner', 'ps_imageslider', 'ps_customtext', 'ps_contactinfo', 'ps_socialfollow',
        'blockreassurance', 'ps_languageselector', 'ps_currencyselector',
    ] as $name) {
        $module = Module::getInstanceByName($name);
        if ($module && $module->active) {
            storefrontCheck($module->disable(), "Cannot disable $name.");
        }
    }

    $directory = _PS_MODULE_DIR_ . 'fishingstorefront';
    storefrontCheck(is_dir($directory) || mkdir($directory), 'Cannot create storefront module directory.');
    foreach (['fishingstorefront.php', 'cookies.tpl'] as $file) {
        storefrontCheck(copy(__DIR__ . "/fishingstorefront/$file", "$directory/$file"), "Cannot copy $file.");
    }
    $mailDirectory = "$directory/mails/pl";
    storefrontCheck(is_dir($mailDirectory) || mkdir($mailDirectory, 0775, true), 'Cannot create the Polish mail directory.');
    foreach (['account', 'order_conf', 'bankwire'] as $template) {
        foreach (['html', 'txt'] as $format) {
            $file = "$template.$format";
            storefrontCheck(copy(__DIR__ . "/fishingstorefront/mails/pl/$file", "$mailDirectory/$file"), "Cannot copy $file.");
        }
    }
    storefrontCheck(storefrontModule('fishingstorefront')->registerStorefrontHooks(), 'Cannot register storefront hooks.');
    $carriers = storefrontCarriers($db, $shop, $country, $language, $languages);
    storefrontSettings($bankDetails);
    storefrontPayments($db, $shop, (int) $country->id, (int) $currency->id, $carriers);
    echo "Polish storefront configured.\n";
} catch (Throwable $error) {
    fwrite(STDERR, 'Storefront initialization failed: ' . $error->getMessage() . PHP_EOL);
    exit(1);
}
