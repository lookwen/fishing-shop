<?php

const D3_VARIANT_TAG = 'wielowariantowy';

function loadD3Demo(array $catalog): array
{
    $demo = json_decode(file_get_contents(__DIR__ . '/d3-demo.json'), true, 512, JSON_THROW_ON_ERROR);
    $products = array_column($catalog['products'], null, 'source_id');
    requireResult(count($demo['promotions']) >= 20 && count($demo['combinations']) >= 5, 'Incomplete D3 demo.');

    foreach ($demo['promotions'] as $id => $promotion) {
        $previous = $promotion['previous_reduction'] ?? 0;
        $discount = $promotion['discount_percent'];
        requireResult(
            isset($products[$id]) && is_int($discount) && $discount > 0 && $discount < 100 && $discount % 5 === 0
                && $previous >= 0 && $previous < 1,
            "Invalid D3 promotion for $id."
        );
    }
    foreach ($demo['combinations'] as $id => $quantities) {
        requireResult(isset($products[$id]) && count($quantities) >= 2, "Invalid D3 combinations for $id.");
        $variants = array_column($products[$id]['variants'], null, 'source_id');
        foreach ($quantities as $suffix => $quantity) {
            $variant = $variants["$id-variant-$suffix"] ?? null;
            requireResult(
                !empty($variant['attributes']) && isset($variant['price_gross']) && is_int($quantity) && $quantity >= 0 && $quantity <= 10,
                "Invalid D3 combination $id-variant-$suffix."
            );
        }
    }
    foreach ($demo['retired_promotions'] as $id) {
        requireResult(!isset($demo['promotions'][$id]), "D3 promotion for $id is both active and retired.");
    }

    return $demo;
}

function d3Attribute(Db $db, int $shop, string $groupName, string $value, array $languages): int
{
    $groupKey = sourceKey('d3', $groupName);
    $group = new AttributeGroup(mappedId($db, $shop, 'd3group', $groupKey));
    if (!$group->id) {
        $group->group_type = 'select';
        $group->name = $group->public_name = array_fill_keys($languages, $groupName);
        requireResult($group->add(), "Cannot create D3 attribute group $groupName.");
        saveMapping($db, $shop, 'd3group', $groupKey, (int) $group->id);
    }

    $key = sourceKey('d3', $groupName, $value);
    $attribute = new ProductAttribute(mappedId($db, $shop, 'd3attr', $key));
    if (!$attribute->id) {
        $attribute->id_attribute_group = (int) $group->id;
        $attribute->name = array_fill_keys($languages, $value);
        requireResult($attribute->add(), "Cannot create D3 attribute $groupName / $value.");
        saveMapping($db, $shop, 'd3attr', $key, (int) $attribute->id);
    }

    return (int) $attribute->id;
}

function configureD3Combinations(
    Db $db, int $shop, string $source, Product $product, array $entry, array $quantities, array $languages
): void {
    $variants = array_column($entry['variants'], null, 'source_id');
    $vat = 1 + ($entry['vat_rate'] ?? 0) / 100;
    foreach ($quantities as $suffix => $quantity) {
        $id = "{$entry['source_id']}-variant-$suffix";
        $variant = $variants[$id];
        $key = sourceKey($source, $id);
        $combination = new Combination(mappedId($db, $shop, 'd3combo', $key), null, $shop);
        $combination->id_product = (int) $product->id;
        $combination->price = round($variant['price_gross'] / $vat - (float) $product->price, 6);
        $combination->minimal_quantity = 1;
        // Choose a default on first import. Keep the shop's choice on subsequent imports.
        if (!$combination->id) {
            $combination->default_on = $product->hasCombinations() ? null : 1;
        }
        requireResult($combination->save(), "Cannot save combination $id.");
        saveMapping($db, $shop, 'd3combo', $key, (int) $combination->id);
        $attributes = [];
        foreach ($variant['attributes'] as $groupName => $value) {
            $attributes[] = d3Attribute($db, $shop, $groupName, $value, $languages);
        }
        requireResult($combination->setAttributes($attributes), "Cannot set attributes for $id.");
        StockAvailable::setQuantity($product->id, $combination->id, $quantity, $shop, false);
        requireResult(
            StockAvailable::getStockAvailableIdByProductId($product->id, $combination->id, $shop)
                && StockAvailable::getQuantityAvailableByProduct($product->id, $combination->id, $shop) === $quantity,
            "Cannot set stock for $id."
        );
    }
    Product::updateDefaultAttribute((int) $product->id);
}

