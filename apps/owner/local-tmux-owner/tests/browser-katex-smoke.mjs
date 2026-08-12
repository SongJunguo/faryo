import { spawn } from 'node:child_process';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';

const targetUrl = process.env.FARYO_SMOKE_URL;
const sendText = process.env.FARYO_SMOKE_SEND_TEXT || '';
const debugLayout = process.env.FARYO_SMOKE_DEBUG_LAYOUT === '1';
const screenshotPath = process.env.FARYO_SMOKE_SCREENSHOT || '';
const expectedTex = JSON.parse(process.env.FARYO_SMOKE_EXPECT_TEX || '[]');
const minMatrixRows = Number(process.env.FARYO_SMOKE_MIN_MATRIX_ROWS || 0);
const screenshotTex = process.env.FARYO_SMOKE_SCREENSHOT_TEX || expectedTex.at(-1) || '';
const chromeBin = process.env.CHROME_BIN || '/usr/bin/google-chrome';
if (!targetUrl) {
  throw new Error('FARYO_SMOKE_URL is required');
}

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const profile = await mkdtemp(path.join(os.tmpdir(), 'faryo-katex-chrome-'));
let chrome;
let socket;

try {
  chrome = spawn(chromeBin, [
    '--headless=new',
    '--no-sandbox',
    '--disable-gpu',
    '--disable-dev-shm-usage',
    '--disable-background-networking',
    '--disable-default-apps',
    '--disable-sync',
    '--no-first-run',
    '--no-proxy-server',
    `--user-data-dir=${profile}`,
    '--remote-debugging-port=0',
    'about:blank',
  ], {
    stdio: ['ignore', 'ignore', 'pipe'],
  });

  chrome.stderr.setEncoding('utf8');
  const browserWebSocketUrl = await new Promise((resolve, reject) => {
    let buffered = '';
    const timer = setTimeout(() => reject(new Error('Chrome DevTools startup timed out')), 15000);
    chrome.stderr.on('data', (chunk) => {
      buffered += chunk;
      const match = buffered.match(/DevTools listening on (ws:\/\/[^\s]+)/);
      if (!match) return;
      clearTimeout(timer);
      resolve(match[1]);
    });
    chrome.once('exit', (code) => {
      clearTimeout(timer);
      reject(new Error(`Chrome exited before DevTools was ready (code ${code})`));
    });
  });

  const port = new URL(browserWebSocketUrl).port;
  const response = await fetch(`http://127.0.0.1:${port}/json/new?about%3Ablank`, {
    method: 'PUT',
  });
  if (!response.ok) {
    throw new Error(`Could not create Chrome target: HTTP ${response.status}`);
  }
  const target = await response.json();

  socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('Chrome target connection timed out')), 10000);
    socket.addEventListener('open', () => {
      clearTimeout(timer);
      resolve();
    }, { once: true });
    socket.addEventListener('error', () => {
      clearTimeout(timer);
      reject(new Error('Chrome target connection failed'));
    }, { once: true });
  });

  let nextId = 0;
  const pending = new Map();
  socket.addEventListener('message', (event) => {
    const message = JSON.parse(String(event.data));
    if (!message.id || !pending.has(message.id)) return;
    const { resolve, reject } = pending.get(message.id);
    pending.delete(message.id);
    if (message.error) reject(new Error(message.error.message));
    else resolve(message.result);
  });

  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++nextId;
    pending.set(id, { resolve, reject });
    socket.send(JSON.stringify({ id, method, params }));
  });

  await send('Page.enable');
  await send('Runtime.enable');
  await send('Page.navigate', { url: targetUrl });

  let state = {};
  for (let attempt = 0; attempt < 80; attempt += 1) {
    await delay(250);
    const result = await send('Runtime.evaluate', {
      expression: `(() => {
        const output = document.getElementById('output');
        const outputWrap = document.getElementById('outputWrap');
        const katexCount = output?.querySelectorAll('.katex').length || 0;
        const displayCount = output?.querySelectorAll('.katex-display').length || 0;
        const displayLayout = [...(output?.querySelectorAll('.katex-display') || [])].map((display) => {
          const formula = display.querySelector(':scope > .katex');
          const block = display.closest('.compact-block');
          const displayRect = display.getBoundingClientRect();
          const formulaRect = formula?.getBoundingClientRect();
          const blockRect = block?.getBoundingClientRect();
          const displayStyle = getComputedStyle(display);
          const formulaStyle = formula ? getComputedStyle(formula) : null;
          const mathml = formula?.querySelector('.katex-mathml');
          const annotation = mathml?.querySelector('annotation[encoding="application/x-tex"]');
          const html = formula?.querySelector('.katex-html');
          const mathmlStyle = mathml ? getComputedStyle(mathml) : null;
          const htmlStyle = html ? getComputedStyle(html) : null;
          const htmlRect = html?.getBoundingClientRect();
          const mathmlRect = mathml?.getBoundingClientRect();
          const bases = [...(formula?.querySelectorAll('.katex-base') || [])].map((base) => {
            const rect = base.getBoundingClientRect();
            const style = getComputedStyle(base);
            return {
              width: Math.round(rect.width),
              height: Math.round(rect.height),
              whiteSpace: style.whiteSpace,
              lineHeight: style.lineHeight,
              display: style.display,
            };
          });
          return {
            text: String(display.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 160),
            tex: String(annotation?.textContent || ''),
            matrixRows: mathml?.querySelectorAll('mtable > mtr').length || 0,
            displayWidth: Math.round(displayRect.width),
            displayHeight: Math.round(displayRect.height),
            displayScrollWidth: display.scrollWidth,
            formulaWidth: Math.round(formulaRect?.width || 0),
            formulaHeight: Math.round(formulaRect?.height || 0),
            blockWidth: Math.round(blockRect?.width || 0),
            whiteSpace: displayStyle.whiteSpace,
            wordBreak: displayStyle.wordBreak,
            formulaWhiteSpace: formulaStyle?.whiteSpace || '',
            formulaWordBreak: formulaStyle?.wordBreak || '',
            mathml: mathmlStyle ? {
              position: mathmlStyle.position,
              width: mathmlStyle.width,
              height: mathmlStyle.height,
              overflow: mathmlStyle.overflow,
              clip: mathmlStyle.clip,
              clipPath: mathmlStyle.clipPath,
              rect: { width: Math.round(mathmlRect?.width || 0), height: Math.round(mathmlRect?.height || 0) },
            } : null,
            html: htmlStyle ? {
              display: htmlStyle.display,
              position: htmlStyle.position,
              whiteSpace: htmlStyle.whiteSpace,
              lineHeight: htmlStyle.lineHeight,
              rect: { width: Math.round(htmlRect?.width || 0), height: Math.round(htmlRect?.height || 0) },
            } : null,
            bases,
          };
        });
        return {
          ready: katexCount >= 2 && displayCount >= 1,
          katexCount,
          displayCount,
          viewport: { width: innerWidth, height: innerHeight },
          outputHorizontalOverflow: Boolean(outputWrap && outputWrap.scrollWidth > outputWrap.clientWidth + 1),
          katexStylesheetLoaded: [...document.styleSheets].some((sheet) => String(sheet.href || '').includes('/katex')),
          displayLayout,
          outputText: String(output?.innerText || '').slice(-600),
          outputHtml: String(output?.innerHTML || '').slice(-2400),
          errorText: String(document.getElementById('errorBox')?.innerText || ''),
        };
      })()`,
      returnByValue: true,
    });
    state = result.result?.value || {};
    if (state.ready) break;
  }

  if (!state.ready) {
    throw new Error(`KaTeX did not appear in the live Faryo DOM: ${JSON.stringify(state)}`);
  }
  const brokenDisplayLayout = state.displayLayout.filter((item) => item.html?.whiteSpace !== 'nowrap');
  if (brokenDisplayLayout.length) {
    throw new Error(`KaTeX display layout lost nowrap: ${JSON.stringify(brokenDisplayLayout)}`);
  }
  if (state.outputHorizontalOverflow) {
    throw new Error('Formula rendering caused page-level horizontal overflow');
  }
  for (const expected of expectedTex) {
    if (!state.displayLayout.some((item) => item.tex.includes(expected))) {
      throw new Error(`Expected display TeX was not rendered: ${JSON.stringify(expected)}`);
    }
  }
  if (minMatrixRows > 0 && !state.displayLayout.some((item) => item.matrixRows >= minMatrixRows)) {
    throw new Error(`Expected a KaTeX matrix with at least ${minMatrixRows} rows`);
  }

  console.log('faryo-browser-katex-smoke=PASS');
  if (debugLayout) console.log(`faryo-browser-katex-layout=${JSON.stringify(state)}`);

  if (screenshotPath) {
    const targetResult = await send('Runtime.evaluate', {
      expression: `(() => {
        const expected = ${JSON.stringify(screenshotTex)};
        const items = [...document.querySelectorAll('#output .katex-display')];
        const target = expected
          ? items.find((item) => item.querySelector('annotation[encoding="application/x-tex"]')?.textContent.includes(expected))
          : items[items.length - 1];
        if (!target) return null;
        document.getElementById('faryo-smoke-screenshot-overlay')?.remove();
        const targetRect = target.getBoundingClientRect();
        const overlay = document.createElement('div');
        overlay.id = 'faryo-smoke-screenshot-overlay';
        Object.assign(overlay.style, {
          position: 'fixed',
          left: '0',
          top: '0',
          zIndex: '2147483647',
          boxSizing: 'border-box',
          width: '100vw',
          height: '100vh',
          padding: '16px',
          background: getComputedStyle(document.body).backgroundColor || '#fff',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        });
        const wrapper = document.createElement('section');
        wrapper.className = 'compact-block output';
        wrapper.style.width = Math.min(innerWidth - 32, Math.max(288, targetRect.width)) + 'px';
        const clone = target.cloneNode(true);
        clone.style.margin = '0';
        wrapper.appendChild(clone);
        overlay.appendChild(wrapper);
        document.body.appendChild(overlay);
        const cloneRect = clone.getBoundingClientRect();
        const html = clone.querySelector('.katex-html');
        return {
          found: true,
          text: String(clone.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 160),
          rect: { width: Math.round(cloneRect.width), height: Math.round(cloneRect.height) },
          display: getComputedStyle(clone).display,
          visibility: getComputedStyle(clone).visibility,
          color: getComputedStyle(clone).color,
          htmlDisplay: html ? getComputedStyle(html).display : '',
        };
      })()`,
      returnByValue: true,
    });
    const screenshotState = targetResult.result?.value;
    if (!screenshotState?.found) throw new Error(`Screenshot TeX was not found: ${JSON.stringify(screenshotTex)}`);
    if (debugLayout) console.log(`faryo-browser-screenshot-state=${JSON.stringify(screenshotState)}`);
    await send('Runtime.evaluate', { expression: 'document.fonts.ready', awaitPromise: true });
    await delay(100);
    const screenshot = await send('Page.captureScreenshot', {
      format: 'png',
      fromSurface: true,
    });
    await writeFile(screenshotPath, Buffer.from(screenshot.data, 'base64'));
    console.log(`faryo-browser-screenshot=${screenshotPath}`);
  }

  if (sendText) {
    await send('Runtime.evaluate', {
      expression: `(() => {
        const input = document.getElementById('promptInput');
        input.value = ${JSON.stringify(sendText)};
        input.dispatchEvent(new Event('input', { bubbles: true }));
        document.getElementById('sendBtn').click();
      })()`,
    });

    let sendState = {};
    for (let attempt = 0; attempt < 80; attempt += 1) {
      await delay(100);
      const result = await send('Runtime.evaluate', {
        expression: `(() => ({
          inputValue: document.getElementById('promptInput')?.value || '',
          errorText: document.getElementById('errorBox')?.innerText || '',
          errorHidden: document.getElementById('errorBox')?.classList.contains('hidden'),
        }))()`,
        returnByValue: true,
      });
      sendState = result.result?.value || {};
      if (sendState.errorText) break;
      if (!sendState.inputValue) break;
    }

    if (sendState.errorText || sendState.inputValue) {
      throw new Error(`Faryo browser send failed: ${JSON.stringify(sendState)}`);
    }
    console.log('faryo-browser-send-smoke=PASS');
  }
} finally {
  try {
    socket?.close();
  } catch {}
  if (chrome && chrome.exitCode === null) {
    chrome.kill('SIGTERM');
    await delay(400);
    if (chrome.exitCode === null) chrome.kill('SIGKILL');
  }
  await rm(profile, { recursive: true, force: true });
}
