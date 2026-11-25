<?php

use PrestaShop\PrestaShop\Adapter\ServiceLocator;
use PrestaShop\PrestaShop\Core\Image\ImageFormatConfiguration;

if (PHP_SAPI !== 'cli' || $argc !== 2) {
    exit(1);
}

$_SERVER['REQUEST_URI'] = '/';
require '/var/www/html/config/config.inc.php';

function requireResult($condition, string $message): void
{
    if (!$condition) {
        throw new RuntimeException($message);
    }
}

function transaction(Db $db, callable $save)
{
    requireResult($db->execute('START TRANSACTION'), 'Cannot start transaction.');
    try {
        $result = $save();
        requireResult($db->execute('COMMIT'), 'Cannot commit transaction.');
        return $result;
    } catch (Throwable $error) {
        $db->execute('ROLLBACK');
        throw $error;
    }
}

function sourceKey(string ...$parts): string
{
    return hash('sha256', json_encode($parts, JSON_THROW_ON_ERROR));
}

function mappedId(Db $db, int $shop, string $kind, string $key): int
{
    return (int) $db->getValue(
        'SELECT entity_id FROM `' . _DB_PREFIX_ . 'fishing_catalog_source`'
        . " WHERE shop_id = $shop AND kind = '" . pSQL($kind)
        . "' AND source_key = '" . pSQL($key) . "'",
        false
    );
}

function saveMapping(Db $db, int $shop, string $kind, string $key, int $id): void
{
    requireResult($db->insert('fishing_catalog_source', [
        'shop_id' => $shop,
        'kind' => pSQL($kind),
        'source_key' => pSQL($key),
        'entity_id' => $id,
    ], false, false, Db::ON_DUPLICATE_KEY), "Cannot save $kind mapping.");
}

function categoryImport(Db $db, int $shop, string $key, array $entry, int $parent, array $languages): int
{
    return transaction($db, function () use ($db, $shop, $key, $entry, $parent, $languages) {
        $category = new Category(mappedId($db, $shop, 'category', $key), null, $shop);
        $category->id_parent = $parent;
        $category->active = (bool) $entry['active'];
        $category->name = array_fill_keys($languages, $entry['name']);
        $category->link_rewrite = array_fill_keys(
            $languages,
            Tools::link_rewrite($entry['name']) ?: 'kategoria-' . substr($key, 0, 12)
        );
        requireResult($category->save(), 'Cannot save category.');
        saveMapping($db, $shop, 'category', $key, (int) $category->id);
        return (int) $category->id;
    });
}

function taxGroup(Db $db, int $shop, int $country, array $languages, float $rate): int
{
    $rateSql = number_format($rate, 3, '.', '');
    requireResult(abs((float) $rateSql - $rate) < 0.0000001, 'Unsupported VAT precision.');
    $prefix = _DB_PREFIX_;
    $existing = $db->getValue(
        "SELECT g.id_tax_rules_group FROM `{$prefix}tax_rules_group` g
        JOIN `{$prefix}tax_rules_group_shop` gs USING (id_tax_rules_group)
        JOIN `{$prefix}tax_rule` r USING (id_tax_rules_group)
        JOIN `{$prefix}tax` t USING (id_tax)
        WHERE gs.id_shop = $shop AND g.active = 1 AND g.deleted = 0
          AND t.active = 1 AND t.deleted = 0 AND t.rate = $rateSql
          AND r.id_country = $country AND r.id_state = 0
          AND r.zipcode_from IN ('', '0') AND r.zipcode_to IN ('', '0')
          AND NOT EXISTS (
              SELECT 1 FROM `{$prefix}tax_rule` other
              WHERE other.id_tax_rules_group = g.id_tax_rules_group
                AND other.id_country = $country AND other.id_tax_rule <> r.id_tax_rule
          )
        ORDER BY g.id_tax_rules_group",
        false
    );
    if ($existing) {
        return (int) $existing;
    }

    return transaction($db, function () use ($shop, $country, $languages, $rate, $rateSql) {
        $tax = new Tax();
        $tax->name = array_fill_keys($languages, "VAT PL $rateSql%");
        $tax->rate = $rate;
        $tax->active = true;
        requireResult($tax->add(), 'Cannot create tax.');

        $group = new TaxRulesGroup();
        $group->name = "Fishing Shop VAT PL $rateSql%";
        $group->active = true;
        requireResult($group->add() && $group->associateTo($shop), 'Cannot create tax group.');

        $rule = new TaxRule();
        $rule->id_tax_rules_group = (int) $group->id;
        $rule->id_tax = (int) $tax->id;
        $rule->id_country = $country;
        $rule->id_state = 0;
        $rule->zipcode_from = '0';
        $rule->zipcode_to = '0';
        $rule->behavior = 0;
        requireResult($rule->add(), 'Cannot create Polish tax rule.');
        return (int) $group->id;
    });
}