function enableD3VariantChoices(Db $db, int $shop, int $featureId): void
{
    $key = 'layered_selection_feat_' . $featureId;
    $templates = $db->executeS('SELECT f.id_layered_filter, f.filters FROM `' . _DB_PREFIX_ . 'layered_filter` f'
        . ' INNER JOIN `' . _DB_PREFIX_ . 'layered_filter_shop` fs USING (id_layered_filter)'
        . ' WHERE fs.id_shop = ' . $shop);
    foreach ($templates as $row) {
        $settings = Tools::unSerialize($row['filters']);
        if (isset($settings['layered_selection_extras']) && !isset($settings[$key])) {
            $settings[$key] = ['filter_type' => 0, 'filter_show_limit' => 0];
            requireResult($db->update('layered_filter', ['filters' => pSQL(serialize($settings))],
                'id_layered_filter = ' . (int) $row['id_layered_filter']), 'Cannot add variants to the selections facet.');
        }
    }
}

function configureD3VariantFacet(Db $db, int $shop, array $products): void
{
    $languages = Language::getIDs(false, $shop);
    $feature = new Feature((int) Configuration::get('FISHING_D3_VARIANT_FEATURE'));
    if (!$feature->id) {
        $feature->name = array_fill_keys($languages, 'Warianty');
        requireResult($feature->add(), 'Cannot create the variant feature.');
        requireResult(Configuration::updateValue('FISHING_D3_VARIANT_FEATURE', $feature->id), 'Cannot save the variant feature.');
    }

    $value = new FeatureValue((int) Configuration::get('FISHING_D3_VARIANT_FEATURE_VALUE'));
    if (!$value->id) {
        $value->id_feature = (int) $feature->id;
        $value->custom = false;
        $value->value = array_fill_keys($languages, 'Dostępne warianty');
        requireResult($value->add(), 'Cannot create the variant feature value.');
        requireResult(Configuration::updateValue('FISHING_D3_VARIANT_FEATURE_VALUE', $value->id), 'Cannot save the variant feature value.');
    }
    foreach ($products as $id) {
        requireResult(Product::addFeatureProductImport($id, $feature->id, $value->id), "Cannot assign the variant feature to product $id.");
    }

    $filters = [
        'shop_list' => [$shop],
        'categories' => [],
        'controllers' => ['search'],
        'layered_selection_feat_' . $feature->id => ['filter_type' => 0, 'filter_show_limit' => 0],
    ];
    $templateId = (int) Configuration::get('FISHING_D3_SEARCH_FILTER_TEMPLATE');
    $module = Module::getInstanceByName('ps_facetedsearch');
    requireResult($module && $module->active, 'Activate faceted search before configuring the variant filter.');
    $template = $templateId ? $module->getFilterTemplate($templateId) : false;
    if ($template) {
        // Preserve any filters added to this search template in the back office.
        $filters = array_replace(Tools::unSerialize($template['filters']) ?: [], $filters);
        requireResult($db->update('layered_filter', ['filters' => pSQL(serialize($filters))], 'id_layered_filter = ' . $templateId),
            'Cannot update the variant filter template.');
    } else {
        requireResult($db->insert('layered_filter', [
            'name' => 'Warianty w wynikach wyszukiwania',
            'filters' => pSQL(serialize($filters)),
            'n_categories' => 0,
            'date_add' => date('Y-m-d H:i:s'),
        ]), 'Cannot save the variant filter template.');
        $templateId = (int) $db->Insert_ID();
        requireResult($db->insert('layered_filter_shop', ['id_layered_filter' => $templateId, 'id_shop' => $shop]),
            'Cannot associate the search template with the shop.');
        requireResult(Configuration::updateValue('FISHING_D3_SEARCH_FILTER_TEMPLATE', $templateId), 'Cannot save the search template ID.');
    }
    $templates = $db->executeS('SELECT f.id_layered_filter, f.filters FROM `' . _DB_PREFIX_ . 'layered_filter` f'
        . ' INNER JOIN `' . _DB_PREFIX_ . 'layered_filter_shop` fs USING (id_layered_filter)'
        . ' WHERE fs.id_shop = ' . $shop);
    foreach ($templates as $row) {
        $settings = Tools::unSerialize($row['filters']);
        if (isset($settings['layered_selection_subcategories'])) {
            unset($settings['layered_selection_subcategories']);
            requireResult($db->update('layered_filter', ['filters' => pSQL(serialize($settings))],
                'id_layered_filter = ' . (int) $row['id_layered_filter']), 'Cannot remove the category facet.');
        }
    }
    $featureId = (int) $feature->id;
    enableD3VariantChoices($db, $shop, $featureId);
    $module->buildLayeredCategories();
    requireResult($db->getValue('SELECT id_layered_category FROM `' . _DB_PREFIX_ . 'layered_category`'
        . " WHERE id_shop = $shop AND controller = 'search' AND type = 'id_feature' AND id_value = $featureId", false),
        'Cannot enable the native variant filter.');
}

