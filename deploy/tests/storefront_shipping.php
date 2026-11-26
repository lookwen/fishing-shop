<?php

// Run against an initialized local test shop. Test records are rolled back.
$_SERVER['REQUEST_URI'] = '/';
require '/var/www/html/config/config.inc.php';

function checkShipping($result, string $message): void
{
    if (!$result) {
        throw new RuntimeException($message);
    }
}

$context = Context::getContext();
$shop = (int) Configuration::get('PS_SHOP_DEFAULT');
Shop::setContext(Shop::CONTEXT_SHOP, $shop);
$context->shop = new Shop($shop);
$context->language = new Language((int) Configuration::get('PS_LANG_DEFAULT'));
$context->currency = new Currency((int) Configuration::get('PS_CURRENCY_DEFAULT'));
$context->country = new Country((int) Configuration::get('PS_COUNTRY_DEFAULT'));
$context->customer = new Customer();
$context->link = new Link('https://', 'https://');
$db = Db::getInstance();
$prefix = _DB_PREFIX_;
$country = (int) $context->country->id;
$taxGroup = (int) $db->getValue("SELECT r.id_tax_rules_group FROM `{$prefix}tax_rule` r
    JOIN `{$prefix}tax` t ON t.id_tax = r.id_tax AND t.rate = 23 AND t.active = 1
    JOIN `{$prefix}tax_rules_group` g ON g.id_tax_rules_group = r.id_tax_rules_group AND g.active = 1 AND g.deleted = 0
    WHERE r.id_country = $country AND r.id_state = 0 AND r.zipcode_from = '0' AND r.zipcode_to = '0'");
checkShipping($taxGroup, 'Initialize the shop with the Polish VAT rules.');

checkShipping($db->execute('START TRANSACTION'), 'Cannot start fixture transaction.');
try {
    foreach ([
        [1999.99, 0.5, 1, [16.9, 24.9]],
        [2000.00, 50, 1, [16.9, 24.9]],
        [2000.01, 50, 1, [0.0, 0.0]],
        [2000.00, 50.000001, 1, []],
        [1000.01, 25.01, 2, []],
    ] as [$price, $weight, $quantity, $expected]) {
        $product = new Product(null, false, null, $shop);
        $language = (int) $context->language->id;
        $product->name = [$language => 'Shipping test fixture'];
        $product->link_rewrite = [$language => 'shipping-test-fixture'];
        $product->price = round($price / 1.23, 6);
        $product->id_tax_rules_group = $taxGroup;
        $product->weight = $weight;
        $product->id_category_default = (int) Configuration::get('PS_HOME_CATEGORY');
        $product->active = true;
        $product->visibility = 'none';
        checkShipping($product->add(), 'Cannot create fixture product.');
        StockAvailable::setQuantity((int) $product->id, 0, 2, $shop, false);

        $cart = new Cart();
        $cart->id_shop = $shop;
        $cart->id_shop_group = (int) $context->shop->id_shop_group;
        $cart->id_currency = (int) $context->currency->id;
        $cart->id_lang = $language;
        $context->cart = $cart;
        checkShipping($cart->add() && $cart->updateQty($quantity, (int) $product->id) === true, 'Cannot add fixture to cart.');
        checkShipping(round((float) $cart->getOrderTotal(true, Cart::ONLY_PRODUCTS), 2) === round($price * $quantity, 2), 'Unexpected gross fixture price.');

        $fees = [];
        foreach ($cart->getDeliveryOptionList($context->country, true) as $options) {
            foreach ($options as $option) {
                $fees[] = round((float) $option['total_price_with_tax'], 2);
            }
        }
        sort($fees, SORT_NUMERIC);
        $fixture = "$quantity x ($price PLN / $weight kg)";
        checkShipping($fees === $expected, "$fixture: expected " . json_encode($expected)
            . ', got ' . json_encode($fees));
        if (!$expected) {
            $default = (int) Configuration::get('PS_CARRIER_DEFAULT');
            $fallback = [0 => ["$default," => ['carrier_list' => [$default => []]]]];
            Module::getInstanceByName('fishingstorefront')->hookActionFilterDeliveryOptionList([
                'delivery_option_list' => &$fallback,
                'cart' => $cart,
            ]);
            checkShipping(!$fallback, "$fixture: default carrier was not removed.");
        }
        echo "$fixture: OK", PHP_EOL;
    }
} finally {
    $db->execute('ROLLBACK');
}
