const { randomUUID } = require('node:crypto');
const { test, expect } = require('@playwright/test');
const { products } = require('../scraper-results/products.json');

const importedNames = new Set(products.map(({ name }) => name.replace(/\s+/g, ' ').trim()));
const mailpit = process.env.MAILPIT_URL || 'http://localhost:8025';

async function assertImportedListing(links) {
  await expect(links.first()).toBeVisible();
  const names = await links.allTextContents();
  expect(names.every(name => {
    const label = name.replace(/\s+/g, ' ').trim();
    const prefix = label.replace(/(?:\.\.\.|…)$/, '');
    return importedNames.has(label) || (prefix !== label && prefix.length >= 12 &&
      [...importedNames].some(imported => imported.startsWith(prefix)));
  })).toBe(true);
}

async function assertMail(request, email, subject, content) {
  await expect.poll(async () => {
    const search = await request.get(new URL('/api/v1/search', mailpit).href, {
      params: { query: `to:${email}` },
    });
    expect(search.ok()).toBe(true);
    const { messages } = await search.json();
    const match = messages?.find(message =>
      message.Subject === `[Fishing Shop] ${subject}` &&
      message.To.some(recipient => recipient.Address === email));
    if (!match) return '';
    const message = await request.get(new URL(`/api/v1/message/${match.ID}`, mailpit).href);
    expect(message.ok()).toBe(true);
    return (await message.json()).Text;
  }, { timeout: 20_000 }).toContain(content);
}

test('Polski katalog, menu, wyszukiwarka, stopka i CMS', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('html')).toHaveAttribute('lang', /^pl(?:-|$)/i);
  await expect(page.getByRole('complementary', { name: 'Informacja o plikach cookies' }))
    .toContainText('Używamy niezbędnych plików cookies');

  const footer = page.locator('#footer');
  for (const [title, fragment] of [
    ['O sklepie', 'wędkarstwu muchowemu'],
    ['Regulamin', 'Zamówienia służą do sprawdzenia procesu zakupowego'],
    ['Polityka prywatności', 'Wiadomości są przechwytywane'],
    ['Dostawa', 'powyżej 50 kg'],
    ['Formy płatności', 'tradycyjny przelew bankowy'],
  ]) {
    await footer.getByRole('link', { name: title, exact: true }).first().click();
    await expect(page.getByRole('heading', { name: title, exact: true })).toBeVisible();
    await expect(page.locator('#content')).toContainText(fragment);
  }

  await page.goto('/');
  const homeProducts = page.locator('.featured-products .product-title a');
  await assertImportedListing(homeProducts);
  const menu = page.locator('#_desktop_top_menu');
  await expect(menu.getByRole('link', { name: 'O sklepie', exact: true })).toBeVisible();
  await menu.getByRole('link', { name: 'Wędki muchowe', exact: true }).hover();
  const populatedCategory = menu.getByRole('link', { name: 'Wędki muchowe Orvis', exact: true });
  await expect(populatedCategory).toBeVisible();
  await populatedCategory.click();
  const categoryProducts = page.locator('#products .product-title a');
  await assertImportedListing(categoryProducts);
  await categoryProducts.first().click();
  const productPath = new URL(page.url()).pathname;
  const productName = (await page.locator('h1').textContent()).replace(/\s+/g, ' ').trim();
  expect(importedNames.has(productName)).toBe(true);
  await expect(page.locator('.current-price')).toContainText('zł');
  const cover = page.locator('.product-cover img.js-qv-product-cover:visible');
  await expect(cover).toBeVisible();
  await expect.poll(() => cover.evaluate(img => img.naturalWidth)).toBeGreaterThan(0);

  const search = page.locator('#search_widget input[name="s"]');
  // The name index ignores very short words and punctuation.
  const words = productName.match(/[\p{L}\p{N}]{4,}/gu) || [];
  expect(words.length).toBeGreaterThan(0);
  await search.fill(words.join(' '));
  await search.press('Enter');
  await expect(page.locator('body#search')).toBeVisible();
  await expect.poll(() => page.locator('#products .product-title a')
    .evaluateAll(links => links.map(link => new URL(link.href).pathname))).toContain(productPath);
});

