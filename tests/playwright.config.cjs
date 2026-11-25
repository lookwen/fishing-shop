const { defineConfig } = require('@playwright/test');

module.exports = defineConfig({
  testDir: '.',
  workers: 1,
  timeout: 120_000,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: process.env.SHOP_URL || 'https://localhost:8443/',
    channel: process.env.PLAYWRIGHT_CHANNEL,
    ignoreHTTPSErrors: true,
    actionTimeout: 10_000,
    screenshot: 'only-on-failure',
    viewport: { width: 1440, height: 900 },
  },
});
