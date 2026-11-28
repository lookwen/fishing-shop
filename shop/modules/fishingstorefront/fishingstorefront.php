<?php

if (!defined('_PS_VERSION_')) {
    exit;
}

class FishingStorefront extends Module
{
    private array $lowestPrices = [];

    public function __construct()
    {
        $this->name = 'fishingstorefront';
        $this->version = '1.0.0';
        $this->author = 'Fishing Shop';
        parent::__construct();
        $this->displayName = 'Fishing Shop';
    }

    public function install()
    {
        return parent::install() && $this->registerStorefrontHooks();
    }

    public function registerStorefrontHooks(): bool
    {
        foreach (['displayHome', 'actionFrontControllerSetMedia', 'displayHeaderCategory', 'actionProductSearchProviderRunQueryBefore'] as $hook) {
            if ($this->isRegisteredInHook($hook) && !$this->unregisterHook($hook)) {
                return false;
            }
        }
        foreach ([
            'displayFooterBefore', 'actionFilterDeliveryOptionList', 'actionFrontControllerInitAfter', 'actionEmailSendBefore',
            'actionPresentProduct', 'actionPresentProductListing', 'displayProductPriceBlock',
            'overrideLayoutTemplate', 'actionOutputHTMLBefore', 'actionProductSearchProviderRunQueryAfter',
        ] as $hook) {
            if (!$this->isRegisteredInHook($hook) && !$this->registerHook($hook)) {
                return false;
            }
        }
        if (!$this->isRegisteredInHook('displayLeftColumn')) {
            if (!$this->registerHook('displayLeftColumn')) {
                return false;
            }
            $sidebar = (int) Hook::getIdByName('displayLeftColumn');
            if ($this->getPosition($sidebar) > 1 && !$this->updatePosition($sidebar, 0, 1)) {
                return false;
            }
        }

        return true;
    }

    public function hookActionPresentProductListing($params): void
    {
        $this->hookActionPresentProduct($params);
    }

    public function hookActionPresentProduct($params): void
    {
        $product = $params['presentedProduct'];
        $start = $product['specific_prices']['from'] ?? '';
        if (!$product['has_discount'] || !Validate::isDate($start) || $start === '0000-00-00 00:00:00'
            || !Configuration::get('FISHING_D3_PRICE_HISTORY')) {
            return;
        }

        $shop = (int) $this->context->shop->id;
        $currency = $this->context->currency;
        $productId = (int) $product['id_product'];
        $combination = (int) $product['id_product_attribute'];
        $priceColumn = (new TaxConfiguration())->includeTaxes() ? 'price_tax_incl' : 'price_tax_excl';
        $key = "$shop:$currency->id:$productId:$combination:$priceColumn:$start";
        if (!array_key_exists($key, $this->lowestPrices)) {
            $window = (new DateTimeImmutable($start))->modify('-30 days')->format('Y-m-d H:i:s');
            $lowest = Db::getInstance()->getValue('SELECT MIN(' . $priceColumn . ') FROM `' . _DB_PREFIX_ . 'fishing_price_history`'
                . " WHERE id_shop = $shop AND id_product = $productId AND id_product_attribute = $combination"
                . ' AND id_currency = ' . (int) $currency->id
                . " AND valid_from < '" . pSQL($start) . "' AND valid_to > '" . pSQL($window) . "'");
            $this->lowestPrices[$key] = is_numeric($lowest) ? (float) $lowest : null;
        }

        $lowest = $this->lowestPrices[$key];
        if ($lowest === null) {
            return;
        }

        $locale = $this->context->getCurrentLocale();
        $product['fishing_lowest_price'] = $locale->formatPrice($lowest, $currency->iso_code);
        if ($product['discount_type'] === 'percentage' && $lowest > (float) $product['price_amount']) {
            // Keep PrestaShop's transaction price and use the historical minimum in the discount claim.
            $percent = 100 * ($lowest - (float) $product['price_amount']) / $lowest;
            $absolute = $locale->formatNumber(round($percent, 2)) . '%';
            $flags = $product['flags'];
            if (isset($flags['discount'])) {
                $flags['discount']['label'] = '-' . $absolute;
                $product->offsetSet('flags', $flags, true);
            }
            $product->offsetSet('discount_percentage', '-' . $absolute, true);
            $product->offsetSet('discount_percentage_absolute', $absolute, true);
        }
    }

    public function hookDisplayProductPriceBlock($params): string
    {
        if ($params['type'] === 'before_price' && !empty($params['product']['id_product_attribute'])) {
            return '<div class="fishing-variant-note text-muted"><small>Dostępne warianty</small></div>';
        }

        // Classic calls these beside the price on product pages, cards and cart lines.
        if (!in_array($params['type'], ['after_price', 'unit_price'], true)
            || empty($params['product']['fishing_lowest_price'])) {
            return '';
        }

        $this->context->smarty->assign('fishing_lowest_price', $params['product']['fishing_lowest_price']);

        return $this->fetch('module:fishingstorefront/lowest-price.tpl');
    }