function configureD3SaleNavigation(Db $db, int $shop, int $categoryId): void
{
    $menu = Module::getInstanceByName('ps_mainmenu');
    requireResult($menu && $menu->active, 'Activate the main menu before configuring the sale link.');
    $id = (int) Configuration::get('FISHING_D3_SALE_MENU_LINK');
    if (!$id || !$db->getValue('SELECT id_linksmenutop FROM `' . _DB_PREFIX_ . 'linksmenutop`'
        . " WHERE id_linksmenutop = $id AND id_shop = $shop")) {
        requireResult($db->insert('linksmenutop', ['new_window' => 0, 'id_shop' => $shop]), 'Cannot create the sale menu link.');
        $id = (int) $db->Insert_ID();
        requireResult($id && Configuration::updateValue('FISHING_D3_SALE_MENU_LINK', $id), 'Cannot save the sale menu link ID.');
    }
    $link = Context::getContext()->link ?? new Link();
    foreach (Language::getIDs(false, $shop) as $languageId) {
        requireResult($db->insert('linksmenutop_lang', [
            'id_linksmenutop' => $id,
            'id_shop' => $shop,
            'id_lang' => (int) $languageId,
            'label' => Language::getIsoById($languageId) === 'pl' ? 'Wyprzedaże' : 'Sale',
            'link' => pSQL($link->getPageLink('prices-drop', true, $languageId, null, false, $shop)),
        ], false, false, Db::ON_DUPLICATE_KEY), 'Cannot save the localized sale menu link.');
    }

    $items = array_filter(explode(',', (string) Configuration::get('MOD_BLOCKTOPMENU_ITEMS')));
    $saleItem = 'LNK' . $id;
    $items = array_map(static fn ($item) => $item === 'CAT' . $categoryId ? $saleItem : $item, $items);
    if (!in_array($saleItem, $items, true)) {
        $items[] = $saleItem;
    }
    requireResult(Configuration::updateValue('MOD_BLOCKTOPMENU_ITEMS', implode(',', array_unique($items))),
        'Cannot replace the imported sale category in the main menu.');

    // Keep source assignments and let old category URLs redirect to the live sales listing.
    $category = new Category($categoryId, null, $shop);
    if ($category->active) {
        $category->active = false;
        requireResult($category->update(), 'Cannot hide the imported sale category.');
    }
    $tree = Module::getInstanceByName('ps_categorytree');
    if ($tree && $tree->isRegisteredInHook('displayLeftColumn')) {
        requireResult($tree->unregisterHook('displayLeftColumn', [$shop]), 'Cannot remove the category tree from the filters sidebar.');
    }
    $menu->hookActionObjectCategoryUpdateAfter([]);
}

function configureD3SaleTranslations(Db $db): void
{
    $language = (int) Language::getIdByIso('pl');
    if (!$language) {
        return;
    }
    $changed = false;
    foreach (['ModulesFacetedsearchShop' => 'Discounted', 'ShopThemeCatalog' => 'Prices drop'] as $domain => $key) {
        $where = "id_lang = $language AND theme IS NULL AND domain = '" . pSQL($domain) . "' AND `key` = '" . pSQL($key) . "'";
        $existing = $db->getRow('SELECT id_translation, translation FROM `' . _DB_PREFIX_ . 'translation` WHERE ' . $where, false);
        if (!$existing) {
            requireResult($db->insert('translation', [
                'id_lang' => $language, 'key' => $key, 'translation' => 'Wyprzedaże', 'domain' => $domain,
            ]), "Cannot add the sale translation for $key.");
            $changed = true;
        } elseif ($existing['translation'] !== 'Wyprzedaże') {
            requireResult($db->update('translation', ['translation' => 'Wyprzedaże'],
                'id_translation = ' . (int) $existing['id_translation']), "Cannot update the sale translation for $key.");
            $changed = true;
        }
    }
    if ($changed) {
        $catalogues = glob(_PS_CACHE_DIR_ . 'translations/catalogue.pl-PL.*') ?: [];
        (new Symfony\Component\Filesystem\Filesystem())->remove($catalogues);
    }
}

