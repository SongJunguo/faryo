import assert from 'node:assert/strict';
import test from 'node:test';

import { resolveBrowserExecutable, trustedSwipe, withBrowser } from './playwright.mjs';

test('Playwright fixture uses an installed browser and trusted input', async () => {
  assert.ok(resolveBrowserExecutable());
  await withBrowser({ viewport: { width: 390, height: 844 } }, async ({ page, mobile }) => {
    assert.equal(mobile, true);
    await page.setContent(`<!doctype html><style>body{margin:0}.spacer{height:2200px}</style><button id="action">Ready</button><div class="spacer"></div><script>document.querySelector('#action').addEventListener('click',event=>event.currentTarget.textContent=event.isTrusted?'Trusted':'Synthetic')</script>`);
    await page.locator('#action').click();
    assert.equal(await page.locator('#action').textContent(), 'Trusted');
    await trustedSwipe(page);
    await page.waitForFunction(() => window.scrollY > 20);
    assert.ok(await page.evaluate(() => window.scrollY));
  });
});
