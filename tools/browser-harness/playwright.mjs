import { existsSync } from 'node:fs';
import { chromium } from 'playwright-core';

const DEFAULT_BROWSER_CANDIDATES = [
  '/usr/bin/google-chrome',
  '/usr/bin/microsoft-edge-stable',
  '/usr/bin/chromium',
  '/usr/bin/chromium-browser',
];

export function resolveBrowserExecutable(explicit = '') {
  const candidates = [explicit, process.env.CHROME_BIN || '', ...DEFAULT_BROWSER_CANDIDATES]
    .map((item) => String(item || '').trim())
    .filter(Boolean);
  const selected = candidates.find((item) => existsSync(item));
  if (!selected) throw new Error('No system Chrome/Edge executable is available');
  return selected;
}

export async function withBrowser(options, callback) {
  const viewport = options?.viewport || { width: 390, height: 844 };
  const mobile = options?.mobile ?? viewport.width < 720;
  const browser = await chromium.launch({
    executablePath: resolveBrowserExecutable(options?.executablePath),
    headless: options?.headless !== false,
    args: [
      '--no-sandbox',
      '--disable-gpu',
      '--disable-dev-shm-usage',
      '--disable-background-networking',
      '--disable-default-apps',
      '--disable-sync',
      '--no-first-run',
      '--no-proxy-server',
      `--host-resolver-rules=${options?.hostResolverRules || 'MAP * ~NOTFOUND, EXCLUDE 127.0.0.1'}`,
      ...(options?.args || []),
    ],
  });
  const context = await browser.newContext({
    viewport,
    deviceScaleFactor: 1,
    isMobile: mobile,
    hasTouch: mobile,
    extraHTTPHeaders: options?.extraHTTPHeaders || {},
  });
  const page = await context.newPage();
  try {
    return await callback({ browser, context, page, viewport, mobile });
  } finally {
    await context.close().catch(() => {});
    await browser.close().catch(() => {});
  }
}

export async function trustedSwipe(page, options = {}) {
  const viewport = page.viewportSize();
  if (!viewport) throw new Error('Touch swipe requires a fixed viewport');
  const x = Number(options.x || viewport.width / 2);
  const startY = Number(options.startY || viewport.height * 0.76);
  const endY = Number(options.endY || viewport.height * 0.36);
  const steps = Math.max(2, Number(options.steps || 4));
  const session = await page.context().newCDPSession(page);
  const point = (y) => [{ x, y, radiusX: 2, radiusY: 2, force: 1, id: 1 }];
  try {
    await session.send('Emulation.setTouchEmulationEnabled', { enabled: true, maxTouchPoints: 1 });
    await session.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: point(startY) });
    for (let index = 1; index <= steps; index += 1) {
      const y = startY + ((endY - startY) * index) / steps;
      await session.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: point(y) });
      await page.waitForTimeout(18);
    }
    await session.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  } finally {
    await session.detach().catch(() => {});
  }
}
