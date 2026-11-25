<?php

if (!defined('_PS_VERSION_')) {
    exit;
}

class FishingStorefront extends Module
{
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
        foreach (['displayFooterBefore', 'actionFilterDeliveryOptionList', 'actionFrontControllerInitAfter', 'actionEmailSendBefore'] as $hook) {
            if (!$this->isRegisteredInHook($hook) && !$this->registerHook($hook)) {
                return false;
            }
        }

        return true;
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