    public function hookActionProductSearchProviderRunQueryAfter($params): void
    {
        $collection = $params['result']->getFacetCollection();
        $featureId = (int) Configuration::get('FISHING_D3_VARIANT_FEATURE');
        if (!$collection || !$featureId) {
            return;
        }

        $facets = $collection->getFacets();
        $selections = null;
        $variantIndex = null;
        foreach ($facets as $index => $facet) {
            if ($facet->getType() === 'extras') {
                $selections = $facet;
            } elseif ($facet->getType() === 'feature' && (int) $facet->getProperty('id_feature') === $featureId) {
                $variantIndex = $index;
            }
        }
        if (!$selections || $variantIndex === null) {
            return;
        }

        $variants = $facets[$variantIndex];
        // Faceted Search already generated each filter's URL using its original feature group.
        foreach ($variants->getFilters() as $filter) {
            if ($filter->isActive() || ($variants->isDisplayed() && $filter->isDisplayed())) {
                $selections->addFilter($filter->setDisplayed(true));
                $selections->setDisplayed(true);
            }
        }
        unset($facets[$variantIndex]);
        $collection->setFacets(array_values($facets));
    }

    public function hookOverrideLayoutTemplate($params): string
    {
        if ($params['entity'] !== 'search' || $params['content_only'] || !Configuration::get('FISHING_D3_VARIANT_FEATURE')) {
            return '';
        }
        return $this->getLocalPath() . 'layout-left-column.tpl';
    }

    public function hookDisplayLeftColumn($params): string
    {
        if (!$this->context->controller instanceof ProductListingFrontController) {
            return '';
        }

        $this->context->smarty->assign('fishing_catalog_url', $this->getCatalogUrl());

        return $this->fetch('module:fishingstorefront/catalog-sidebar-link.tpl');
    }

    public function hookActionOutputHTMLBefore($params): void
    {
        if (!$this->context->controller instanceof IndexController) {
            return;
        }

        // Classic's featured and sale widgets share the link class but have different destinations.
        $link = $this->context->link;
        $featuredUrl = $link->getCategoryLink((int) Configuration::get('HOME_FEATURED_CAT'));
        $catalogUrl = $this->getCatalogUrl();
        $saleUrl = $link->getPageLink('prices-drop', true);
        $polish = $this->context->language->iso_code === 'pl';
        $params['html'] = preg_replace_callback(
            '~<a\b[^>]*\bclass="[^"]*\ball-product-link\b[^"]*"[^>]*>.*?</a>~is',
            static function (array $matches) use ($featuredUrl, $catalogUrl, $saleUrl, $polish): string {
                $anchor = $matches[0];
                if (!preg_match('~\bhref="([^"]*)"~i', $anchor, $href, PREG_OFFSET_CAPTURE)) {
                    return $anchor;
                }
                [$value, $offset] = $href[1];
                $destination = html_entity_decode($value, ENT_QUOTES, 'UTF-8');
                if ($destination === $featuredUrl) {
                    return substr_replace($anchor, htmlspecialchars($catalogUrl, ENT_QUOTES, 'UTF-8'), $offset, strlen($value));
                }
                if ($polish && $destination === $saleUrl) {
                    return preg_replace('~(?<=>)[^<]+(?=<i\b)~i', 'Zobacz wyprzedaże ', $anchor, 1) ?? $anchor;
                }

                return $anchor;
            },
            $params['html']
        ) ?? $params['html'];
    }

    private function getCatalogUrl(): string
    {
        return $this->context->link->getCategoryLink((int) Configuration::get('PS_HOME_CATEGORY'));
    }

    public function hookDisplayFooterBefore($params)
    {
        $this->context->smarty->assign('fishing_privacy_url', $this->context->link->getCMSLink(
            (int) Configuration::get('FISHING_CMS_PRIVACY')
        ));

        return $this->fetch('module:fishingstorefront/cookies.tpl');
    }

    public function hookActionFilterDeliveryOptionList($params)
    {
        if ($this->isOverweight($params['cart'])) {
            $params['delivery_option_list'] = [];
        }
    }

    public function hookActionEmailSendBefore($params)
    {
        $subjects = [
            'account' => 'Witaj w Fishing Shop!',
            'order_conf' => 'Potwierdzenie zamówienia',
            'bankwire' => 'Instrukcja przelewu bankowego',
        ];
        $template = $params['template'];
        if (isset($subjects[$template]) && Language::getIsoById((int) $params['idLang']) === 'pl') {
            $params['templatePath'] = $this->getLocalPath() . 'mails/';
            $params['subject'] = $subjects[$template];
        }
    }

    public function hookActionFrontControllerInitAfter($params)
    {
        $controller = $params['controller'];
        $saleCategory = (int) Configuration::get('FISHING_D3_SALE_CATEGORY');
        if ($controller instanceof CategoryController && $saleCategory && (int) Tools::getValue('id_category') === $saleCategory) {
            Tools::redirect($this->context->link->getPageLink('prices-drop', true));
        }
        // A cart may become overweight after the payment page has already loaded.
        if (($controller instanceof Ps_CashondeliveryValidationModuleFrontController
                || $controller instanceof Ps_WirepaymentValidationModuleFrontController)
            && $this->isOverweight($this->context->cart)) {
            $controller->errors[] = 'Dostawa jest niedostępna, ponieważ koszyk przekracza 50 kg.';
            $controller->redirectWithNotifications($this->context->link->getPageLink('cart', true, null, ['action' => 'show']));
        }
    }

    private function isOverweight(Cart $cart): bool
    {
        // Product and combination weights are stored to six decimal places.
        return round((float) $cart->getTotalWeight(), 6) > 50;
    }
}
