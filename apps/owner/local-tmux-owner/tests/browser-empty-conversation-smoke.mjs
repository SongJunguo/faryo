import { readFile } from 'node:fs/promises';

import { withBrowser } from '../../../../tools/browser-harness/playwright.mjs';

const targetUrl = process.env.FARYO_SMOKE_URL;
const loginUser = process.env.FARYO_SMOKE_LOGIN_USER || '';
const passwordFile = process.env.FARYO_SMOKE_LOGIN_PASSWORD_FILE || '';
const loginPassword = passwordFile ? (await readFile(passwordFile, 'utf8')).trim() : '';
const authCookie = process.env.FARYO_SMOKE_AUTH_COOKIE || '';
const chromeBin = process.env.CHROME_BIN || '/usr/bin/google-chrome';
const viewportWidth = Number(process.env.FARYO_SMOKE_VIEWPORT_WIDTH || 390);
const viewportHeight = Number(process.env.FARYO_SMOKE_VIEWPORT_HEIGHT || 844);

if (!targetUrl) throw new Error('FARYO_SMOKE_URL is required');

await withBrowser({
  executablePath: chromeBin,
  viewport: { width: viewportWidth, height: viewportHeight },
  mobile: viewportWidth < 720,
  extraHTTPHeaders: authCookie ? { Cookie: authCookie } : {},
}, async ({ page }) => {
  let captureRequests = 0;
  let eventRequests = 0;
  const emptyCapture = {
    ok: true,
    text: '',
    captureSource: 'codex-app-server',
    agentSource: 'codex-cli',
    agentProfile: 'codex',
    agentRunning: false,
    queuedSendNowAvailable: false,
    sessionId: 'anonymous-empty-thread',
    sessionTitle: 'New conversation',
    updatedAt: '2026-01-01T00:00:00Z',
  };
  await page.route('**/api/capture**', async (route) => {
    captureRequests += 1;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(emptyCapture),
    });
  });
  await page.route('**/api/events**', async (route) => {
    eventRequests += 1;
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: `event: capture\ndata: ${JSON.stringify(emptyCapture)}\n\n`,
    });
  });

  await page.goto(targetUrl, { waitUntil: 'domcontentloaded' });
  if (loginUser && loginPassword) {
    const username = page.locator('input[name="username"]');
    if (await username.count()) {
      await username.fill(loginUser);
      await page.locator('input[name="password"]').fill(loginPassword);
      await page.locator('form').evaluate((form) => form.requestSubmit());
    }
  }

  try {
    await page.waitForFunction(() => {
      const output = document.getElementById('output');
      return document.documentElement.dataset.faryoAppReady === '1'
        && output?.dataset.captureSource === 'codex-app-server'
        && output?.dataset.structuredEmpty === 'true';
    }, null, { timeout: 25_000 });
  } catch (_error) {
    const diagnostic = await page.evaluate(() => ({
      path: location.pathname,
      appReady: document.documentElement.dataset.faryoAppReady || '',
      source: document.getElementById('output')?.dataset.captureSource || '',
      empty: document.getElementById('output')?.dataset.structuredEmpty || '',
      loginVisible: Boolean(document.querySelector('input[name="username"]')),
      errorVisible: Boolean(document.getElementById('errorBox')?.innerText),
    }));
    throw new Error(`Empty conversation fixture did not become ready: ${JSON.stringify({ ...diagnostic, captureRequests, eventRequests })}`);
  }

  const state = await page.evaluate(() => {
    const output = document.getElementById('output');
    const text = String(output?.innerText || '');
    return {
      source: output?.dataset.captureSource || '',
      empty: output?.dataset.structuredEmpty || '',
      warningCount: output?.querySelectorAll('.compact-capture-warning').length || 0,
      compactBlocks: output?.querySelectorAll('.compact-block').length || 0,
      hasEmptyMessage: text.includes('No messages yet. Ask Codex to start this conversation.'),
      leakedTerminalStartup: /Codex ready|Ask Codex to do anything|for shortcuts/i.test(text),
      horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
    };
  });

  if (captureRequests < 1 || eventRequests < 1 || state.source !== 'codex-app-server' || state.empty !== 'true'
    || state.warningCount || !state.compactBlocks || !state.hasEmptyMessage
    || state.leakedTerminalStartup || state.horizontalOverflow) {
    throw new Error(`Empty structured conversation rendered incorrectly: ${JSON.stringify(state)}`);
  }

  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => {
    const output = document.getElementById('output');
    return document.documentElement.dataset.faryoAppReady === '1'
      && output?.dataset.captureSource === 'codex-app-server'
      && output?.dataset.structuredEmpty === 'true'
      && output?.innerText.includes('No messages yet. Ask Codex to start this conversation.')
      && !output?.querySelector('.compact-capture-warning');
  }, null, { timeout: 25_000 });

  console.log(`faryo-browser-empty-conversation=PASS viewport=${viewportWidth}x${viewportHeight} source=codex-app-server terminal-fallback=absent ordinary-reload=yes`);
});
