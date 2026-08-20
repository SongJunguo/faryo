import { writeFile } from 'node:fs/promises';

import { trustedSwipe, withBrowser } from '../../../../tools/browser-harness/playwright.mjs';

const targetUrl = process.env.FARYO_IMMERSIVE_URL;
const chromeBin = process.env.CHROME_BIN || '/usr/bin/google-chrome';
const viewport = {
  width: Number(process.env.FARYO_IMMERSIVE_WIDTH || 390),
  height: Number(process.env.FARYO_IMMERSIVE_HEIGHT || 844),
};
const screenshotPath = process.env.FARYO_IMMERSIVE_SCREENSHOT || '';
const authCookie = process.env.FARYO_IMMERSIVE_AUTH_COOKIE || '';
const expectDocumentScroll = process.env.FARYO_IMMERSIVE_EXPECT_DOCUMENT_SCROLL === '1';
if (!targetUrl) throw new Error('FARYO_IMMERSIVE_URL is required');

await withBrowser({
  executablePath: chromeBin,
  viewport,
  mobile: viewport.width < 720,
  extraHTTPHeaders: authCookie ? { Cookie: authCookie } : {},
}, async ({ page, mobile }) => {
  await page.goto(targetUrl, { waitUntil: 'domcontentloaded' });
  await page.waitForFunction((expectScroll) => {
    const ready = document.documentElement.dataset.faryoAppReady === '1'
      && document.documentElement.dataset.faryoImmersive === 'ready';
    return ready && (!expectScroll || document.scrollingElement.scrollHeight > innerHeight + 80);
  }, expectDocumentScroll, { timeout: 15000 });

  const baseline = await page.evaluate(() => ({
    ready: document.documentElement.dataset.faryoAppReady === '1'
      && document.documentElement.dataset.faryoImmersive === 'ready',
    supported: document.documentElement.dataset.faryoFullscreen !== 'unsupported',
    manifest: document.querySelector('link[rel="manifest"]')?.getAttribute('href') || '',
    enterLabel: document.getElementById('immersiveBtn')?.getAttribute('aria-label') || '',
    detailsLabel: document.querySelector('#detailsFullscreenBtn [data-fullscreen-label]')?.textContent || '',
    exitHidden: document.getElementById('immersiveExitBtn')?.hidden,
    horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
    scrollSurface: document.documentElement.dataset.faryoScrollSurface || '',
    documentScrollable: document.scrollingElement?.scrollHeight > innerHeight + 80,
    mainOverflow: getComputedStyle(document.getElementById('outputWrap')).overflowY,
    footerPosition: getComputedStyle(document.querySelector('footer')).position,
  }));
  if (!baseline.ready || baseline.manifest !== '/manifest.json' || baseline.enterLabel !== 'Enter full screen'
    || baseline.detailsLabel !== 'Enter full screen' || !baseline.exitHidden || baseline.horizontalOverflow) {
    throw new Error(`Immersive baseline failed: ${JSON.stringify(baseline)}`);
  }
  if (expectDocumentScroll && (baseline.scrollSurface !== 'document' || !baseline.documentScrollable
    || baseline.mainOverflow !== 'visible' || baseline.footerPosition !== 'fixed')) {
    throw new Error(`Mobile document scroll mode failed: ${JSON.stringify(baseline)}`);
  }
  if (!expectDocumentScroll && baseline.scrollSurface !== 'conversation') {
    throw new Error(`Unexpected document scroll mode: ${JSON.stringify(baseline)}`);
  }

  const verifyDocumentScroll = async () => {
    if (!expectDocumentScroll) return;
    await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'auto' }));
    await page.waitForTimeout(60);
    if (mobile) await trustedSwipe(page);
    else await page.mouse.wheel(0, 360);
    await page.waitForFunction(() => window.scrollY > 40);
    const rootScroll = await page.evaluate(() => {
      const footer = document.querySelector('footer')?.getBoundingClientRect();
      return {
        y: window.scrollY,
        innerMain: document.getElementById('outputWrap')?.scrollTop || 0,
        footerVisible: Boolean(footer && footer.bottom <= innerHeight + 1 && footer.top >= 0),
        markerCount: document.querySelectorAll('#questionNavMarkers .question-nav-marker').length,
        railRevealed: document.getElementById('questionNavigator')?.classList.contains('is-scrolling') || false,
      };
    });
    if (rootScroll.y <= 40 || rootScroll.innerMain !== 0 || !rootScroll.footerVisible) {
      throw new Error(`Trusted document scroll failed: ${JSON.stringify(rootScroll)}`);
    }
    if (rootScroll.markerCount >= 2 && !rootScroll.railRevealed) {
      throw new Error(`Document scroll did not reach question navigation: ${JSON.stringify(rootScroll)}`);
    }
    const promptGeometry = () => page.locator('.prompt-shell').evaluate((item) => {
      const rect = item.getBoundingClientRect();
      return { width: rect.width, height: rect.height, visible: rect.top >= 0 && rect.bottom <= innerHeight + 1 };
    });
    const before = await promptGeometry();
    await page.locator('#promptInput').click();
    const focused = await promptGeometry();
    await page.locator('#promptInput').blur();
    await page.waitForTimeout(140);
    const blurred = await promptGeometry();
    if (![before, focused, blurred].every((item) => item.visible)
      || Math.abs(before.width - focused.width) > 1 || Math.abs(before.height - focused.height) > 1
      || Math.abs(before.width - blurred.width) > 1 || Math.abs(before.height - blurred.height) > 1) {
      throw new Error(`Document-scroll composer geometry changed: ${JSON.stringify({ before, focused, blurred })}`);
    }
  };

  if (!baseline.supported) {
    await page.locator('#immersiveBtn').click();
    await page.waitForFunction(() => document.getElementById('errorBox')?.textContent.includes('Install Faryo from Home'));
    await verifyDocumentScroll();
    console.log(`faryo-browser-immersive=PASS viewport=${viewport.width}x${viewport.height} api=unsupported fallback=pwa root-scroll=${expectDocumentScroll ? 'yes' : 'no'}`);
    return;
  }

  await page.waitForTimeout(220);
  await page.locator('#immersiveBtn').click();
  await page.waitForFunction(() => Boolean(document.fullscreenElement || document.webkitFullscreenElement));
  const entered = await page.evaluate(() => ({
    active: Boolean(document.fullscreenElement || document.webkitFullscreenElement),
    rootState: document.documentElement.dataset.faryoFullscreen,
    topExitVisible: Boolean(document.getElementById('immersiveBtn')?.getClientRects().length),
    floatingExitHidden: document.getElementById('immersiveExitBtn')?.hidden === false
      && !document.getElementById('immersiveExitBtn')?.getClientRects().length,
    toggleLabel: document.getElementById('immersiveBtn')?.getAttribute('aria-label') || '',
    toggleText: document.getElementById('immersiveBtn')?.textContent?.trim() || '',
    horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
  }));
  if (!entered.active || entered.rootState !== 'active' || !entered.topExitVisible || !entered.floatingExitHidden
    || entered.toggleLabel !== 'Exit full screen' || entered.toggleText !== 'Exit' || entered.horizontalOverflow) {
    throw new Error(`Entering full screen failed: ${JSON.stringify(entered)}`);
  }
  if (screenshotPath) await writeFile(screenshotPath, await page.screenshot({ type: 'png' }));

  await page.locator('#immersiveBtn').click();
  await page.waitForFunction(() => !document.fullscreenElement && !document.webkitFullscreenElement);
  const exited = await page.evaluate(() => ({
    rootState: document.documentElement.dataset.faryoFullscreen,
    exitHidden: document.getElementById('immersiveExitBtn')?.hidden === true,
    toggleLabel: document.getElementById('immersiveBtn')?.getAttribute('aria-label') || '',
  }));
  if (exited.rootState !== 'ready' || !exited.exitHidden || exited.toggleLabel !== 'Enter full screen') {
    throw new Error(`Exiting full screen failed: ${JSON.stringify(exited)}`);
  }

  await page.locator('#detailsBtn').click();
  await page.locator('#detailsPanel:not(.hidden)').waitFor();
  await page.locator('#detailsFullscreenBtn').click();
  await page.waitForFunction(() => Boolean(document.fullscreenElement || document.webkitFullscreenElement));
  const detailsEntered = await page.evaluate(() => ({
    panelClosed: document.getElementById('detailsPanel')?.classList.contains('hidden') || false,
    topExitVisible: Boolean(document.getElementById('immersiveBtn')?.getClientRects().length),
  }));
  if (!detailsEntered.panelClosed || !detailsEntered.topExitVisible) {
    throw new Error(`Details full screen flow failed: ${JSON.stringify(detailsEntered)}`);
  }
  await page.locator('#sessionTitle').click();
  await page.locator('#immersiveExitBtn').waitFor({ state: 'visible' });
  await page.locator('#immersiveExitBtn').click();
  await page.waitForFunction(() => !document.fullscreenElement && !document.webkitFullscreenElement);

  await verifyDocumentScroll();
  console.log(`faryo-browser-immersive=PASS viewport=${viewport.width}x${viewport.height} api=fullscreen topbar=yes details=yes exit=yes root-scroll=${expectDocumentScroll ? 'yes' : 'no'}`);
});