function configureD3Merchandising(Db $db, int $shop, int $currency, array $catalog, array $demo, bool $refreshSearchIndex = false): int
{
    requireResult($db->execute(
        'CREATE TABLE IF NOT EXISTS `' . _DB_PREFIX_ . 'fishing_price_history` (
            id_shop INT UNSIGNED NOT NULL,
            id_product INT UNSIGNED NOT NULL,
            id_product_attribute INT UNSIGNED NOT NULL,
            id_currency INT UNSIGNED NOT NULL,
            valid_from DATETIME NOT NULL,
            valid_to DATETIME NOT NULL,
            price_tax_incl DECIMAL(20,6) UNSIGNED NOT NULL,
            price_tax_excl DECIMAL(20,6) UNSIGNED NOT NULL,
            PRIMARY KEY (id_shop, id_product, id_product_attribute, id_currency, valid_from)
        ) ENGINE=InnoDB'
    ), 'Cannot initialize D3 price history.');

    $products = array_column($catalog['products'], null, 'source_id');
    $source = $catalog['source']['base_url'];
    $saleCategory = mappedId($db, $shop, 'category', sourceKey($source, $demo['sale_category']));
    requireResult($saleCategory, 'Cannot find the imported sale category.');
    $variantProducts = [];
    foreach (array_keys($demo['combinations']) as $id) {
        $productId = mappedId($db, $shop, 'product', sourceKey($source, $id));
        requireResult($productId && Product::getDefaultAttribute($productId), "Cannot find D3 combinations for $id.");
        $variantProducts[] = $productId;
    }
    // SpecificPrice evaluates start times with minute precision.
    $start = new DateTimeImmutable(date('Y-m-d H:i:00'));
    $newProductDays = max(0, (int) Configuration::get('PS_NB_DAYS_NEW_PRODUCT'));
    $olderDate = $start->setTime(0, 0)->modify('-' . ($newProductDays + 1) . ' days')->format('Y-m-d H:i:s');
    transaction($db, static function () use ($db, $shop, $currency, $products, $source, $start, $demo, $variantProducts, $saleCategory, $olderDate) {
        foreach ($demo['retired_promotions'] as $id) {
            $key = sourceKey('d3', $source, $id);
            $ruleId = mappedId($db, $shop, 'd3price', $key);
            if ($ruleId) {
                $rule = new SpecificPrice($ruleId);
                requireResult(!$rule->id || $rule->delete(), "Cannot retire the D3 promotion for $id.");
                requireResult($db->delete('fishing_catalog_source',
                    "shop_id = $shop AND kind = 'd3price' AND source_key = '" . pSQL($key) . "'"),
                    "Cannot remove the retired promotion mapping for $id."
                );
            }
        }
        foreach ($demo['promotions'] as $id => $promotion) {
            $productId = mappedId($db, $shop, 'product', sourceKey($source, $id));
            requireResult($productId, "Cannot find D3 product $id.");
            if (!empty($promotion['older_product'])) {
                // PrestaShop calculates the New flag from date_add, including on filtered listings.
                $moreRecent = "id_product = $productId AND date_add > '" . pSQL($olderDate) . "'";
                requireResult($db->update('product', ['date_add' => $olderDate], $moreRecent)
                    && $db->update('product_shop', ['date_add' => $olderDate], "$moreRecent AND id_shop = $shop"),
                    "Cannot set the demo catalog age for $id.");
            }
            // The fixture discount uses the 30-day minimum. SpecificPrice uses the regular price.
            $historicalRatio = 1 - ($promotion['previous_reduction'] ?? 0);
            $reduction = round(1 - $historicalRatio * (1 - $promotion['discount_percent'] / 100), 6);
            $key = sourceKey('d3', $source, $id);
            $rule = new SpecificPrice(mappedId($db, $shop, 'd3price', $key));
            if ($rule->id) {
                if ($rule->reduction_type !== 'percentage' || (float) $rule->reduction !== $reduction) {
                    $rule->reduction = $reduction;
                    $rule->reduction_type = 'percentage';
                    requireResult($rule->update(), "Cannot update the D3 discount for $id.");
                }
                continue;
            }

            $entry = $products[$id];
            $prices = [0 => $entry['price_gross']];
            if (isset($demo['combinations'][$id])) {
                $prices = [];
                $variants = array_column($entry['variants'], null, 'source_id');
                foreach ($demo['combinations'][$id] as $suffix => $quantity) {
                    $variantId = "$id-variant-$suffix";
                    $combinationId = mappedId($db, $shop, 'd3combo', sourceKey($source, $variantId));
                    requireResult($combinationId, "Cannot find D3 combination $variantId.");
                    $prices[$combinationId] = $variants[$variantId]['price_gross'];
                }
            }
            foreach ($prices as $combinationId => $price) {
                seedD3PriceHistory($db, $shop, $currency, $productId, $combinationId, $entry, $price, $start, $promotion);
            }

            $rule->id_product = $productId;
            $rule->id_shop = $shop;
            $rule->id_currency = $currency;
            $rule->id_country = $rule->id_group = $rule->id_customer = $rule->id_cart = $rule->id_product_attribute = 0;
            $rule->price = -1;
            $rule->from_quantity = 1;
            $rule->reduction = $reduction;
            $rule->reduction_type = 'percentage';
            $rule->reduction_tax = 1;
            $rule->from = $start->format('Y-m-d H:i:s');
            $rule->to = '0000-00-00 00:00:00';
            requireResult($rule->add(), "Cannot add D3 promotion for $id.");
            saveMapping($db, $shop, 'd3price', $key, (int) $rule->id);
        }
        foreach ($variantProducts as $productId) {
            $tagsByLanguage = Tag::getProductTags($productId) ?: [];
            foreach (Language::getIDs(false, $shop) as $languageId) {
                if (!in_array(D3_VARIANT_TAG, $tagsByLanguage[$languageId] ?? [], true)) {
                    requireResult(Tag::addTags($languageId, $productId, [D3_VARIANT_TAG]), "Cannot tag product $productId.");
                }
            }
        }
        requireResult(Configuration::updateValue('FISHING_D3_SALE_CATEGORY', $saleCategory), 'Cannot configure the sale link.');
        requireResult(Configuration::updateValue('FISHING_D3_PRICE_HISTORY', true), 'Cannot enable D3 disclosures.');
    });
    configureD3VariantFacet($db, $shop, $variantProducts);
    configureD3SaleNavigation($db, $shop, $saleCategory);
    configureD3SaleTranslations($db);
    if ($refreshSearchIndex) {
        foreach ($variantProducts as $productId) {
            requireResult(Search::indexation(false, $productId), "Cannot reindex product $productId.");
        }
    }

    return count($demo['promotions']);
}

function seedD3PriceHistory(
    Db $db, int $shop, int $currency, int $product, int $combination, array $entry, float $price,
    DateTimeImmutable $start, array $promotion
): void {
    $periods = [[30, 0, 0]];
    if (isset($promotion['previous_reduction'])) {
        // The older, deeper reduction ends at the window boundary and must be excluded.
        $periods = [[40, 30, 0.25], [30, 20, 0], [20, 10, $promotion['previous_reduction']], [10, 0, 0]];
    }
    foreach ($periods as [$from, $to, $reduction]) {
        $gross = round($price * (1 - $reduction), 2);
        requireResult($db->insert('fishing_price_history', [
            'id_shop' => $shop,
            'id_product' => $product,
            'id_product_attribute' => $combination,
            'id_currency' => $currency,
            'valid_from' => $start->modify("-$from days")->format('Y-m-d H:i:s'),
            'valid_to' => $start->modify("-$to days")->format('Y-m-d H:i:s'),
            'price_tax_incl' => $gross,
            'price_tax_excl' => round($gross / (1 + ($entry['vat_rate'] ?? 0) / 100), 6),
        ]), "Cannot seed D3 price history for {$entry['source_id']}.");
    }
}
