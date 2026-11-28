const { randomInt, randomUUID } = require('node:crypto');
const { readFile } = require('node:fs/promises');
const { test, expect } = require('@playwright/test');

const productLinks = '#products .product-title a';

async function listingUrls(page) {
  const links = page.locator(productLinks);
  await expect(links.first()).toBeVisible();
  return links.evaluateAll(anchors => anchors.map(anchor => anchor.href));
}

async function purchasableProduct(page, url, quantity, cart) {
  await page.goto(url);
  const details = JSON.parse(await page.locator('#product-details').getAttribute('data-product'));
  const name = (await page.locator('h1').textContent()).replace(/\s+/g, ' ').trim();
  if (cart.has(name) || details.quantity < quantity || details.minimal_quantity > quantity) return;
  if (await page.locator('button[data-button-action="add-to-cart"]').isEnabled()) return name;
}

async function addProduct(page, cart, name, quantity) {
  await page.locator('#quantity_wanted').fill(String(quantity));
  await page.locator('button[data-button-action="add-to-cart"]').click();
  const modal = page.locator('#blockcart-modal');
  await expect(modal.locator('.product-name')).toHaveText(name);
  cart.set(name, quantity);
}

function cartRow(page, name) {
  return page.locator('.cart-item').filter({ has: page.getByRole('link', { name, exact: true }) });
}

async function assertCart(page, cart) {
  await expect(page.locator('.cart-item')).toHaveCount(cart.size);
  for (const [name, quantity] of cart) {
    await expect(cartRow(page, name).locator('input[name="product-quantity-spin"]'))
      .toHaveValue(String(quantity));
  }
}