test('Rejestracja, logowanie, koszyk, pobranie i historia zamówienia', async ({ page, request }) => {
  const email = `fishing-${randomUUID()}@example.test`;
  const password = 'FishingTest_123!';
  await page.goto('/');
  const account = page.locator('#_desktop_user_info');
  await account.locator('a').click();
  await page.locator('.no-account a').click();
  const registration = page.locator('#customer-form');
  await registration.locator('[name="firstname"]').fill('Łukasz');
  await registration.locator('[name="lastname"]').fill('Żak');
  await registration.locator('[name="email"]').fill(email);
  await registration.locator('[name="password"]').fill(password);
  for (const checkbox of await registration.locator('input[type="checkbox"][required]').all()) {
    await checkbox.check();
  }
  await registration.locator('button[type="submit"]').click();
  await expect(account.locator('a.account')).toContainText('Łukasz Żak');
  await assertMail(request, email, 'Witaj w Fishing Shop!', 'Łukasz');

  await account.locator('a.logout').click();
  await expect(account.locator('a.account')).toHaveCount(0);
  await account.locator('a').click();
  const login = page.locator('#login-form');
  await login.locator('[name="email"]').fill(email);
  await login.locator('[name="password"]').fill(password);
  await login.locator('button[type="submit"]').click();
  await expect(account.locator('a.account')).toContainText('Łukasz Żak');

  await page.goto('/');
  const cards = page.locator('.featured-products .product-title a');
  await assertImportedListing(cards);
  const candidates = await cards.evaluateAll(links => links.map(link => link.href));
  const add = page.locator('button[data-button-action="add-to-cart"]');
  let chosen;
  for (const candidate of candidates) {
    await page.goto(candidate);
    await expect(add).toBeVisible();
    const price = Number(await page.locator('.current-price-value').getAttribute('content'));
    if (await add.isEnabled() && price > 0 && price <= 2000) {
      chosen = (await page.locator('h1').textContent()).replace(/\s+/g, ' ').trim();
      break;
    }
  }
  expect(chosen, 'Na stronie głównej musi być dostępny produkt w cenie do 2 000 zł').toBeTruthy();
  await add.click();
  const modal = page.locator('#blockcart-modal');
  await expect(modal).toContainText(chosen);
  await modal.locator('.cart-content-btn a').click();
  await expect(page.locator('.cart-item')).toHaveCount(1);
  await expect(page.locator('.cart-item')).toContainText(chosen);
  await expect(page.locator('.cart-item input[name="product-quantity-spin"]')).toHaveValue('1');
  await page.locator('.checkout a.btn').click();

  const address = page.locator('#checkout-addresses-step');
  const alias = address.locator('[name="alias"]:visible');
  if (await alias.count()) await alias.fill('Dom');
  await address.locator('[name="address1"]').fill('ul. Łąkowa 10');
  await address.locator('[name="postcode"]').fill('80-769');
  await address.locator('[name="city"]').fill('Gdańsk');
  await expect(address.locator('select[name="id_country"] option:checked')).toContainText('Polska');
  await address.locator('[name="confirm-addresses"]').click();

  const shipping = page.locator('#checkout-delivery-step');
  const options = shipping.locator('.delivery-option');
  await expect(options).toHaveCount(2);
  const standard = options.filter({ hasText: 'Przesyłka standardowa' });
  await expect(standard).toContainText(/16[,.]90\s*zł/);
  await expect(options.filter({ hasText: 'Przesyłka ekspresowa' })).toContainText(/24[,.]90\s*zł/);
  await standard.getByRole('radio').check();
  await shipping.locator('[name="confirmDeliveryOption"]').click();

  const payment = page.locator('#checkout-payment-step');
  await expect(payment.locator('input[name="payment-option"]')).toHaveCount(2);
  const transfer = payment.locator('.payment-option:has([data-module-name="ps_wirepayment"])');
  const deliveryPayment = payment.locator('.payment-option:has([data-module-name="ps_cashondelivery"])');
  await expect(transfer).toContainText(/przelew/i);
  await expect(deliveryPayment).toContainText(/przy odbiorze/i);
  const cod = deliveryPayment.getByRole('radio');
  await cod.check();
  await expect(cod).toBeChecked();
  for (const checkbox of await payment.locator('#conditions-to-approve input[required]').all()) {
    await checkbox.check();
  }
  await expect(payment.locator('#conditions-to-approve').getByRole('link', {
    name: 'warunkami świadczenia usług',
  })).toHaveAttribute('href', /-regulamin(?:[?#]|$)/);
  await payment.locator('#payment-confirmation button[type="submit"]').click();

  const order = page.locator('#order-details');
  await expect(order).toContainText('Przesyłka standardowa');
  const reference = (await order.locator('#order-reference-value').innerText()).split(':').at(-1).trim();
  expect(reference).toMatch(/^[A-Z0-9]+$/);
  await assertMail(request, email, 'Potwierdzenie zamówienia', reference);
  await account.locator('a.account').click();
  await page.locator('#history-link').click();
  const orderRow = page.locator('table tr').filter({ hasText: reference });
  await expect(orderRow).toBeVisible();
  await expect(orderRow).toContainText(/przy odbiorze/i);
  await expect(orderRow.locator('.label-pill')).toHaveText(/\S/);
});
