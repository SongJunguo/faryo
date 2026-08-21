import { readFile } from 'node:fs/promises';

import { withBrowser } from '../../../../tools/browser-harness/playwright.mjs';

const targetUrl = process.env.FARYO_SMOKE_URL;
const expectedRelease = process.env.FARYO_SMOKE_EXPECT_RELEASE || '';
const expectedCaptureRevision = process.env.FARYO_SMOKE_EXPECT_CAPTURE_REVISION || '';
const loginUser = process.env.FARYO_SMOKE_LOGIN_USER || '';
const passwordFile = process.env.FARYO_SMOKE_LOGIN_PASSWORD_FILE || '';
const loginPassword = passwordFile ? (await readFile(passwordFile, 'utf8')).trim() : '';
const chromeBin = process.env.CHROME_BIN || '/usr/bin/google-chrome';

if (!targetUrl) throw new Error('FARYO_SMOKE_URL is required');

const delay = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

await withBrowser({
  executablePath: chromeBin,
  viewport: { width: 390, height: 844 },
  mobile: true,
}, async ({ page }) => {
  let captureRequests = 0;
  let eventRequests = 0;
  page.on('request', (request) => {
    const pathname = new URL(request.url()).pathname;
    if (pathname.endsWith('/api/capture')) captureRequests += 1;
    if (pathname.endsWith('/api/events')) eventRequests += 1;
  });

  const waitFor = async (probe, timeoutMs, message) => {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      try {
        if (await probe()) return;
      } catch (error) {
        if (!/Execution context was destroyed|navigation/i.test(String(error?.message || error))) throw error;
      }
      await delay(100);
    }
    throw new Error(message);
  };

  const waitForReady = () => waitFor(
    () => page.evaluate(() => document.documentElement.dataset.faryoAppReady === '1'),
    10000,
    'Owner app did not become ready',
  );

  await page.goto(targetUrl, { waitUntil: 'domcontentloaded' });
  if (loginUser && loginPassword) {
    await waitFor(
      () => page.evaluate(() => Boolean(document.querySelector('input[name="username"]') && document.querySelector('input[name="password"]'))),
      10000,
      'Gateway login form did not appear',
    );
    await page.evaluate(({ username, password }) => {
      const usernameInput = document.querySelector('input[name="username"]');
      const passwordInput = document.querySelector('input[name="password"]');
      usernameInput.value = username;
      passwordInput.value = password;
      usernameInput.form.requestSubmit();
    }, { username: loginUser, password: loginPassword });
  }
  await waitForReady();
  await waitFor(() => Promise.resolve(eventRequests >= 1), 5000, 'Initial event stream did not open');

  await page.evaluate(() => {
    const originalFetch = window.fetch.bind(window);
    window.__faryoOriginalFetch = originalFetch;
    window.__faryoStalledEventRequests = 0;
    window.fetch = (input, init = {}) => {
      const url = String(typeof input === 'string' ? input : input?.url || '');
      if (!url.includes('/api/events')) return originalFetch(input, init);
      window.__faryoStalledEventRequests += 1;
      let streamController = null;
      const body = new ReadableStream({
        start(controller) {
          streamController = controller;
          controller.enqueue(new TextEncoder().encode(': opened\n\n'));
        },
      });
      init.signal?.addEventListener('abort', () => {
        try {
          streamController.error(new DOMException('Aborted', 'AbortError'));
        } catch (_error) {}
      }, { once: true });
      return Promise.resolve(new Response(body, {
        status: 200,
        headers: { 'Content-Type': 'text/event-stream; charset=utf-8' },
      }));
    };
    Object.defineProperty(document, 'hidden', { configurable: true, value: true });
    document.dispatchEvent(new Event('visibilitychange'));
    delete document.hidden;
    document.dispatchEvent(new Event('visibilitychange'));
  });

  await waitFor(
    () => page.evaluate(() => window.__faryoStalledEventRequests >= 1),
    3000,
    'Foreground restoration did not recreate the event stream',
  );
  const captureBaseline = captureRequests;
  await waitFor(
    () => Promise.resolve(captureRequests > captureBaseline),
    15000,
    'Safety capture did not run while the event stream appeared open',
  );
  await waitFor(
    () => page.evaluate(() => window.__faryoStalledEventRequests >= 2),
    22000,
    'A heartbeat-stalled event stream did not reconnect',
  );

  const realEventsBeforeOnline = eventRequests;
  await page.evaluate(() => {
    window.fetch = window.__faryoOriginalFetch;
    delete window.__faryoOriginalFetch;
    window.dispatchEvent(new Event('online'));
  });
  await waitFor(
    () => Promise.resolve(eventRequests > realEventsBeforeOnline),
    5000,
    'Online restoration did not recreate the real event stream',
  );

  const realEventsBeforePageShow = eventRequests;
  await page.evaluate(() => {
    window.dispatchEvent(new PageTransitionEvent('pagehide', { persisted: true }));
    window.dispatchEvent(new PageTransitionEvent('pageshow', { persisted: true }));
  });
  await waitFor(
    () => Promise.resolve(eventRequests > realEventsBeforePageShow),
    5000,
    'BFCache pageshow did not recreate the event stream closed by pagehide',
  );

  await page.reload({ waitUntil: 'domcontentloaded' });
  await waitForReady();
  const assets = await page.evaluate(() => performance.getEntriesByType('resource').map((entry) => entry.name));
  if (expectedRelease && !assets.some((url) => url.includes(`/app.js?v=${expectedRelease}`))) {
    throw new Error('Ordinary reload did not load the expected release-keyed app asset');
  }
  if (expectedCaptureRevision && !assets.some((url) => url.includes(`/owner/capture-controller.mjs?v=${expectedCaptureRevision}`))) {
    throw new Error('Ordinary reload did not load the expected capture controller revision');
  }

  console.log(`faryo-browser-live-resilience=PASS captures=${captureRequests} events=${eventRequests} ordinary-reload=yes`);
});
