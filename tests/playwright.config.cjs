const { defineConfig } = require('@playwright/test');

const shopURL = new URL(process.env.SHOP_URL || 'https://localhost:8443/');
if (!shopURL.pathname.endsWith('/')) shopURL.pathname += '/';

module.exports = defineConfig({
  testDir: '.',
  workers: 1,
  timeout: 180_000,
  globalTimeout: 270_000,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: shopURL.href,
    channel: process.env.PLAYWRIGHT_CHANNEL,
    headless: true,
    ignoreHTTPSErrors: true,
    actionTimeout: 10_000,
    screenshot: 'only-on-failure',
    viewport: { width: 1440, height: 900 },
  },
});