function checkVatRate(int $country, int $group, float $rate): int
{
    $address = new Address();
    $address->id_country = $country;
    $calculator = TaxManagerFactory::getManager($address, $group)->getTaxCalculator();
    requireResult(abs($calculator->getTotalRate() - $rate) < 0.0000001, 'Polish VAT rule does not apply the source rate.');
    return $group;
}

function productImport(
    Db $db, int $shop, string $key, array $entry, array $categories,
    int $defaultCategory, array $languages, int $taxGroup
): array {
    return transaction($db, function () use (
        $db, $shop, $key, $entry, $categories, $defaultCategory, $languages, $taxGroup
    ) {
        $product = new Product(mappedId($db, $shop, 'product', $key), false, null, $shop);
        $created = !$product->id;
        if ($created) {
            $product->active = false;
        }
        $product->id_shop_default = $shop;
        $product->id_category_default = $defaultCategory;
        $product->name = array_fill_keys($languages, $entry['name']);
        $description = nl2br(htmlspecialchars($entry['description'], ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8'));
        $product->description = array_fill_keys($languages, $description);
        $product->link_rewrite = array_fill_keys(
            $languages,
            Tools::link_rewrite($entry['name']) ?: 'produkt-' . substr($key, 0, 12)
        );
        $product->weight = $entry['weight_kg'] ?? 0;
        $product->id_tax_rules_group = $taxGroup;
        $product->price = round($entry['price_gross'] / (1 + ($entry['vat_rate'] ?? 0) / 100), 6);
        $product->available_for_order = true;
        $product->show_price = true;
        $product->visibility = 'both';
        $product->indexed = false;
        requireResult($product->save(), 'Cannot save product.');
        requireResult($product->updateCategories($categories), 'Cannot assign categories.');
        $savedCategories = array_map('intval', $product->getCategories());
        sort($savedCategories);
        sort($categories);
        requireResult($savedCategories === $categories, 'Saved category assignments differ from the export.');
        saveMapping($db, $shop, 'product', $key, (int) $product->id);
        return [$product, $created];
    });
}

function imageImport(
    Db $db, int $shop, int $productId, string $key, string $source,
    int $position, array $types, array $formats
): int {
    $size = getimagesize($source);
    requireResult(
        $size && $size[2] === IMAGETYPE_JPEG && max($size[0], $size[1]) >= 800
        && max($size[0], $size[1]) <= 1600 && filesize($source) <= 300000,
        'Invalid prepared JPEG.'
    );

    // Commit the image ID before writing files so a rerun can repair an interrupted upload.
    $image = transaction($db, function () use ($db, $shop, $productId, $key, $position) {
        $image = new Image(mappedId($db, $shop, 'image', $key), null, $shop);
        requireResult(!$image->id || (int) $image->id_product === $productId, 'Image mapping mismatch.');
        $image->id_product = $productId;
        $image->position = $position;
        requireResult($image->save(), 'Cannot save image record.');
        saveMapping($db, $shop, 'image', $key, (int) $image->id);
        return $image;
    });

    $path = $image->getPathForCreation();
    requireResult($path, 'Cannot determine image path.');
    $same = is_file("$path.jpg") && hash_file('sha256', "$path.jpg") === hash_file('sha256', $source);
    foreach ($types as $type) {
        foreach ($formats as $format) {
            $thumbnail = "$path-{$type['name']}.$format";
            if (!$same || !is_file($thumbnail) || filesize($thumbnail) === 0) {
                $temporary = "$thumbnail.import";
                requireResult(
                    ImageManager::resize($source, $temporary, $type['width'], $type['height'], $format, true)
                    && rename($temporary, $thumbnail),
                    'Cannot generate product thumbnail.'
                );
            }
        }
    }
    if (!$same) {
        requireResult(copy($source, "$path.jpg.import") && rename("$path.jpg.import", "$path.jpg"), 'Cannot save original JPEG.');
    }
    return (int) $image->id;
}

function removeDemoProducts(Db $db, int $shop): int
{
    // Stock PrestaShop 8.2.8 fashion fixtures, grouped by original manufacturer.
    $references = [
        'Studio Design' => [1, 3, 11, 12, 13, 14, 15, 16, 17],
        'Graphic Corner' => [5, 6, 7, 8, 9, 10, 18, 19, 20],
        '' => [21],
    ];
    $prefix = _DB_PREFIX_;
    $rows = $db->executeS(
        "SELECT p.id_product, p.reference, COALESCE(m.name, '') AS manufacturer, s.name AS supplier,
                EXISTS(SELECT 1 FROM `{$prefix}order_detail` o WHERE o.product_id = p.id_product) AS ordered
         FROM `{$prefix}product` p
         JOIN `{$prefix}product_shop` ps USING (id_product)
         JOIN `{$prefix}supplier` s USING (id_supplier)
         LEFT JOIN `{$prefix}manufacturer` m USING (id_manufacturer)
         WHERE ps.id_shop = $shop AND p.weight = 0.300000
           AND p.reference REGEXP '^demo_[0-9]+$'
           AND NOT EXISTS (SELECT 1 FROM `{$prefix}fishing_catalog_source` f
                           WHERE f.kind = 'product' AND f.entity_id = p.id_product)",
        true,
        false
    );
    requireResult(is_array($rows), 'Cannot check installer demo products.');
    $removed = 0;
    foreach ($rows as $row) {
        $number = (int) substr($row['reference'], 5);
        $supplier = in_array($number, [1, 3, 5, 6, 7], true) ? 'Fashion supplier' : 'Accessories supplier';
        if (
            $row['reference'] !== "demo_$number"
            || !in_array($number, $references[$row['manufacturer']] ?? [], true)
            || $row['supplier'] !== $supplier
        ) {
            continue;
        }
        if ($row['ordered']) {
            fwrite(STDERR, "Demo product {$row['reference']} preserved because it has an order.\n");
            continue;
        }
        requireResult((new Product((int) $row['id_product'], false, null, $shop))->delete(), "Cannot delete {$row['reference']}.");
        ++$removed;
    }
    return $removed;
}

function importCatalog(Db $db, string $directory): void
{
    $catalog = json_decode(file_get_contents("$directory/catalog.json"), true, 512, JSON_THROW_ON_ERROR);
    $context = Context::getContext();
    $shop = (int) Configuration::get('PS_SHOP_DEFAULT');
    Shop::setContext(Shop::CONTEXT_SHOP, $shop);
    $context->shop = new Shop($shop);
    $language = new Language((int) Configuration::get('PS_LANG_DEFAULT'));
    $context->language = $language;
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
        foreach (Language::getIDs() as $languageId) {
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
        requireResult($pln->add(), 'Cannot create PLN currency.');
        $plnId = (int) $pln->id;
    }
    if (!$pln->active) {
        $pln->active = true;
        requireResult($pln->update(), 'Cannot activate PLN currency.');
    }
    if (!$pln->isInstalled($pln->id, $shop)) {
        requireResult($pln->associateTo($shop), 'Cannot enable PLN for the default shop.');
    }
    if ((int) Configuration::get('PS_CURRENCY_DEFAULT') !== $plnId) {
        requireResult(
            Configuration::updateValue('PS_CURRENCY_DEFAULT', $plnId),
            'Cannot set PLN as the default store currency.'
        );
    }
    $context->currency = $pln;
    $country = (int) Country::getByIso('PL');
    $context->country = new Country($country);
    $languages = Language::getIDs(false, $shop);
    $home = (int) Configuration::get('PS_HOME_CATEGORY');
    requireResult($country && $home && $languages && Configuration::get('PS_TAX'), 'Polish shop configuration or taxes missing.');

    requireResult($db->execute(
        'CREATE TABLE IF NOT EXISTS `' . _DB_PREFIX_ . 'fishing_catalog_source` (
            shop_id INT UNSIGNED NOT NULL,
            kind VARCHAR(8) CHARACTER SET ascii NOT NULL,
            source_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
            entity_id INT UNSIGNED NOT NULL,
            PRIMARY KEY (shop_id, kind, source_key)
        ) ENGINE=InnoDB'
    ), 'Cannot initialize source mappings.');

    $source = $catalog['source']['base_url'];
    $categories = $depths = [];
    foreach ($catalog['categories'] as $entry) {
        $id = $entry['source_id'];
        $parent = $entry['parent_source_id'];
        try {
            $categories[$id] = categoryImport(
                $db, $shop, sourceKey($source, $id), $entry,
                $parent === null ? $home : $categories[$parent], $languages
            );
            $depths[$id] = $parent === null ? 1 : $depths[$parent] + 1;
        } catch (Throwable $error) {
            throw new RuntimeException("Category $id: " . $error->getMessage(), 0, $error);
        }
    }

    $types = ImageType::getImagesTypes('products');
    $formats = ServiceLocator::get(ImageFormatConfiguration::class)->getGenerationFormats();
    $taxGroups = [];
    $counts = array_fill_keys(['created', 'updated', 'failed', 'images', 'without_weight', 'without_vat', 'out_of_stock'], 0);
    foreach ($catalog['products'] as $entry) {
        $id = $entry['source_id'];
        try {
            $rate = $entry['vat_rate'] ?? null;
            $group = 0;
            if ($rate !== null && $rate > 0) {
                $group = $taxGroups[(string) $rate] ??= checkVatRate(
                    $country, taxGroup($db, $shop, $country, $languages, $rate), $rate
                );
            }
            $assigned = $entry['category_ids'];
            usort($assigned, static fn ($a, $b) => $depths[$b] <=> $depths[$a]);
            $categoryIds = array_map(static fn ($category) => $categories[$category], $assigned);
            [$product, $created] = productImport(
                $db, $shop, sourceKey($source, $id), $entry, $categoryIds, $categoryIds[0], $languages, $group
            );

            $productId = (int) $product->id;
            $images = [];
            foreach ($entry['prepared_images'] as $index => $image) {
                $images[] = imageImport(
                    $db, $shop, $productId, sourceKey($source, $id, $image['source_url']),
                    "$directory/images/{$image['file']}", $index + 1, $types, $formats
                );
            }
            requireResult($images, 'Product has no usable image.');
            transaction($db, static function () use ($shop, $product, $productId, $images, $entry) {
                if ((int) (Image::getCover($productId)['id_image'] ?? 0) !== $images[0]) {
                    requireResult(Image::deleteCover($productId), 'Cannot clear the previous cover.');
                    $cover = new Image($images[0], null, $shop);
                    $cover->cover = true;
                    requireResult($cover->update(), 'Cannot set cover image.');
                }
                StockAvailable::setProductOutOfStock($productId, 0, $shop);
                StockAvailable::setQuantity($productId, 0, $entry['quantity'], $shop, false);
                requireResult(
                    StockAvailable::getStockAvailableIdByProductId($productId, 0, $shop)
                    && (int) StockAvailable::getQuantityAvailableByProduct($productId, 0, $shop) === $entry['quantity']
                    && (int) StockAvailable::outOfStock($productId, $shop) === 0,
                    'Cannot set stock quantity or policy.'
                );
                if (!$product->active) {
                    $product->active = true;
                    requireResult($product->update(), 'Cannot activate product.');
                }
            });
            ++$counts[$created ? 'created' : 'updated'];
            $counts['images'] += count($images);
            $counts['without_weight'] += (int) !isset($entry['weight_kg']);
            $counts['without_vat'] += (int) ($rate === null);
            $counts['out_of_stock'] += (int) ($entry['quantity'] === 0);
        } catch (Throwable $error) {
            ++$counts['failed'];
            fwrite(STDERR, "Product $id: {$error->getMessage()}\n");
        }
    }

    $counts['categories'] = count($categories);
    $counts['demo_removed'] = 0;
    if (!$counts['failed']) {
        $counts['demo_removed'] = removeDemoProducts($db, $shop);
    }
    echo json_encode($counts, JSON_THROW_ON_ERROR) . PHP_EOL;
    requireResult(Search::indexation(false), 'Cannot update the product search index.');
    requireResult(!$counts['failed'], 'One or more products failed. Rerun after correcting the reported errors.');
}

try {
    $db = Db::getInstance();
    $lock = pSQL('fishing-catalog:' . substr(hash('sha256', _DB_NAME_ . ':' . _DB_PREFIX_), 0, 40));
    requireResult((int) $db->getValue("SELECT GET_LOCK('$lock', 0)", false) === 1, 'Another catalog import is running.');
    try {
        importCatalog($db, $argv[1]);
    } finally {
        $db->getValue("SELECT RELEASE_LOCK('$lock')", false);
    }
} catch (Throwable $error) {
    fwrite(STDERR, 'Catalog initialization failed: ' . $error->getMessage() . PHP_EOL);
    exit(1);
}
