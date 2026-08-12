import { spawn } from 'node:child_process';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';

const targetUrl = process.env.FARYO_SMOKE_URL;
const sendText = process.env.FARYO_SMOKE_SEND_TEXT || '';
const expectSendFailure = process.env.FARYO_SMOKE_EXPECT_SEND_FAILURE === '1';
const expectLive = process.env.FARYO_SMOKE_EXPECT_LIVE === '1';
const expectLiveClears = process.env.FARYO_SMOKE_EXPECT_LIVE_CLEARS === '1';
const checkLiveScroll = process.env.FARYO_SMOKE_CHECK_LIVE_SCROLL === '1';
const skipRenderChecks = process.env.FARYO_SMOKE_SKIP_RENDER_CHECKS === '1';
// Real-session smoke tests may contain private conversations. Keep DOM shape
// and layout diagnostics while omitting rendered text/TeX from failure output.
const privacySafe = process.env.FARYO_SMOKE_PRIVACY_SAFE === '1';
const expectStructured = process.env.FARYO_SMOKE_EXPECT_STRUCTURED === '1';
const debugLayout = process.env.FARYO_SMOKE_DEBUG_LAYOUT === '1';
const screenshotPath = process.env.FARYO_SMOKE_SCREENSHOT || '';
const expectedTex = JSON.parse(process.env.FARYO_SMOKE_EXPECT_TEX || '[]');
const expectedOutput = process.env.FARYO_SMOKE_EXPECT_OUTPUT || '';
const minMatrixRows = Number(process.env.FARYO_SMOKE_MIN_MATRIX_ROWS || 0);
const screenshotTex = process.env.FARYO_SMOKE_SCREENSHOT_TEX || expectedTex.at(-1) || '';
const loginUser = process.env.FARYO_SMOKE_LOGIN_USER || '';
const loginPasswordFile = process.env.FARYO_SMOKE_LOGIN_PASSWORD_FILE || '';
const loginPassword = loginPasswordFile ? (await readFile(loginPasswordFile, 'utf8')).trim() : '';
const hostResolverRules = process.env.FARYO_SMOKE_HOST_RESOLVER_RULES || 'MAP * ~NOTFOUND, EXCLUDE 127.0.0.1';
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
    `--host-resolver-rules=${hostResolverRules}`,
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

  if (loginUser && loginPassword) {
    let loginReady = false;
    for (let attempt = 0; attempt < 80; attempt += 1) {
      await delay(100);
      const result = await send('Runtime.evaluate', {
        expression: `Boolean(document.querySelector('input[name="username"]') && document.querySelector('input[name="password"]'))`,
        returnByValue: true,
      });
      loginReady = Boolean(result.result?.value);
      if (loginReady) break;
    }
    if (!loginReady) throw new Error('Faryo Gateway login form did not appear');
    await send('Runtime.evaluate', {
      expression: `(() => {
        const username = document.querySelector('input[name="username"]');
        const password = document.querySelector('input[name="password"]');
        username.value = ${JSON.stringify(loginUser)};
        password.value = ${JSON.stringify(loginPassword)};
        username.form.requestSubmit();
      })()`,
    });
  }

  let state = {};
  for (let attempt = 0; attempt < 80; attempt += 1) {
    await delay(250);
    const result = await send('Runtime.evaluate', {
      expression: `(() => {
        const output = document.getElementById('output');
        const outputWrap = document.getElementById('outputWrap');
        const katexCount = output?.querySelectorAll('.katex').length || 0;
        const displayCount = output?.querySelectorAll('.katex-display').length || 0;
        const katexErrorCount = output?.querySelectorAll('.katex-error').length || 0;
        const markdownCount = output?.querySelectorAll('.markdown-body').length || 0;
        let rawMathDelimiterCount = 0;
        if (output) {
          const walker = document.createTreeWalker(output, NodeFilter.SHOW_TEXT);
          let node = walker.nextNode();
          while (node) {
            if (!node.parentElement?.closest('pre, code, .katex, .math-ignore')
                && /(?:\\\\\[|\\\\\]|\\\\\(|\\\\\)|\$\$)/.test(String(node.nodeValue || ''))) {
              rawMathDelimiterCount += 1;
            }
            node = walker.nextNode();
          }
        }
        const katexAssetUrls = performance.getEntriesByType('resource')
          .map((entry) => String(entry.name || ''))
          .filter((url) => /(?:\\/vendor\\/katex\\/|cdn\\.jsdelivr\\.net\\/npm\\/katex)/i.test(url));
        const markdownAssetUrls = performance.getEntriesByType('resource')
          .map((entry) => String(entry.name || ''))
          .filter((url) => /(?:\\/vendor\\/markdown-it\\/|cdn\\.jsdelivr\\.net\\/npm\\/markdown-it)/i.test(url));
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
            text: ${JSON.stringify(privacySafe)} ? '' : String(display.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 160),
            tex: ${JSON.stringify(privacySafe)} ? '' : String(annotation?.textContent || ''),
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
          domReady: Boolean(output && document.getElementById('promptInput') && document.documentElement.dataset.faryoAppReady === '1'),
          ready: katexCount >= 2 && displayCount >= 1 && markdownCount >= 1,
          katexCount,
          displayCount,
          katexErrorCount,
          rawMathDelimiterCount,
          markdownCount,
          captureSource: String(output?.dataset.captureSource || ''),
          captureWarningCount: output?.querySelectorAll('.compact-capture-warning').length || 0,
          viewport: { width: innerWidth, height: innerHeight },
          outputHorizontalOverflow: Boolean(outputWrap && outputWrap.scrollWidth > outputWrap.clientWidth + 1),
          katexStylesheetLoaded: [...document.styleSheets].some((sheet) => String(sheet.href || '').includes('/katex')),
          katexAssetUrls: ${JSON.stringify(privacySafe)}
            ? katexAssetUrls.map((url) => new URL(url).pathname)
            : katexAssetUrls,
          katexAssetsLocal: katexAssetUrls.length >= 3 && katexAssetUrls.every((url) => new URL(url).origin === location.origin),
          markdownAssetUrls: ${JSON.stringify(privacySafe)}
            ? markdownAssetUrls.map((url) => new URL(url).pathname)
            : markdownAssetUrls,
          markdownAssetsLocal: markdownAssetUrls.length >= 1 && markdownAssetUrls.every((url) => new URL(url).origin === location.origin),
          displayLayout,
          outputText: ${JSON.stringify(privacySafe)} ? '' : String(output?.innerText || '').slice(-600),
          outputHtml: ${JSON.stringify(privacySafe)} ? '' : String(output?.innerHTML || '').slice(-2400),
          errorText: ${JSON.stringify(privacySafe)} ? '' : String(document.getElementById('errorBox')?.innerText || ''),
        };
      })()`,
      returnByValue: true,
    });
    state = result.result?.value || {};
    if (skipRenderChecks ? state.domReady : state.ready) break;
  }

  if (!(skipRenderChecks ? state.domReady : state.ready)) {
    throw new Error(`KaTeX did not appear in the live Faryo DOM: ${JSON.stringify(state)}`);
  }
  if (!skipRenderChecks) {
    const brokenDisplayLayout = state.displayLayout.filter((item) => item.html?.whiteSpace !== 'nowrap');
    if (brokenDisplayLayout.length) {
      throw new Error(`KaTeX display layout lost nowrap: ${JSON.stringify(brokenDisplayLayout)}`);
    }
    if (state.outputHorizontalOverflow) {
      throw new Error('Formula rendering caused page-level horizontal overflow');
    }
    if (state.katexErrorCount) {
      throw new Error(`KaTeX left ${state.katexErrorCount} parse errors in the live Faryo DOM`);
    }
    if (state.rawMathDelimiterCount) {
      throw new Error(`Math delimiters remained visible in ${state.rawMathDelimiterCount} text nodes`);
    }
    if (expectStructured && (state.captureSource !== 'codex-app-server' || state.captureWarningCount)) {
      throw new Error(`Codex capture did not use structured history: source=${state.captureSource || 'missing'} warning=${state.captureWarningCount || 0}`);
    }
    if (!state.katexAssetsLocal) {
      throw new Error(`KaTeX loaded a missing or external asset: ${JSON.stringify(state.katexAssetUrls)}`);
    }
    if (!state.markdownAssetsLocal) {
      throw new Error(`markdown-it loaded a missing or external asset: ${JSON.stringify(state.markdownAssetUrls)}`);
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
  }

  if (checkLiveScroll) {
    let liveScrollState = {};
    for (let attempt = 0; attempt < 100; attempt += 1) {
      await delay(100);
      const result = await send('Runtime.evaluate', {
        expression: `(() => {
          const pane = document.querySelector('.compact-live-terminal pre');
          if (!pane || pane.scrollHeight <= pane.clientHeight) return { ready: false };
          const maximum = pane.scrollHeight - pane.clientHeight;
          const target = Math.max(1, Math.floor(maximum / 3));
          const initialNearBottom = maximum - pane.scrollTop < 48;
          pane.scrollTop = target;
          pane.dataset.faryoSmokeScroll = 'waiting';
          window.__faryoSmokeLiveScrollTarget = target;
          return { ready: true, initialNearBottom };
        })()`,
        returnByValue: true,
      });
      liveScrollState = result.result?.value || {};
      if (liveScrollState.ready) break;
    }
    if (!liveScrollState.ready) throw new Error('A scrollable Live from tmux pane did not appear');
    if (!liveScrollState.initialNearBottom) throw new Error('A new Live from tmux pane did not start at the latest output');

    let preserved = {};
    for (let attempt = 0; attempt < 120; attempt += 1) {
      await delay(100);
      const result = await send('Runtime.evaluate', {
        expression: `(() => {
          const pane = document.querySelector('.compact-live-terminal pre');
          const replaced = Boolean(pane && pane.dataset.faryoSmokeScroll !== 'waiting');
          const target = Number(window.__faryoSmokeLiveScrollTarget || 0);
          return {
            replaced,
            delta: pane ? Math.abs(pane.scrollTop - target) : -1,
          };
        })()`,
        returnByValue: true,
      });
      preserved = result.result?.value || {};
      if (preserved.replaced) break;
    }
    if (!preserved.replaced) throw new Error('Live from tmux did not refresh during the scroll test');
    if (preserved.delta > 2 || preserved.delta < 0) throw new Error(`Live from tmux moved the reading position by ${preserved.delta}px`);
    console.log('faryo-browser-live-scroll=PASS initial=latest manual=preserved');
  }

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
          storedDrafts: Object.entries(sessionStorage).filter(([key]) => key.startsWith('faryoPromptDraft:')).map(([, value]) => value),
        }))()`,
        returnByValue: true,
      });
      sendState = result.result?.value || {};
      if (sendState.errorText) break;
      if (!sendState.inputValue) break;
    }

    if (expectSendFailure) {
      if (!sendState.errorText || sendState.inputValue !== sendText || !sendState.storedDrafts?.includes(sendText)) {
        throw new Error(`Faryo browser did not preserve a failed draft: ${JSON.stringify(sendState)}`);
      }
      console.log('faryo-browser-send-failure-retains-draft=PASS');
    } else if (sendState.errorText || sendState.inputValue || sendState.storedDrafts?.includes(sendText)) {
      throw new Error(`Faryo browser send failed: ${JSON.stringify(sendState)}`);
    } else {
      console.log('faryo-browser-send-smoke=PASS');
    }

    if (expectLive && !expectSendFailure) {
      let liveState = {};
      for (let attempt = 0; attempt < 80; attempt += 1) {
        await delay(100);
        const result = await send('Runtime.evaluate', {
          expression: `(() => { const live = document.querySelector('.compact-live-terminal'); return { found: Boolean(live), text: String(live?.innerText || '') }; })()`,
          returnByValue: true,
        });
        liveState = result.result?.value || {};
        if (liveState.found) break;
      }
      if (!liveState.found) throw new Error(`Faryo live tmux panel did not appear: ${JSON.stringify(liveState)}`);
      console.log('faryo-browser-live-smoke=PASS');
      if (expectLiveClears) {
        for (let attempt = 0; attempt < 120; attempt += 1) {
          await delay(100);
          const result = await send('Runtime.evaluate', {
            expression: `(() => ({ found: Boolean(document.querySelector('.compact-live-terminal')) }))()`,
            returnByValue: true,
          });
          liveState = result.result?.value || {};
          if (!liveState.found) break;
        }
        if (liveState.found) throw new Error('Faryo live tmux panel did not clear after turn completion');
        console.log('faryo-browser-live-finalized=PASS');
      }
    }

    if (expectedOutput && !expectSendFailure) {
      let outputFound = false;
      for (let attempt = 0; attempt < 120; attempt += 1) {
        await delay(100);
        const result = await send('Runtime.evaluate', {
          expression: `String(document.getElementById('output')?.innerText || '').includes(${JSON.stringify(expectedOutput)})`,
          returnByValue: true,
        });
        outputFound = Boolean(result.result?.value);
        if (outputFound) break;
      }
      if (!outputFound) throw new Error('Expected output marker did not appear without a page reload');
      console.log('faryo-browser-auto-update-smoke=PASS');
    }
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