test('Zakup od koszyka do faktury VAT', async ({ page }, testInfo) => {
  const email = `fishing-${randomUUID()}@example.test`;
  const password = 'FishingTest_123!';
  const account = page.locator('#_desktop_user_info');
  const cart = new Map();
  const orderNames = new Map();
  const carrier = 'Przesyłka standardowa';

  for (const [parent, category] of [
    ['Linki muchowe', 'Linki pływające'],
    ['Akcesoria wędkarskie', 'Pudełka na muchy'],
  ]) {
    await test.step(`Dodanie 5 produktów z kategorii „${category}”`, async () => {
      await page.goto('./');
      const menu = page.locator('#_desktop_top_menu');
      await menu.getByRole('link', { name: parent, exact: true }).hover();
      await menu.getByRole('link', { name: category, exact: true }).click();
      await expect(page.getByRole('heading', { name: category, exact: true })).toBeVisible();

      const quantities = [1, 2, 3, 1, 2];
      let added = 0;
      while (added < quantities.length) {
        const urls = await listingUrls(page);
        const next = await page.locator('.pagination a[rel="next"]').evaluateAll(
          links => links[0]?.href,
        );
        for (const url of urls) {
          const quantity = quantities[added];
          const name = await purchasableProduct(page, url, quantity, cart);
          if (!name) continue;
          await addProduct(page, cart, name, quantity);
          added += 1;
          if (added === quantities.length) break;
        }
        if (added === quantities.length || !next) break;
        await page.goto(next);
      }
      expect(added, `Liczba dostępnych produktów w kategorii „${category}”`).toBe(5);
      await page.locator('#blockcart-modal .cart-content-btn a').click();
      await assertCart(page, cart);
    });
  }

  await test.step('Wyszukanie po nazwie i dodanie losowego produktu', async () => {
    const term = 'Wędka muchowa Orvis Helios';
    const search = page.locator('#search_widget input[name="s"]');
    await search.fill(term);
    await search.press('Enter');
    await expect(page.locator('body#search')).toBeVisible();
    await expect(search).toHaveValue(term);
    await expect(page.locator(productLinks).filter({ hasText: term }).first()).toBeVisible();
    const results = [...new Set(await listingUrls(page))];

    // Draw without replacement so every eligible result has the same chance of being selected.
    let selected;
    while (results.length && !selected) {
      const [url] = results.splice(randomInt(results.length), 1);
      selected = await purchasableProduct(page, url, 1, cart);
    }
    expect(selected, 'Dostępny produkt z wyników wyszukiwania spoza koszyka').toBeTruthy();
    await addProduct(page, cart, selected, 1);
    await page.locator('#blockcart-modal .cart-content-btn a').click();
    await expect(page.locator('.cart-item')).toHaveCount(11);
    await assertCart(page, cart);
  });

  await test.step('Usunięcie 3 pozycji z koszyka', async () => {
    for (const name of [...cart.keys()].slice(0, 3)) {
      const row = cartRow(page, name);
      await row.locator('[data-link-action="delete-from-cart"]').click();
      cart.delete(name);
      await expect(row).toHaveCount(0);
      await expect(page.locator('.cart-item')).toHaveCount(cart.size);
    }
    await expect(page.locator('.cart-item')).toHaveCount(8);
    await assertCart(page, cart);
  });

  await test.step('Rejestracja nowego klienta', async () => {
    await account.getByRole('link').click();
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
  });

  await test.step('Przejście do zamówienia i podanie adresu dostawy', async () => {
    await page.locator('#_desktop_cart a').click();
    await assertCart(page, cart);
    for (const name of cart.keys()) {
      const attributes = await cartRow(page, name).locator('.product-line-info:has(> .label + .value)')
        .evaluateAll(rows => rows.map(row => {
          const label = row.querySelector('.label').textContent.trim();
          const value = row.querySelector('.value').textContent.trim();
          return `${label} ${value}`;
        }));
      orderNames.set(name, attributes.length ? `${name} (${attributes.join(' - ')})` : name);
    }
    await page.locator('.checkout a.btn').click();

    const address = page.locator('#checkout-addresses-step');
    await expect(address).toHaveClass(/(?:^|\s)-current(?:\s|$)/);
    const alias = address.locator('[name="alias"]:visible');
    if (await alias.count()) await alias.fill('Dom');
    await address.locator('[name="address1"]').fill('ul. Łąkowa 10');
    await address.locator('[name="postcode"]').fill('80-769');
    await address.locator('[name="city"]').fill('Gdańsk');
    await expect(address.locator('select[name="id_country"] option:checked')).toContainText('Polska');
    await address.locator('[name="confirm-addresses"]').click();
    await expect(address).toHaveClass(/-complete\b/);
  });

  await test.step('Wybór przewoźnika', async () => {
    const shipping = page.locator('#checkout-delivery-step');
    const options = shipping.locator('.delivery-option');
    await expect(options).toHaveCount(2);
    await expect(options.filter({ hasText: 'Przesyłka ekspresowa' })).toBeVisible();
    const radio = options.filter({ hasText: carrier }).getByRole('radio');
    await radio.check();
    await expect(radio).toBeChecked();
    await shipping.locator('[name="confirmDeliveryOption"]').click();
    await expect(shipping).toHaveClass(/-complete\b/);
  });

  const payment = page.locator('#checkout-payment-step');
  await test.step('Wybór płatności przy odbiorze', async () => {
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
      await expect(checkbox).toBeChecked();
    }
    await expect(payment.locator('#conditions-to-approve').getByRole('link', {
      name: 'warunkami świadczenia usług',
    })).toHaveAttribute('href', /-regulamin(?:[?#]|$)/);
  });

  const reference = await test.step('Zatwierdzenie zamówienia i sprawdzenie pozycji', async () => {
    await payment.locator('#payment-confirmation button[type="submit"]').click();
    await expect(page.locator('body#order-confirmation')).toBeVisible();
    const order = page.locator('#order-details');
    await expect(order).toContainText(carrier);
    await expect(order).toContainText(/przy odbiorze/i);
    const reference = (await order.locator('#order-reference-value').innerText()).split(':').at(-1).trim();
    expect(reference).toMatch(/^[A-Z0-9]+$/);

    const lines = page.locator('#order-items .order-line');
    await expect(lines).toHaveCount(cart.size);
    for (const [name, quantity] of cart) {
      const line = lines.filter({ has: page.locator('.details').getByText(orderNames.get(name), { exact: true }) });
      await expect(line.locator('.qty > .row > div').nth(1)).toHaveText(String(quantity));
    }
    return reference;
  });

  const orderRow = page.locator('tbody tr').filter({
    has: page.getByRole('rowheader', { name: reference, exact: true }),
  });
  await test.step('Sprawdzenie statusu w historii zamówień', async () => {
    await account.locator('a.account').click();
    await page.locator('#history-link').click();
    await expect(orderRow).toBeVisible();
    await expect(orderRow).toContainText(/przy odbiorze/i);
    await expect(orderRow.locator('.label-pill')).toHaveText('Oczekiwanie na płatność przy odbiorze');
  });

  await test.step('Pobranie faktury VAT z historii zamówień', async () => {
    const invoice = orderRow.locator('a[href*="pdf-invoice"]');
    await expect(invoice).toBeVisible();
    const [download] = await Promise.all([page.waitForEvent('download'), invoice.click()]);
    expect(download.suggestedFilename()).toMatch(/\.pdf$/i);
    const path = testInfo.outputPath(`faktura-${reference}.pdf`);
    await download.saveAs(path);
    const pdf = await readFile(path);
    expect(pdf.subarray(0, 5).toString('ascii')).toBe('%PDF-');
    expect(pdf.subarray(-32).toString('ascii')).toContain('%%EOF');
    await testInfo.attach('Faktura VAT', { path, contentType: 'application/pdf' });
  });
});
