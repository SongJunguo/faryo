import { withBrowser } from '../../../../tools/browser-harness/playwright.mjs';

const targetUrl = process.env.FARYO_CHANGES_URL;
const viewport = {
  width: Number(process.env.FARYO_CHANGES_WIDTH || 390),
  height: Number(process.env.FARYO_CHANGES_HEIGHT || 844),
};
const expectedFiles = Number(process.env.FARYO_CHANGES_EXPECT_FILES || 1);
const authCookie = process.env.FARYO_CHANGES_AUTH_COOKIE || '';
if (!targetUrl) throw new Error('FARYO_CHANGES_URL is required');

await withBrowser({
  executablePath: process.env.CHROME_BIN || '/usr/bin/google-chrome',
  viewport,
  mobile: viewport.width < 720,
  extraHTTPHeaders: authCookie ? { Cookie: authCookie } : {},
}, async ({ page }) => {
  await page.goto(targetUrl, { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => document.documentElement.dataset.faryoAppReady === '1');
  const before = await page.evaluate(() => ({
    script: Boolean(document.getElementById('faryoDiffReviewScript')),
    css: Boolean(document.getElementById('faryoDiffReviewCss')),
  }));
  if (before.script || before.css) throw new Error('Diff review assets loaded before the feature was opened');

  await page.locator('#detailsBtn').click();
  await page.locator('#detailsChangesBtn').click();
  await page.locator('#changesPanel:not(.hidden)').waitFor();
  await page.locator('#changesDiff .d2h-file-wrapper').first().waitFor({ timeout: 15000 });
  await page.waitForTimeout(260);

  const lineState = await page.evaluate(() => {
    const panel = document.getElementById('changesPanel');
    const diff = document.getElementById('changesDiff');
    const fileRows = [...document.querySelectorAll('#changesFiles .changes-file')];
    return {
      fileCount: fileRows.length,
      relativePaths: fileRows.every((row) => !String(row.querySelector('code')?.textContent || '').startsWith('/')),
      lazyAssets: Boolean(document.getElementById('faryoDiffReviewScript') && document.getElementById('faryoDiffReviewCss')),
      lineActive: document.getElementById('changesLineBtn')?.classList.contains('mode-active') || false,
      diffReady: Boolean(diff?.querySelector('.d2h-file-wrapper')),
      scripts: diff?.querySelectorAll('script').length || 0,
      eventAttributes: [...(diff?.querySelectorAll('*') || [])].some((item) => [...item.attributes].some((attribute) => attribute.name.startsWith('on'))),
      readOnly: document.querySelector('.changes-readonly')?.textContent.includes('cannot stage, discard, commit, checkout, or apply') || false,
      forbiddenControls: [...panel.querySelectorAll('button')].some((item) => /stage|discard|commit|checkout|apply/i.test(item.textContent)),
      pageOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
      panelRect: (() => { const rect = panel.getBoundingClientRect(); return { left: rect.left, right: rect.right, width: rect.width, viewport: innerWidth }; })(),
    };
  });
  if (lineState.fileCount < expectedFiles || !lineState.relativePaths || !lineState.lazyAssets
    || !lineState.lineActive || !lineState.diffReady || lineState.scripts || lineState.eventAttributes
    || !lineState.readOnly || lineState.forbiddenControls || lineState.pageOverflow
    || lineState.panelRect.left < -1 || lineState.panelRect.right > lineState.panelRect.viewport + 1) {
    throw new Error(`Read-only line diff failed: ${JSON.stringify(lineState)}`);
  }

  await page.locator('#changesSplitBtn').click();
  await page.waitForFunction(() => document.getElementById('changesSplitBtn')?.classList.contains('mode-active'));
  const splitState = await page.evaluate(() => ({
    splitActive: document.getElementById('changesSplitBtn')?.classList.contains('mode-active') || false,
    sideBySide: Boolean(document.querySelector('#changesDiff .d2h-file-side-diff')),
    pageOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
    innerScrollable: (() => { const item = document.getElementById('changesDiff'); return Boolean(item && item.scrollWidth >= item.clientWidth); })(),
  }));
  if (!splitState.splitActive || !splitState.sideBySide || splitState.pageOverflow || !splitState.innerScrollable) {
    throw new Error(`Read-only split diff failed: ${JSON.stringify(splitState)}`);
  }

  await page.locator('#changesPanel [data-close-panel]').click();
  await page.locator('#detailsBtn').click();
  const downloadPromise = page.waitForEvent('download');
  await page.locator('#detailsDiagnosticsBtn').click();
  const download = await downloadPromise;
  const stream = await download.createReadStream();
  const chunks = [];
  for await (const chunk of stream) chunks.push(chunk);
  const diagnosticsText = Buffer.concat(chunks).toString('utf8');
  const diagnostics = JSON.parse(diagnosticsText);
  if (download.suggestedFilename() !== 'faryo-diagnostics.json' || diagnostics.schemaVersion !== 1
    || !diagnostics.features?.diagnostics || !diagnostics.counts
    || /(?:token|cookie|email|hostname|username|sessionId|cwd|\/home\/)/i.test(diagnosticsText)) {
    throw new Error('Downloaded diagnostics violated the privacy contract');
  }

  console.log(`faryo-browser-workspace-changes=PASS viewport=${viewport.width}x${viewport.height} files=${lineState.fileCount} lazy-assets=yes sanitized=yes diagnostics=redacted read-only=yes`);
});
