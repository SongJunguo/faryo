import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';

const targetUrl = process.env.FARYO_SMOKE_URL;
const sendText = process.env.FARYO_SMOKE_SEND_TEXT || '';
const sendMatrixFile = process.env.FARYO_SMOKE_SEND_MATRIX_FILE || '';
const rawSendMatrix = sendMatrixFile ? JSON.parse(await readFile(sendMatrixFile, 'utf8')) : [];
const sendMatrix = Array.isArray(rawSendMatrix) ? rawSendMatrix.map((item, index) => {
  const digest = typeof item?.text === 'string'
    ? createHash('sha256').update(item.text, 'utf8').digest('hex').slice(0, 16)
    : '';
  return {
    ...item,
    expectedOutput: item?.expectedOutput
      || `FARYO_DELIVERY_ACK_${String(index + 1).padStart(2, '0')} sha256=${digest}`,
  };
}) : rawSendMatrix;
const attachmentViaClipboard = process.env.FARYO_SMOKE_CLIPBOARD_IMAGE === '1';
const clipboardPngBase64 = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=';
const attachmentName = process.env.FARYO_SMOKE_ATTACHMENT_NAME || (attachmentViaClipboard ? 'anonymous-clipboard.png' : '');
const attachmentContent = process.env.FARYO_SMOKE_ATTACHMENT_CONTENT || (attachmentViaClipboard ? clipboardPngBase64 : '');
const attachmentPrompt = process.env.FARYO_SMOKE_ATTACHMENT_PROMPT || '';
const attachmentExpectedOutput = process.env.FARYO_SMOKE_ATTACHMENT_EXPECT_OUTPUT || '';
const checkRecovery = process.env.FARYO_SMOKE_CHECK_RECOVERY === '1';
const recoveryTmuxSession = process.env.FARYO_SMOKE_TMUX_SESSION || '';
const recoveryStartIndex = Number(process.env.FARYO_SMOKE_RECOVERY_START_INDEX || 0);
const checkAmbiguousSend = process.env.FARYO_SMOKE_CHECK_AMBIGUOUS_SEND === '1';
const ambiguousSendIndex = Number(process.env.FARYO_SMOKE_AMBIGUOUS_SEND_INDEX || 0);
const checkSessionSendIsolation = process.env.FARYO_SMOKE_CHECK_SESSION_SEND_ISOLATION === '1';
const isolationSessionA = process.env.FARYO_SMOKE_SESSION_A || '';
const isolationSessionB = process.env.FARYO_SMOKE_SESSION_B || '';
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
const checkOwnerLayout = process.env.FARYO_SMOKE_CHECK_OWNER_LAYOUT === '1';
const checkCommandSuggestions = process.env.FARYO_SMOKE_CHECK_COMMANDS === '1';
const checkCopyFidelity = process.env.FARYO_SMOKE_CHECK_COPY_FIDELITY === '1';
const checkModeSwitch = process.env.FARYO_SMOKE_CHECK_MODE_SWITCH === '1';
const checkRefreshLatest = process.env.FARYO_SMOKE_CHECK_REFRESH_LATEST === '1';
const checkAstFixture = process.env.FARYO_SMOKE_CHECK_AST_FIXTURE === '1';
const checkQuestionNavigator = process.env.FARYO_SMOKE_CHECK_QUESTION_NAV === '1';
const forceRenderFailure = process.env.FARYO_SMOKE_FORCE_RENDER_FAILURE === '1';
const expectedLivePanelState = process.env.FARYO_SMOKE_EXPECT_LIVE_PANEL_STATE || '';
const expectedInteractionState = process.env.FARYO_SMOKE_EXPECT_INTERACTION || 'hidden';
const viewportWidth = Number(process.env.FARYO_SMOKE_VIEWPORT_WIDTH || 0);
const viewportHeight = Number(process.env.FARYO_SMOKE_VIEWPORT_HEIGHT || 0);
const smokeTheme = process.env.FARYO_SMOKE_THEME || '';
const screenshotPath = process.env.FARYO_SMOKE_SCREENSHOT || '';
const uiScreenshotPath = process.env.FARYO_SMOKE_UI_SCREENSHOT || '';
const questionNavScreenshotPath = process.env.FARYO_SMOKE_QUESTION_NAV_SCREENSHOT || '';
const uiScreenshotPanel = process.env.FARYO_SMOKE_UI_PANEL || '';
const uiScreenshotFocus = process.env.FARYO_SMOKE_UI_FOCUS || '';
const expectedTex = JSON.parse(process.env.FARYO_SMOKE_EXPECT_TEX || '[]');
const expectedOutput = process.env.FARYO_SMOKE_EXPECT_OUTPUT || '';
const expectedSessionTitle = process.env.FARYO_SMOKE_EXPECT_SESSION_TITLE || '';
const expectedCanonicalSession = process.env.FARYO_SMOKE_EXPECT_CANONICAL_SESSION || '';
const expectedGoalStatus = process.env.FARYO_SMOKE_EXPECT_GOAL_STATUS || '';
const minMatrixRows = Number(process.env.FARYO_SMOKE_MIN_MATRIX_ROWS || 0);
const minKatex = Number(process.env.FARYO_SMOKE_MIN_KATEX ?? 2);
const minDisplay = Number(process.env.FARYO_SMOKE_MIN_DISPLAY ?? 1);
const minTables = Number(process.env.FARYO_SMOKE_MIN_TABLES || 0);
const minTableKatex = Number(process.env.FARYO_SMOKE_MIN_TABLE_KATEX || 0);
const minProtectedLinks = Number(process.env.FARYO_SMOKE_MIN_PROTECTED_LINKS || 0);
const minProtectedImages = Number(process.env.FARYO_SMOKE_MIN_PROTECTED_IMAGES || 0);
const minMemoryReferences = Number(process.env.FARYO_SMOKE_MIN_MEMORY_REFERENCES || 0);
const minQuestionMarkers = Number(process.env.FARYO_SMOKE_MIN_QUESTION_MARKERS || 0);
const expectedHistoryTurns = Number(process.env.FARYO_SMOKE_EXPECT_HISTORY_TURNS || 0);
const historyRequiresFormula = process.env.FARYO_SMOKE_HISTORY_REQUIRE_FORMULA !== '0';
const requireDeferredRichBlocks = process.env.FARYO_SMOKE_REQUIRE_DEFERRED_RICH === '1';
const maxInitialRichBlocks = Number(process.env.FARYO_SMOKE_MAX_INITIAL_RICH || 0);
const checkLongHistoryResize = process.env.FARYO_SMOKE_CHECK_LONG_HISTORY_RESIZE === '1';
const minRenderFallbacks = Number(process.env.FARYO_SMOKE_MIN_RENDER_FALLBACKS || 0);
const maxBareTex = Number(process.env.FARYO_SMOKE_MAX_BARE_TEX ?? -1);
const screenshotTex = process.env.FARYO_SMOKE_SCREENSHOT_TEX || expectedTex.at(-1) || '';
const loginUser = process.env.FARYO_SMOKE_LOGIN_USER || '';
const loginPasswordFile = process.env.FARYO_SMOKE_LOGIN_PASSWORD_FILE || '';
const loginPassword = loginPasswordFile ? (await readFile(loginPasswordFile, 'utf8')).trim() : '';
const authCookie = process.env.FARYO_SMOKE_AUTH_COOKIE || '';
const hostResolverRules = process.env.FARYO_SMOKE_HOST_RESOLVER_RULES || 'MAP * ~NOTFOUND, EXCLUDE 127.0.0.1';
const chromeBin = process.env.CHROME_BIN || '/usr/bin/google-chrome';
const astFence = String.fromCharCode(96).repeat(3);
const astFixtureSource = [
  '# Generic control example',
  '',
  '**注意：**内容继续。',
  '',
  '| Operator | Recommendation |',
  '| --- | --- |',
  '| \\(\\Psi_i=\\eta_i\\) | exact recovery with a deliberately long explanation |',
  '| \\(\\Psi_i=e_i\\) | standard integral action |',
  '| \\(\\Psi_i=\\vartheta_{i,\\nu_i}(k_i)e_i\\) | bounded scheduling |',
  '| \\(\\Psi_i=\\delta_i\\tanh(e_i/\\gamma_i)\\) | nonlinear gain |',
  '| \\(\\Psi_i=e_i-\\sigma_i z_i\\) | leakage mechanism |',
  '',
  '\\[',
  'p(s)=\\begin{cases}',
  'a,&0\\le s<s_0,\\\\',
  'b,&s\\ge s_0,',
  '\\end{cases}',
  '\\]',
  '',
  astFence + 'ts',
  'const answer: number = 42',
  astFence,
  '',
  astFence + 'python',
  'def square(value):',
  '    return value ** 2',
  astFence,
  '',
  astFence + 'tex',
  '\\begin{align}',
  'x &= y + 1',
  '\\end{align}',
  astFence,
  '',
  astFence + 'lean4',
  'theorem identity (value : Nat) : value = value := by rfl',
  astFence,
  '',
  astFence + 'matlab',
  'value = sin(pi / 4);',
  astFence,
  '',
  astFence + 'text',
  '$HOME and \\(not_math\\)',
  astFence,
  '',
  '<img src=x onerror="globalThis.pwned=1">',
].join('\n');
const copyFixtureUser = 'Can you preserve \\(q(t)\\) when this question is copied?';
const copyFixtureAnswer = [
  '## Copy result',
  '',
  'For \\(x_i^2\\), keep the original TeX.',
  '',
  '\\[',
  'd(t)=\\begin{cases}',
  '-1,&t<1,\\\\',
  '1,&t\\ge1.',
  '\\end{cases}',
  '\\]',
  '',
  '| Item | Formula |',
  '| --- | --- |',
  '| state | \\(x_i\\) |',
  '',
  '- Preserve lists.',
  '- Preserve formulas.',
  '',
  astFence + 'tex',
  '\\[literal code\\]',
  astFence,
].join('\n');
const uiFixtureSource = [
  '## Verified result',
  '',
  'Markdown, equations, tables, and code share one safe AST pipeline. Wide content scrolls inside its own container instead of squeezing the page.',
  '',
  '| Integral operator | Rendering check |',
  '| --- | --- |',
  '| \\(\\Psi_i=\\eta_i\\) | Exact baseline structure |',
  '| \\(\\Psi_i=e_i\\) | Standard error integral |',
  '| \\(\\Psi_i=\\vartheta_{i,\\nu_i}(k_i)e_i\\) | Indexed scheduling remains intact |',
  '| \\(\\Psi_i=\\delta_i\\tanh(e_i/\\gamma_i)\\) | Nonlinear integral gain |',
  '| \\(\\Psi_i=e_i-\\sigma_i z_i\\) | Leakage modification |',
  '',
  '> Wide equations keep one mathematical layout instead of collapsing into vertical characters.',
  '',
  '\\[',
  'd(t)=\\begin{cases}',
  '-1,&t<1,\\\\',
  '1,&t\\ge 1.',
  '\\end{cases}',
  '\\]',
  '',
  '\\[',
  '\\dot{x}_2=F_2(x_1,x_2)+C\\,\\operatorname{sgn}(d(t))\\sqrt{|d(t)|}+u.',
  '\\]',
  '',
  '\\[',
  'A=\\begin{bmatrix}1&2&3\\\\4&5&6\\end{bmatrix}.',
  '\\]',
  '',
  '### Rendering checks',
  '',
  '- Inline code `render(markdown)` never triggers math parsing.',
  '- Fenced code preserves whitespace and loads highlighting on demand.',
  '',
  astFence + 'ts',
  'const renderState = {',
  "  mode: 'structured',",
  '  stableBlocks: true,',
  '};',
  astFence,
].join('\n');
if (!targetUrl) {
  throw new Error('FARYO_SMOKE_URL is required');
}
const smokeOwnerToken = new URL(targetUrl).searchParams.get('token') || '';
if (!['hidden', 'visible'].includes(expectedInteractionState)) {
  throw new Error('FARYO_SMOKE_EXPECT_INTERACTION must be hidden or visible');
}
if (!['', 'table', 'math', 'code'].includes(uiScreenshotFocus)) {
  throw new Error('FARYO_SMOKE_UI_FOCUS must be table, math, code, or empty');
}
if (!Array.isArray(sendMatrix) || sendMatrix.some((item) => (
  !item || typeof item.text !== 'string' || !item.text.trim()
  || typeof item.expectedOutput !== 'string' || !item.expectedOutput
))) {
  throw new Error('FARYO_SMOKE_SEND_MATRIX_FILE must contain text/expectedOutput objects');
}
if (sendText && sendMatrix.length) {
  throw new Error('Use either FARYO_SMOKE_SEND_TEXT or FARYO_SMOKE_SEND_MATRIX_FILE');
}
if ([attachmentName, attachmentContent, attachmentPrompt, attachmentExpectedOutput].some(Boolean)
    && ![attachmentName, attachmentContent, attachmentPrompt, attachmentExpectedOutput].every(Boolean)) {
  throw new Error('Attachment smoke requires name, content, prompt, and expected output');
}
if (checkRecovery && (!recoveryTmuxSession || recoveryStartIndex < 1)) {
  throw new Error('Recovery smoke requires a tmux session and positive start index');
}
if (checkSessionSendIsolation && (!isolationSessionA || !isolationSessionB || !new URL(targetUrl).pathname.startsWith('/txy/'))) {
  throw new Error('Session send isolation requires two sessions and a /txy/ URL');
}

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const runCommand = (command, args) => new Promise((resolve, reject) => {
  const child = spawn(command, args, { stdio: ['ignore', 'ignore', 'pipe'] });
  let stderr = '';
  child.stderr.setEncoding('utf8');
  child.stderr.on('data', (chunk) => { stderr += chunk; });
  child.once('error', reject);
  child.once('exit', (code) => {
    if (code === 0) resolve();
    else reject(new Error(`${command} failed (${code}): ${stderr.trim()}`));
  });
});
const receiverAck = (index, text) => {
  const digest = createHash('sha256').update(text, 'utf8').digest('hex').slice(0, 16);
  return `FARYO_DELIVERY_ACK_${String(index).padStart(2, '0')} sha256=${digest}`;
};
const injectReceiverTurn = async (session, text) => {
  await runCommand('tmux', ['send-keys', '-t', session, '-l', `\u001b[200~${text}\u001b[201~`]);
  await runCommand('tmux', ['send-keys', '-t', session, 'C-m']);
};
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
  await send('Network.enable');
  if (authCookie) {
    const separator = authCookie.indexOf('=');
    if (separator <= 0) throw new Error('FARYO_SMOKE_AUTH_COOKIE must be name=value');
    await send('Network.setExtraHTTPHeaders', { headers: { Cookie: authCookie } });
  }
  if (['light', 'dark', 'system'].includes(smokeTheme)) {
    await send('Page.addScriptToEvaluateOnNewDocument', {
      source: `localStorage.setItem('faryoTheme', ${JSON.stringify(smokeTheme)});`,
    });
  }
  if (forceRenderFailure) {
    await send('Page.addScriptToEvaluateOnNewDocument', {
      source: `(() => {
        let renderer;
        Object.defineProperty(globalThis, 'FaryoMarkdownAst', {
          configurable: true,
          get: () => renderer,
          set: (value) => {
            renderer = value && typeof value === 'object' ? new Proxy(value, {
              get: (target, property, receiver) => property === 'render'
                ? () => { throw new Error('anonymous render failure fixture'); }
                : Reflect.get(target, property, receiver),
            }) : value;
          },
        });
      })();`,
    });
  }
  if (viewportWidth > 0 && viewportHeight > 0) {
    await send('Emulation.setDeviceMetricsOverride', {
      width: viewportWidth,
      height: viewportHeight,
      deviceScaleFactor: 1,
      mobile: viewportWidth < 720,
    });
  }
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
        const promptShell = document.querySelector('.prompt-shell');
        const questionNavigator = document.getElementById('questionNavigator');
        const questionMarkers = [...document.querySelectorAll('#questionNavMarkers .question-nav-marker')];
        const historyRequests = performance.getEntriesByType('resource')
          .map((entry) => String(entry.name || ''))
          .filter((url) => url.includes('/api/conversation-history'))
          .map((url) => {
            const parsed = new URL(url);
            return parsed.searchParams.has('around') ? 'around' : (parsed.searchParams.has('cursor') ? 'cursor' : 'latest');
          });
        const livePanel = output?.querySelector('.compact-live-terminal');
        const statusLine = document.querySelector('.status-line');
        const interaction = document.querySelector('.interaction-backdrop');
        const promptRect = promptShell?.getBoundingClientRect();
        const homeLink = document.getElementById('homeBtn');
        const homeRect = homeLink?.getBoundingClientRect();
        const visibleComposerControls = ['petControl', 'dockPlusBtn', 'sendBtn']
          .map((id) => document.getElementById(id))
          .filter((element) => element && !element.classList.contains('hidden'))
          .map((element) => {
            const rect = element.getBoundingClientRect();
            return { id: element.id, width: Math.round(rect.width), height: Math.round(rect.height) };
          });
        const katexCount = output?.querySelectorAll('.katex').length || 0;
        const displayCount = output?.querySelectorAll('.katex-display').length || 0;
        const katexErrorCount = output?.querySelectorAll('.katex-error').length || 0;
        const markdownCount = output?.querySelectorAll('.markdown-body').length || 0;
        const tableCount = output?.querySelectorAll('.markdown-body table').length || 0;
        const tableKatexCount = output?.querySelectorAll('.markdown-body table .katex').length || 0;
        const protectedLinkCount = output?.querySelectorAll('a[data-faryo-fetch-href]').length || 0;
        const protectedImageCount = output?.querySelectorAll('img[src^="blob:"]').length || 0;
        const protectedImagePendingCount = output?.querySelectorAll('img[data-faryo-fetch-src]').length || 0;
        const ownerTokenNeedle = ${JSON.stringify(smokeOwnerToken)};
        let ownerTokenDomCount = 0;
        if (ownerTokenNeedle) {
          for (const element of document.querySelectorAll('*')) {
            for (const attribute of element.attributes || []) {
              if (String(attribute.value || '').includes(ownerTokenNeedle)) ownerTokenDomCount += 1;
            }
          }
        }
        let rawMathDelimiterCount = 0;
        let bareTexParenthesisCount = 0;
        if (output) {
          const walker = document.createTreeWalker(output, NodeFilter.SHOW_TEXT);
          let node = walker.nextNode();
          while (node) {
            if (!node.parentElement?.closest('pre, code, .katex, .math-ignore')) {
              const value = String(node.nodeValue || '');
              if (/(?:\\\\\[|\\\\\]|\\\\\(|\\\\\)|\$\$)/.test(value)) rawMathDelimiterCount += 1;
              if (/\\((?=[^\\n)]{0,240}\\\\[A-Za-z])/.test(value)) bareTexParenthesisCount += 1;
            }
            node = walker.nextNode();
          }
        }
        const katexAssetUrls = performance.getEntriesByType('resource')
          .map((entry) => String(entry.name || ''))
          .filter((url) => /(?:\\/vendor\\/katex\\/|cdn\\.jsdelivr\\.net\\/npm\\/katex)/i.test(url));
        const markdownAssetUrls = performance.getEntriesByType('resource')
          .map((entry) => String(entry.name || ''))
          .filter((url) => /(?:\\/vendor\\/markdown-ast\\/|cdn\\.jsdelivr\\.net\\/npm\\/(?:micromark|mdast|katex))/i.test(url));
        const eventResourceUrls = performance.getEntriesByType('resource')
          .map((entry) => String(entry.name || ''))
          .filter((url) => /\\/api\\/events(?:\\?|$)/i.test(url));
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
          domReady: Boolean(output && document.getElementById('promptInput') && document.documentElement.dataset.faryoAppReady === '1' && document.documentElement.dataset.faryoClipboardPaste === 'ready'),
          ready: katexCount >= ${minKatex} && displayCount >= ${minDisplay} && markdownCount >= 1,
          katexCount,
          displayCount,
          katexErrorCount,
          rawMathDelimiterCount,
          bareTexParenthesisCount,
          markdownCount,
          tableCount,
          tableKatexCount,
          protectedLinkCount,
          protectedImageCount,
          protectedImagePendingCount,
          ownerTokenDomCount,
          ownerTokenInLocation: Boolean(ownerTokenNeedle && (location.href.includes(ownerTokenNeedle) || new URL(location.href).searchParams.has('token'))),
          ownerTokenEventUrlCount: ownerTokenNeedle ? eventResourceUrls.filter((url) => url.includes(ownerTokenNeedle) || new URL(url).searchParams.has('token')).length : 0,
          memoryReferenceCount: output?.querySelectorAll('.memory-reference-card').length || 0,
          rawMemoryTagCount: (String(output?.innerText || '').match(/<\\/?oai-mem-citation\\b/gi) || []).length,
          renderFallbackCount: output?.querySelectorAll('.rich-render-fallback, .capture-render-fallback').length || 0,
          captureSource: String(output?.dataset.captureSource || ''),
          captureWarningCount: output?.querySelectorAll('.compact-capture-warning').length || 0,
          stableBlockState: {
            apiReady: typeof window.FaryoStableBlocks?.reconcile === 'function',
            keyedCount: output?.querySelectorAll('[data-faryo-block-key]').length || 0,
            created: Number(output?.dataset.compactCreated || -1),
            reused: Number(output?.dataset.compactReused || -1),
            stable: Number(output?.dataset.compactStable || -1),
          },
          richBlockState: {
            rendered: output?.querySelectorAll(':scope > [data-faryo-rich-state="rendered"]').length || 0,
            deferred: output?.querySelectorAll(':scope > [data-faryo-rich-state="deferred"]').length || 0,
            descendants: output?.querySelectorAll('*').length || 0,
          },
          questionNavigation: {
            markerCount: questionMarkers.length,
            loadedQuestionCount: output?.querySelectorAll('.compact-block.user').length || 0,
            unloadedMarkerCount: questionMarkers.filter((marker) => marker.classList.contains('unloaded')).length,
            historyRequestCount: historyRequests.length,
            historyRequestKinds: historyRequests,
            current: String(document.getElementById('questionNavCurrent')?.textContent || ''),
            total: String(document.getElementById('questionNavTotal')?.textContent || ''),
            available: Boolean(questionNavigator && !questionNavigator.classList.contains('hidden') && questionNavigator.getClientRects().length),
            shown: Boolean(questionNavigator && Number.parseFloat(getComputedStyle(questionNavigator).opacity) > 0.5),
            balancedPadding: Boolean(outputWrap && Math.abs(
              Number.parseFloat(getComputedStyle(outputWrap).paddingLeft)
              - Number.parseFloat(getComputedStyle(outputWrap).paddingRight)
            ) < 1),
          },
          viewport: { width: innerWidth, height: innerHeight },
          pageHorizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
          outputHorizontalOverflow: Boolean(outputWrap && outputWrap.scrollWidth > outputWrap.clientWidth + 1),
          ownerLayout: {
            ui: String(document.documentElement.dataset.faryoUi || ''),
            outputWidth: Math.round(output?.getBoundingClientRect().width || 0),
            home: homeLink && homeRect ? {
              path: new URL(homeLink.href, location.href).pathname,
              search: new URL(homeLink.href, location.href).search,
              sameOrigin: new URL(homeLink.href, location.href).origin === location.origin,
              target: homeLink.target,
              width: Math.round(homeRect.width),
              height: Math.round(homeRect.height),
            } : null,
            prompt: promptRect ? {
              left: Math.round(promptRect.left),
              right: Math.round(promptRect.right),
              width: Math.round(promptRect.width),
              height: Math.round(promptRect.height),
            } : null,
            visibleComposerControls,
            statusCollapsed: Boolean(statusLine?.classList.contains('collapsed')),
            statusAutoExpanded: Boolean(statusLine?.classList.contains('auto-expanded')),
            interactionVisible: Boolean(interaction && interaction.getClientRects().length),
            interactionKind: String(interaction?.dataset.interactionKind || ''),
            livePanel: livePanel ? { open: Boolean(livePanel.open), session: String(livePanel.dataset.session || '') } : null,
            weeklyQuota: {
              label: String(document.getElementById('quotaText')?.textContent || '').trim(),
              details: String(document.getElementById('detailsQuota')?.textContent || '').trim(),
              title: String(document.getElementById('quotaTop')?.title || '').trim(),
            },
            contextStatus: {
              label: String(document.getElementById('ctxText')?.textContent || '').trim(),
              details: String(document.getElementById('detailsContext')?.textContent || '').trim(),
              title: String(document.getElementById('ctxText')?.title || '').trim(),
            },
            goalStatus: {
              visible: (() => { const item = document.getElementById('goalPill'); return Boolean(item && !item.hidden && item.getClientRects().length); })(),
              label: String(document.getElementById('goalPill')?.textContent || '').trim(),
              details: String(document.getElementById('detailsGoal')?.textContent || '').trim(),
              className: String(document.getElementById('goalPill')?.className || ''),
              title: String(document.getElementById('goalPill')?.title || '').trim(),
              modelVisible: (() => { const item = document.getElementById('modelText'); return Boolean(item && item.getClientRects().length); })(),
              objectiveLeak: [
                document.getElementById('goalPill')?.textContent,
                document.getElementById('goalPill')?.title,
                document.getElementById('detailsGoal')?.textContent,
              ].some((value) => String(value || '').includes('anonymous fixture objective must stay private')),
            },
            sessionTitleMatches: !${JSON.stringify(expectedSessionTitle)} || (
              String(document.getElementById('detailsSession')?.textContent || '').trim() === ${JSON.stringify(expectedSessionTitle)}
              && String(document.getElementById('sessionTitle')?.title || '').includes(${JSON.stringify(expectedSessionTitle)})
            ),
            canonicalSession: new URLSearchParams(location.search).get('session') || '',
          },
          katexStylesheetLoaded: [...document.styleSheets].some((sheet) => String(sheet.href || '').includes('/katex')),
          katexAssetUrls: ${JSON.stringify(privacySafe)}
            ? katexAssetUrls.map((url) => new URL(url).pathname)
            : katexAssetUrls,
          katexAssetsLocal: katexAssetUrls.some((url) => new URL(url).pathname.endsWith('/vendor/katex/katex.min.css'))
            && katexAssetUrls.every((url) => new URL(url).origin === location.origin),
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
    const protectedResourcesReady = state.protectedLinkCount >= minProtectedLinks
      && state.protectedImageCount >= minProtectedImages
      && state.protectedImagePendingCount === 0
      && state.memoryReferenceCount >= minMemoryReferences
      && state.renderFallbackCount >= minRenderFallbacks;
    const questionNavigationReady = state.questionNavigation?.markerCount >= minQuestionMarkers;
    const canonicalSessionReady = !expectedCanonicalSession
      || state.ownerLayout?.canonicalSession === expectedCanonicalSession;
    if (skipRenderChecks
      ? state.domReady && (!checkOwnerLayout || state.stableBlockState?.keyedCount >= 1) && protectedResourcesReady && questionNavigationReady && canonicalSessionReady
      : state.ready && protectedResourcesReady && questionNavigationReady && canonicalSessionReady) break;
  }

  const protectedResourcesReady = state.protectedLinkCount >= minProtectedLinks
    && state.protectedImageCount >= minProtectedImages
    && state.protectedImagePendingCount === 0
    && state.memoryReferenceCount >= minMemoryReferences
    && state.renderFallbackCount >= minRenderFallbacks;
  const questionNavigationReady = state.questionNavigation?.markerCount >= minQuestionMarkers;
  const canonicalSessionReady = !expectedCanonicalSession
    || state.ownerLayout?.canonicalSession === expectedCanonicalSession;
  if (!(skipRenderChecks
    ? state.domReady && (!checkOwnerLayout || state.stableBlockState?.keyedCount >= 1) && protectedResourcesReady && questionNavigationReady && canonicalSessionReady
    : state.ready && protectedResourcesReady && questionNavigationReady && canonicalSessionReady)) {
    throw new Error(`KaTeX did not appear in the live Faryo DOM: ${JSON.stringify(state)}`);
  }
  if (state.ownerTokenDomCount) {
    throw new Error(`Owner token appeared in ${state.ownerTokenDomCount} DOM attributes`);
  }
  if (expectedSessionTitle && !state.ownerLayout?.sessionTitleMatches) {
    throw new Error('Owner session title did not match the expected Codex thread name');
  }
  if (expectedCanonicalSession && state.ownerLayout?.canonicalSession !== expectedCanonicalSession) {
    throw new Error('Owner did not canonicalize the active Codex thread URL');
  }
  if (state.ownerTokenInLocation || state.ownerTokenEventUrlCount) {
    throw new Error(`Owner token remained in browser navigation or event-stream URLs: ${JSON.stringify({ location: state.ownerTokenInLocation, eventUrls: state.ownerTokenEventUrlCount })}`);
  }
  if (state.rawMemoryTagCount) {
    throw new Error(`Internal memory citation markup remained visible in ${state.rawMemoryTagCount} text nodes`);
  }
  if (minQuestionMarkers > 0 && (!state.questionNavigation?.available
    || !state.questionNavigation?.balancedPadding
    || state.questionNavigation?.shown
    || Number(state.questionNavigation?.total || 0) < minQuestionMarkers)) {
    throw new Error(`Question navigator did not match the structured history: ${JSON.stringify(state.questionNavigation)}`);
  }
  if (minQuestionMarkers > 0) {
    console.log(`faryo-browser-question-navigation-live=PASS markers=${state.questionNavigation.markerCount}`);
  }
  if (checkRefreshLatest) {
    await send('Runtime.evaluate', {
      expression: `(() => {
        history.scrollRestoration = 'auto';
        sessionStorage.setItem('faryoSmokeReloadLatest', String(Date.now()));
        const scroller = document.getElementById('outputWrap');
        const scrollTopDescriptor = Object.getOwnPropertyDescriptor(Element.prototype, 'scrollTop');
        window.__faryoQuestionScrollAssignments = [];
        Object.defineProperty(scroller, 'scrollTop', {
          configurable: true,
          get() { return scrollTopDescriptor.get.call(this); },
          set(value) {
            window.__faryoQuestionScrollAssignments.push({ value, stack: new Error().stack });
            scrollTopDescriptor.set.call(this, value);
          },
        });
        if (scroller) scroller.scrollTop = 0;
      })()`,
    });
    await send('Page.reload', { ignoreCache: true });
    let refreshedLatest = {};
    for (let attempt = 0; attempt < 160; attempt += 1) {
      await delay(100);
      try {
        const result = await send('Runtime.evaluate', {
          expression: `(() => {
            const scroller = document.getElementById('outputWrap');
            const output = document.getElementById('output');
            const maximum = scroller ? Math.max(0, scroller.scrollHeight - scroller.clientHeight) : 0;
            const distance = scroller ? Math.max(0, maximum - scroller.scrollTop) : -1;
            return {
              appReady: document.documentElement.dataset.faryoAppReady === '1',
              reloadMarker: Boolean(sessionStorage.getItem('faryoSmokeReloadLatest')),
              structured: ['codex-jsonl', 'codex-app-server'].includes(String(output?.dataset.captureSource || '')),
              questionKeys: output?.querySelectorAll('[data-faryo-question-key]').length || 0,
              scrollable: Boolean(scroller && maximum > 100),
              distance,
              atBottom: distance <= 4,
              latestButtonHidden: document.getElementById('bottomBtn')?.classList.contains('hidden') || false,
            };
          })()`,
          returnByValue: true,
        });
        if (result.exceptionDetails) continue;
        refreshedLatest = result.result?.value || {};
      } catch (_error) {
        refreshedLatest = {};
      }
      if (refreshedLatest.appReady && refreshedLatest.structured && refreshedLatest.questionKeys
        && refreshedLatest.scrollable && refreshedLatest.atBottom) break;
    }
    await delay(650);
    const settledResult = await send('Runtime.evaluate', {
      expression: `(() => {
        const scroller = document.getElementById('outputWrap');
        const maximum = scroller ? Math.max(0, scroller.scrollHeight - scroller.clientHeight) : 0;
        const distance = scroller ? Math.max(0, maximum - scroller.scrollTop) : -1;
        return { distance, atBottom: distance <= 4, latestButtonHidden: document.getElementById('bottomBtn')?.classList.contains('hidden') || false };
      })()`,
      returnByValue: true,
    });
    const settledLatest = settledResult.result?.value || {};
    if (!refreshedLatest.appReady || !refreshedLatest.reloadMarker || !refreshedLatest.structured
      || !refreshedLatest.questionKeys || !refreshedLatest.scrollable || !refreshedLatest.atBottom
      || !settledLatest.atBottom || !settledLatest.latestButtonHidden) {
      throw new Error(`Reload did not settle at the latest conversation output: ${JSON.stringify({ refreshedLatest, settledLatest })}`);
    }
    const manualSetup = await send('Runtime.evaluate', {
      expression: `(() => {
        const scroller = document.getElementById('outputWrap');
        const maximum = scroller ? Math.max(0, scroller.scrollHeight - scroller.clientHeight) : 0;
        const target = Math.max(1, Math.round(maximum * 0.3));
        scroller?.dispatchEvent(new WheelEvent('wheel', { deltaY: -240, bubbles: true }));
        if (scroller) scroller.scrollTop = target;
        window.__faryoRefreshManualTarget = target;
        document.getElementById('detailsRefreshBtn')?.click();
        return { maximum, target };
      })()`,
      returnByValue: true,
    });
    await delay(1200);
    const manualResult = await send('Runtime.evaluate', {
      expression: `(() => {
        const scroller = document.getElementById('outputWrap');
        const target = Number(window.__faryoRefreshManualTarget || 0);
        const maximum = scroller ? Math.max(0, scroller.scrollHeight - scroller.clientHeight) : 0;
        return { target, scrollTop: scroller?.scrollTop || 0, delta: Math.abs((scroller?.scrollTop || 0) - target), nearBottom: Boolean(scroller && maximum - scroller.scrollTop < 80) };
      })()`,
      returnByValue: true,
    });
    const manual = manualResult.result?.value || {};
    if (Number(manualSetup.result?.value?.maximum || 0) <= 100 || !manual.target
      || manual.delta > 2 || manual.nearBottom) {
      throw new Error(`Manual reading position moved after refresh: ${JSON.stringify(manual)}`);
    }
    console.log('faryo-browser-refresh-latest=PASS reload=bottom settled=bottom manual=preserved');
  }
  if (expectedHistoryTurns > 0) {
    if ((requireDeferredRichBlocks && Number(state.richBlockState?.deferred || 0) < 1)
      || (maxInitialRichBlocks > 0 && Number(state.richBlockState?.rendered || 0) > maxInitialRichBlocks)) {
      throw new Error(`Long-history rich DOM was not bounded: ${JSON.stringify(state.richBlockState)}`);
    }
    const initialLoaded = Number(state.questionNavigation?.loadedQuestionCount || 0);
    if (state.questionNavigation?.markerCount !== expectedHistoryTurns
      || Number(state.questionNavigation?.total || 0) !== expectedHistoryTurns
      || initialLoaded <= 0 || initialLoaded >= expectedHistoryTurns
      || Number(state.questionNavigation?.unloadedMarkerCount || 0) < 1
      || state.questionNavigation?.historyRequestKinds?.filter((kind) => kind === 'latest').length !== 1) {
      throw new Error(`Full-history index did not stay paged: ${JSON.stringify(state.questionNavigation)}`);
    }
    await delay(150);
    await send('Runtime.evaluate', {
      expression: `(() => {
        const scroller = document.getElementById('outputWrap');
        scroller.dispatchEvent(new WheelEvent('wheel', { deltaY: -120, bubbles: true }));
        scroller.scrollTop = 0;
        const anchor = document.querySelector('#output > [data-faryo-block-key]');
        window.__faryoHistoryAnchor = anchor ? {
          key: anchor.dataset.faryoBlockKey,
          top: anchor.getBoundingClientRect().top,
        } : null;
        window.__faryoHistoryAnchorTimeline = [];
        let samples = 0;
        const sampleAnchor = () => {
          const target = anchor?.dataset.faryoBlockKey
            ? [...document.querySelectorAll('#output > [data-faryo-block-key]')]
              .find((item) => item.dataset.faryoBlockKey === anchor.dataset.faryoBlockKey)
            : null;
          window.__faryoHistoryAnchorTimeline.push({
            frame: samples,
            top: target ? Math.round(target.getBoundingClientRect().top) : null,
            scrollTop: Math.round(scroller.scrollTop),
            blocks: document.querySelectorAll('#output > [data-faryo-block-key]').length,
          });
          samples += 1;
          if (samples < 24) requestAnimationFrame(sampleAnchor);
        };
        requestAnimationFrame(sampleAnchor);
        scroller.dispatchEvent(new Event('scroll'));
      })()`,
    });
    let preloadedHistory = {};
    for (let attempt = 0; attempt < 120; attempt += 1) {
      await delay(100);
      const result = await send('Runtime.evaluate', {
        expression: `(() => {
          const anchor = window.__faryoHistoryAnchor;
          const target = anchor ? [...document.querySelectorAll('#output > [data-faryo-block-key]')]
            .find((item) => item.dataset.faryoBlockKey === anchor.key) : null;
          const requests = performance.getEntriesByType('resource').map((entry) => String(entry.name || ''));
          const anchorDelta = target && anchor ? target.getBoundingClientRect().top - anchor.top : null;
          return {
            loadedQuestionCount: document.querySelectorAll('#output .compact-block.user').length,
            cursorRequest: requests.some((url) => url.includes('/api/conversation-history') && /[?&]cursor=/.test(url)),
            anchorPreserved: Boolean(target && Math.abs(anchorDelta) <= 3),
            anchorDelta,
            anchorState: target?.dataset.faryoRichState || '',
            anchorTop: target ? Math.round(target.getBoundingClientRect().top) : null,
            anchorHeight: target ? Math.round(target.getBoundingClientRect().height) : null,
            precedingBlocks: target ? [...target.parentElement.children].indexOf(target) : -1,
            deferredBlocks: document.querySelectorAll('#output > [data-faryo-rich-state="deferred"]').length,
            anchorTimeline: window.__faryoHistoryAnchorTimeline || [],
            scrollTop: document.getElementById('outputWrap')?.scrollTop || 0,
          };
        })()`,
        returnByValue: true,
      });
      preloadedHistory = result.result?.value || {};
      if (preloadedHistory.loadedQuestionCount > initialLoaded
        && preloadedHistory.cursorRequest && preloadedHistory.anchorPreserved) break;
    }
    if (preloadedHistory.loadedQuestionCount <= initialLoaded
      || !preloadedHistory.cursorRequest || !preloadedHistory.anchorPreserved) {
      throw new Error(`Full-history top preload failed: ${JSON.stringify(preloadedHistory)}`);
    }
    const needsAroundRequest = preloadedHistory.loadedQuestionCount < expectedHistoryTurns;
    await send('Runtime.evaluate', {
      expression: `document.querySelector('#questionNavMarkers .question-nav-marker')?.click()`,
    });
    let loadedHistory = {};
    for (let attempt = 0; attempt < 120; attempt += 1) {
      await delay(100);
      const result = await send('Runtime.evaluate', {
        expression: `(() => {
          const markers = [...document.querySelectorAll('#questionNavMarkers .question-nav-marker')];
          const first = markers[0];
          const key = first?.dataset.questionKey || '';
          const target = [...document.querySelectorAll('#output .compact-block.user')]
            .find((item) => item.dataset.faryoQuestionKey === key);
          const answer = target?.nextElementSibling?.classList.contains('output') ? target.nextElementSibling : null;
          const historyRequests = performance.getEntriesByType('resource')
            .map((entry) => String(entry.name || ''))
            .filter((url) => url.includes('/api/conversation-history'));
          return {
            markerCount: markers.length,
            loadedQuestionCount: document.querySelectorAll('#output .compact-block.user').length,
            firstLoaded: Boolean(first && !first.classList.contains('unloaded') && target),
            firstActive: first?.getAttribute('aria-current') === 'step',
            formulaRendered: Boolean(answer?.querySelector('.katex')),
            targetState: target?.dataset.faryoRichState || '',
            answerState: answer?.dataset.faryoRichState || '',
            nextBlocks: target ? [...document.querySelectorAll('#output > *')]
              .slice([...document.querySelectorAll('#output > *')].indexOf(target), [...document.querySelectorAll('#output > *')].indexOf(target) + 5)
              .map((item) => ({ className: item.className, state: item.dataset.faryoRichState || '' })) : [],
            activeIndex: document.querySelector('#questionNavMarkers .question-nav-marker[aria-current="step"]')?.dataset.questionIndex || '',
            targetTop: target ? Math.round(target.getBoundingClientRect().top) : null,
            scrollTop: Math.round(document.getElementById('outputWrap')?.scrollTop || 0),
            aroundRequest: historyRequests.some((url) => /[?&]around=0(?:&|$)/.test(url)),
            pageHorizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
          };
        })()`,
        returnByValue: true,
      });
      loadedHistory = result.result?.value || {};
      if (loadedHistory.firstLoaded && loadedHistory.firstActive
        && (!historyRequiresFormula || loadedHistory.formulaRendered)) break;
    }
    if (!loadedHistory.firstLoaded || !loadedHistory.firstActive
      || (historyRequiresFormula && !loadedHistory.formulaRendered)
      || (needsAroundRequest && !loadedHistory.aroundRequest) || loadedHistory.pageHorizontalOverflow
      || loadedHistory.markerCount !== expectedHistoryTurns
      || (needsAroundRequest
        ? loadedHistory.loadedQuestionCount <= preloadedHistory.loadedQuestionCount
        : loadedHistory.loadedQuestionCount < preloadedHistory.loadedQuestionCount)) {
      throw new Error(`Full-history lazy loading failed: ${JSON.stringify(loadedHistory)}`);
    }
    let finalHistory = loadedHistory;
    if (loadedHistory.loadedQuestionCount < expectedHistoryTurns) {
      await send('Runtime.evaluate', {
        expression: `document.querySelector('#questionNavMarkers .question-nav-marker.unloaded')?.click()`,
      });
      for (let attempt = 0; attempt < 120; attempt += 1) {
        await delay(100);
        const result = await send('Runtime.evaluate', {
          expression: `(() => ({
            markerCount: document.querySelectorAll('#questionNavMarkers .question-nav-marker').length,
            unloadedMarkerCount: document.querySelectorAll('#questionNavMarkers .question-nav-marker.unloaded').length,
            loadedQuestionCount: document.querySelectorAll('#output .compact-block.user').length,
          }))()`,
          returnByValue: true,
        });
        finalHistory = result.result?.value || {};
        if (finalHistory.loadedQuestionCount === expectedHistoryTurns && finalHistory.unloadedMarkerCount === 0) break;
      }
    }
    if (finalHistory.markerCount !== expectedHistoryTurns
      || finalHistory.loadedQuestionCount !== expectedHistoryTurns
      || finalHistory.unloadedMarkerCount !== 0) {
      throw new Error(`Full-history eventual completeness failed: ${JSON.stringify(finalHistory)}`);
    }
    console.log(`faryo-browser-full-history=PASS total=${expectedHistoryTurns} initial=${initialLoaded} preloaded=${preloadedHistory.loadedQuestionCount} loaded=${finalHistory.loadedQuestionCount} lazy-oldest=PASS`);
    if (checkLongHistoryResize) {
      await delay(900);
      await send('Runtime.evaluate', {
        expression: `(() => {
          const profile = window.__faryoRapidScrollProfile = {
            startedAt: 0, endedAt: 0, frameGaps: [], longTasks: [], richChanges: 0,
          };
          const scroller = document.getElementById('outputWrap');
          scroller.scrollTop = scroller.scrollHeight;
          profile.startedAt = performance.now();
          let previous = profile.startedAt;
          const deadline = previous + 4000;
          const tick = (now) => {
            profile.frameGaps.push({ at: now, gap: now - previous });
            previous = now;
            if (now < deadline) requestAnimationFrame(tick);
          };
          requestAnimationFrame(tick);
          profile.taskObserver = new PerformanceObserver((list) => {
            for (const entry of list.getEntries()) profile.longTasks.push({ startTime: entry.startTime, duration: entry.duration });
          });
          profile.taskObserver.observe({ entryTypes: ['longtask'] });
          profile.richObserver = new MutationObserver((records) => { profile.richChanges += records.length; });
          profile.richObserver.observe(document.getElementById('output'), {
            attributes: true, attributeFilter: ['data-faryo-rich-state'], subtree: true,
          });
        })()`,
      });
      let rapidScrollEvents = 0;
      for (let index = 0; index < 240; index += 1) {
        await send('Input.dispatchMouseEvent', {
          type: 'mouseWheel',
          x: Math.max(20, Math.round((viewportWidth || 390) / 2)),
          y: Math.max(80, Math.round((viewportHeight || 844) / 2)),
          deltaX: 0,
          deltaY: -420,
        });
        rapidScrollEvents += 1;
        await delay(8);
        if (index % 8 === 7) {
          const reached = await send('Runtime.evaluate', {
            expression: `document.getElementById('outputWrap')?.scrollTop <= 1`,
            returnByValue: true,
          });
          if (reached.result?.value) break;
        }
      }
      await send('Runtime.evaluate', { expression: `window.__faryoRapidScrollProfile.endedAt = performance.now()` });
      await delay(500);
      const rapidResult = await send('Runtime.evaluate', {
        expression: `(() => {
          const profile = window.__faryoRapidScrollProfile;
          profile.taskObserver?.disconnect();
          profile.richObserver?.disconnect();
          const tasks = profile.longTasks.filter((entry) => entry.startTime <= profile.endedAt && entry.startTime + entry.duration >= profile.startedAt);
          const frames = profile.frameGaps.filter((entry) => entry.at >= profile.startedAt && entry.at <= profile.endedAt + 34);
          return {
            scrollTop: Math.round(document.getElementById('outputWrap')?.scrollTop || 0),
            richChanges: profile.richChanges,
            longTasks: tasks.length,
            maxLongTask: Math.round(Math.max(0, ...tasks.map((entry) => entry.duration))),
            framesOver50: frames.filter((entry) => entry.gap > 50).length,
            maxFrame: Math.round(Math.max(0, ...frames.map((entry) => entry.gap))),
          };
        })()`,
        returnByValue: true,
      });
      const rapid = rapidResult.result?.value || {};
      if (rapid.scrollTop > 1 || rapid.richChanges > 24 || rapid.maxLongTask > 100
        || rapid.framesOver50 > 2 || rapid.maxFrame > 100) {
        throw new Error(`Long-history rapid-scroll budget failed: ${JSON.stringify(rapid)}`);
      }
      console.log(`faryo-browser-long-history-scroll=PASS events=${rapidScrollEvents} rich-changes=${rapid.richChanges} max-long-task=${rapid.maxLongTask}ms max-frame=${rapid.maxFrame}ms`);

      await send('Runtime.evaluate', {
        expression: `(() => {
          window.__faryoResizeLongTasks = [];
          window.__faryoResizeObserver = new PerformanceObserver((list) => {
            for (const entry of list.getEntries()) window.__faryoResizeLongTasks.push(Math.round(entry.duration));
          });
          window.__faryoResizeObserver.observe({ entryTypes: ['longtask'] });
        })()`,
      });
      const resizeSteps = [
        [390, 844, 1], [430, 820, 1.25], [680, 760, 1], [920, 780, 1.5],
        [1440, 900, 1], [1080, 820, 1.25], [760, 760, 1], [390, 844, 1],
      ];
      for (let cycle = 0; cycle < 3; cycle += 1) {
        for (const [width, height, deviceScaleFactor] of resizeSteps) {
          await send('Emulation.setDeviceMetricsOverride', {
            width, height, deviceScaleFactor, mobile: width < 720,
          });
          await delay(24);
        }
      }
      await delay(500);
      const resizeResult = await send('Runtime.evaluate', {
        expression: `(() => {
          window.__faryoResizeObserver?.disconnect();
          const tasks = window.__faryoResizeLongTasks || [];
          const output = document.getElementById('output');
          return {
            rendered: output?.querySelectorAll(':scope > [data-faryo-rich-state="rendered"]').length || 0,
            deferred: output?.querySelectorAll(':scope > [data-faryo-rich-state="deferred"]').length || 0,
            descendants: output?.querySelectorAll('*').length || 0,
            markerCount: document.querySelectorAll('#questionNavMarkers .question-nav-marker').length,
            longTasks: tasks.length,
            maxLongTask: Math.max(0, ...tasks),
            horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
          };
        })()`,
        returnByValue: true,
      });
      const resized = resizeResult.result?.value || {};
      if (resized.rendered > 14 || resized.deferred < 1 || resized.descendants > 12000
        || resized.markerCount !== expectedHistoryTurns || resized.maxLongTask > 400
        || resized.horizontalOverflow) {
        throw new Error(`Long-history resize budget failed: ${JSON.stringify(resized)}`);
      }
      console.log(`faryo-browser-long-history-resize=PASS rendered=${resized.rendered} deferred=${resized.deferred} descendants=${resized.descendants} max-long-task=${resized.maxLongTask}ms`);
    }
  }
  if (checkOwnerLayout) {
    const layout = state.ownerLayout || {};
    const prompt = layout.prompt;
    if (layout.ui !== 'workbench-v2') throw new Error(`Unexpected Owner UI version: ${JSON.stringify(layout.ui)}`);
    if (state.pageHorizontalOverflow || state.outputHorizontalOverflow) {
      throw new Error(`Owner layout caused page-level horizontal overflow: ${JSON.stringify({ viewport: state.viewport, layout })}`);
    }
    if (!prompt || prompt.left < 7 || prompt.right > state.viewport.width - 7) {
      throw new Error(`Owner composer escaped the viewport: ${JSON.stringify({ viewport: state.viewport, prompt })}`);
    }
    if (!layout.home || layout.home.path !== '/' || layout.home.search
      || !layout.home.sameOrigin || layout.home.target
      || layout.home.width < 32 || layout.home.height < 32) {
      throw new Error(`Owner home link is missing or unsafe: ${JSON.stringify(layout.home)}`);
    }
    if (state.viewport.width < 720 && prompt.width < state.viewport.width - 24) {
      throw new Error(`Mobile Owner composer is unexpectedly narrow: ${JSON.stringify({ viewport: state.viewport, prompt })}`);
    }
    if (!/^Week (?:--|\d+(?:\.\d+)?% left)$/.test(layout.weeklyQuota?.label || '')
      || !layout.weeklyQuota?.details || !layout.weeklyQuota?.title) {
      throw new Error(`Owner weekly quota status is not explicit: ${JSON.stringify(layout.weeklyQuota)}`);
    }
    if (!/^Ctx (?:--|\d+(?:\.\d+)?%(?: · \d+(?:\.\d+)?[km]?\/\d+(?:\.\d+)?[km]?)?)$/.test(layout.contextStatus?.label || '')
      || !layout.contextStatus?.details) {
      throw new Error(`Owner context status is not explicit: ${JSON.stringify(layout.contextStatus)}`);
    }
    if (expectedGoalStatus) {
      if (expectedGoalStatus === 'none') {
        if (layout.goalStatus?.visible || layout.goalStatus?.label || layout.goalStatus?.details !== 'No goal'
          || layout.goalStatus?.objectiveLeak) {
          throw new Error(`Owner empty goal status is wrong: ${JSON.stringify(layout.goalStatus)}`);
        }
      } else {
        const expected = {
          active: { label: 'Goal Active', detail: 'Active', className: 'goal-active' },
          blocked: { label: 'Goal Blocked', detail: 'Blocked', className: 'goal-blocked' },
          complete: { label: 'Goal Done', detail: 'Complete', className: 'goal-complete' },
          paused: { label: 'Goal Paused', detail: 'Paused', className: 'goal-paused' },
          usage_limited: { label: 'Goal Limited', detail: 'Usage limited', className: 'goal-limited' },
        }[expectedGoalStatus];
        if (!expected || !layout.goalStatus?.visible || layout.goalStatus.label !== expected.label
          || !layout.goalStatus.details.startsWith(expected.detail)
          || !layout.goalStatus.className.includes(expected.className)
          || !layout.goalStatus.title.startsWith('Goal status · ')
          || (state.viewport.width <= 420 ? layout.goalStatus.modelVisible : !layout.goalStatus.modelVisible)
          || layout.goalStatus.objectiveLeak) {
          throw new Error(`Owner goal status is missing or wrong: ${JSON.stringify({ expectedGoalStatus, goalStatus: layout.goalStatus })}`);
        }
      }
    }
    if (prompt.height < 82) throw new Error(`Owner composer is unexpectedly short: ${JSON.stringify(prompt)}`);
    if (layout.outputWidth > 752) throw new Error(`Owner reading column is too wide: ${JSON.stringify(layout)}`);
    if (!state.stableBlockState?.apiReady || state.stableBlockState.keyedCount < 1 || state.stableBlockState.created < 0) {
      throw new Error(`Owner did not use stable Compact Chat blocks: ${JSON.stringify(state.stableBlockState)}`);
    }
    if (expectedLivePanelState) {
      const expectedOpen = expectedLivePanelState === 'open';
      if (!layout.livePanel || layout.livePanel.open !== expectedOpen) {
        throw new Error(`Owner Live from tmux panel state is wrong: ${JSON.stringify({ expectedLivePanelState, livePanel: layout.livePanel })}`);
      }
    }
    const undersizedControls = (layout.visibleComposerControls || []).filter((item) => item.width < 42 || item.height < 42);
    if (undersizedControls.length) throw new Error(`Owner composer controls are too small: ${JSON.stringify(undersizedControls)}`);
    const expectInteractionVisible = expectedInteractionState === 'visible';
    if (!layout.statusCollapsed || layout.interactionVisible !== expectInteractionVisible) {
      throw new Error(`Owner structured interaction visibility is wrong: ${JSON.stringify({ expectedInteractionState, layout })}`);
    }
    const attachmentStripResult = await send('Runtime.evaluate', {
      expression: `(() => {
        const preview = document.getElementById('attachmentPreview');
        const statusLine = document.querySelector('.status-line');
        if (!preview || !statusLine) return { ready: false };
        statusLine.classList.add('auto-expanded');
        preview.classList.remove('hidden');
        preview.replaceChildren(...Array.from({ length: 35 }, (_value, index) => {
          const item = document.createElement('button');
          item.type = 'button';
          item.className = 'attachment-thumb file';
          item.textContent = String(index + 1);
          return item;
        }));
        const state = {
          ready: true,
          count: preview.children.length,
          overflowX: getComputedStyle(preview).overflowX,
          scrollable: preview.scrollWidth > preview.clientWidth,
          pageOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
        };
        preview.replaceChildren();
        preview.classList.add('hidden');
        statusLine.classList.remove('auto-expanded');
        return state;
      })()`,
      returnByValue: true,
    });
    const attachmentStrip = attachmentStripResult.result?.value || {};
    if (!attachmentStrip.ready || attachmentStrip.count !== 35 || attachmentStrip.overflowX !== 'auto'
      || !attachmentStrip.scrollable || attachmentStrip.pageOverflow) {
      throw new Error(`Owner 35-file attachment strip is not bounded: ${JSON.stringify(attachmentStrip)}`);
    }
    const measurePrompt = async (action = '') => {
      const result = await send('Runtime.evaluate', {
        expression: `(() => {
          const input = document.getElementById('promptInput');
          if (${JSON.stringify(action)} === 'focus') input?.focus();
          if (${JSON.stringify(action)} === 'blur') input?.blur();
          const rect = document.querySelector('.prompt-shell')?.getBoundingClientRect();
          return rect ? { width: Math.round(rect.width), height: Math.round(rect.height) } : null;
        })()`,
        returnByValue: true,
      });
      return result.result?.value || null;
    };
    const beforeFocus = await measurePrompt();
    await measurePrompt('focus');
    await delay(180);
    const focused = await measurePrompt();
    await measurePrompt('blur');
    await delay(260);
    const blurred = await measurePrompt();
    const geometries = [focused, blurred].filter(Boolean);
    if (!beforeFocus || geometries.some((item) => Math.abs(item.width - beforeFocus.width) > 1 || Math.abs(item.height - beforeFocus.height) > 1)) {
      throw new Error(`Owner composer changed geometry across focus/blur: ${JSON.stringify({ beforeFocus, focused, blurred })}`);
    }

    if (checkCommandSuggestions) {
      const commandResult = await send('Runtime.evaluate', {
        expression: `(async () => {
          const input = document.getElementById('promptInput');
          const popup = document.getElementById('commandSuggest');
          const shell = document.querySelector('.prompt-shell');
          if (!input || !popup || !shell) return { ready: false };
          const original = input.value;
          const shellBefore = shell.getBoundingClientRect();
          input.value = '/';
          input.dispatchEvent(new Event('input', { bubbles: true }));
          await new Promise((resolve) => setTimeout(resolve, 40));
          const buttons = [...popup.querySelectorAll('button')];
          const popupRect = popup.getBoundingClientRect();
          const firstSelected = popup.querySelector('button.selected')?.dataset.index || '';
          input.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }));
          await new Promise((resolve) => setTimeout(resolve, 20));
          const secondSelected = popup.querySelector('button.selected')?.dataset.index || '';
          input.value = '/ren';
          input.dispatchEvent(new Event('input', { bubbles: true }));
          await new Promise((resolve) => setTimeout(resolve, 20));
          input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
          const renameValue = input.value;
          input.value = original;
          input.dispatchEvent(new Event('input', { bubbles: true }));
          await new Promise((resolve) => setTimeout(resolve, 20));
          const shellAfter = shell.getBoundingClientRect();
          return {
            ready: true,
            count: buttons.length,
            hasDescriptions: buttons.every((button) => Boolean(button.querySelector('small')?.textContent)),
            hasExport: buttons.some((button) => button.textContent.includes('/export')),
            hasSubagents: buttons.some((button) => button.textContent.includes('/subagents')),
            hasYolo: buttons.some((button) => button.textContent.includes('--yolo')),
            firstSelected,
            secondSelected,
            renameValue,
            popupWithinViewport: popupRect.left >= -1 && popupRect.right <= innerWidth + 1 && popupRect.height <= innerHeight * 0.59 + 2,
            shellStable: Math.abs(shellBefore.width - shellAfter.width) <= 1 && Math.abs(shellBefore.height - shellAfter.height) <= 1,
          };
        })()`,
        awaitPromise: true,
        returnByValue: true,
      });
      const commandState = commandResult.result?.value || {};
      if (!commandState.ready || commandState.count !== 46 || !commandState.hasDescriptions
        || !commandState.hasExport || !commandState.hasSubagents || commandState.hasYolo
        || commandState.firstSelected !== '0' || commandState.secondSelected !== '1'
        || commandState.renameValue !== '/rename ' || !commandState.popupWithinViewport
        || !commandState.shellStable) {
        throw new Error(`Owner Codex command completion is wrong: ${JSON.stringify(commandState)}`);
      }
    }

    const homeInteractionResult = await send('Runtime.evaluate', {
      expression: `(() => {
        const home = document.getElementById('homeBtn');
        const title = document.getElementById('sessionTitle');
        const header = document.querySelector('header');
        if (!home || !title || !header) return { ready: false };
        const before = header.classList.contains('collapsed');
        let navigationPrevented = false;
        home.addEventListener('click', (event) => { event.preventDefault(); navigationPrevented = true; }, { once: true });
        home.click();
        const afterHome = header.classList.contains('collapsed');
        document.getElementById('ownerText')?.click();
        const afterTitle = header.classList.contains('collapsed');
        document.getElementById('ownerText')?.click();
        home.focus();
        return {
          ready: true,
          navigationPrevented,
          homePreservedHeader: afterHome === before,
          titleToggledHeader: afterTitle !== before,
          restoredHeader: header.classList.contains('collapsed') === before,
          focusedHome: document.activeElement === home,
        };
      })()`,
      returnByValue: true,
    });
    const homeInteraction = homeInteractionResult.result?.value || {};
    if (!homeInteraction.ready || !homeInteraction.navigationPrevented
      || !homeInteraction.homePreservedHeader || !homeInteraction.titleToggledHeader
      || !homeInteraction.restoredHeader || !homeInteraction.focusedHome) {
      throw new Error(`Owner home/title interaction is wrong: ${JSON.stringify(homeInteraction)}`);
    }

    const inspectPanel = async (action) => {
      const result = await send('Runtime.evaluate', {
        expression: `(() => {
          const action = ${JSON.stringify(action)};
          if (action === 'open-session') document.getElementById('draftState')?.click();
          if (action === 'close-current') document.querySelector('.surface-panel:not(.hidden) [data-close-panel]')?.click();
          if (action === 'open-details') document.getElementById('detailsBtn')?.click();
          if (action === 'escape') document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
          const panel = document.querySelector('.surface-panel:not(.hidden)');
          const rect = panel?.getBoundingClientRect();
          return {
            panelId: panel?.id || '',
            panelRect: rect ? { left: Math.round(rect.left), right: Math.round(rect.right), width: Math.round(rect.width) } : null,
            panelOpen: document.documentElement.classList.contains('panel-open'),
            backdropVisible: !document.getElementById('panelBackdrop')?.classList.contains('hidden'),
            sessionExpanded: document.getElementById('draftState')?.getAttribute('aria-expanded'),
            detailsExpanded: document.getElementById('detailsBtn')?.getAttribute('aria-expanded'),
            activeId: document.activeElement?.id || '',
            activeClosesPanel: Boolean(document.activeElement?.hasAttribute?.('data-close-panel')),
            backgroundInert: Boolean(document.getElementById('outputWrap')?.inert && document.querySelector('footer')?.inert),
          };
        })()`,
        returnByValue: true,
      });
      return result.result?.value || {};
    };

    await inspectPanel('open-session');
    await delay(80);
    const sessionPanelState = await inspectPanel('inspect');
    if (sessionPanelState.panelId !== 'sessionMenu' || !sessionPanelState.panelOpen || !sessionPanelState.backdropVisible || !sessionPanelState.backgroundInert || sessionPanelState.sessionExpanded !== 'true' || !sessionPanelState.activeClosesPanel) {
      throw new Error(`Owner session panel did not open accessibly: ${JSON.stringify(sessionPanelState)}`);
    }
    if (state.viewport.width < 720 && sessionPanelState.panelRect?.width !== state.viewport.width) {
      throw new Error(`Mobile session panel is not full width: ${JSON.stringify(sessionPanelState)}`);
    }
    await inspectPanel('close-current');
    await delay(80);
    const sessionClosedState = await inspectPanel('inspect');
    if (sessionClosedState.panelOpen || sessionClosedState.backdropVisible || sessionClosedState.activeId !== 'draftState') {
      throw new Error(`Owner session panel did not restore focus: ${JSON.stringify(sessionClosedState)}`);
    }

    await inspectPanel('open-details');
    await delay(80);
    const detailsPanelState = await inspectPanel('inspect');
    if (detailsPanelState.panelId !== 'detailsPanel' || !detailsPanelState.panelOpen || !detailsPanelState.backgroundInert || detailsPanelState.detailsExpanded !== 'true' || !detailsPanelState.activeClosesPanel) {
      throw new Error(`Owner details panel did not open accessibly: ${JSON.stringify(detailsPanelState)}`);
    }
    if (state.viewport.width < 720 && detailsPanelState.panelRect?.width !== state.viewport.width) {
      throw new Error(`Mobile details panel is not full width: ${JSON.stringify(detailsPanelState)}`);
    }
    await inspectPanel('escape');
    await delay(80);
    const detailsClosedState = await inspectPanel('inspect');
    if (detailsClosedState.panelOpen || detailsClosedState.backdropVisible || detailsClosedState.activeId !== 'detailsBtn') {
      throw new Error(`Owner details panel did not close on Escape: ${JSON.stringify(detailsClosedState)}`);
    }
    console.log(`faryo-browser-owner-layout=PASS viewport=${state.viewport.width}x${state.viewport.height} attachments=35-scrollable`);
  }
  if (minProtectedLinks > 0) {
    const startResult = await send('Runtime.evaluate', {
      expression: `(() => {
        const link = document.querySelector('#output a[data-faryo-fetch-href]');
        if (!link) return { started: false };
        const originalOpen = window.open;
        const result = { started: true, replaced: '', closed: false };
        const popup = {
          opener: window,
          document: { title: '' },
          location: { replace: (value) => { result.replaced = String(value || ''); } },
          close: () => { result.closed = true; },
        };
        window.__faryoProtectedOpenSmoke = result;
        window.open = () => popup;
        link.click();
        window.open = originalOpen;
        return result;
      })()`,
      returnByValue: true,
    });
    if (!startResult.result?.value?.started) throw new Error('Protected local file link was not available');
    let protectedOpenState = {};
    for (let attempt = 0; attempt < 100; attempt += 1) {
      await delay(100);
      const result = await send('Runtime.evaluate', {
        expression: `(() => ({
          replaced: String(window.__faryoProtectedOpenSmoke?.replaced || ''),
          closed: Boolean(window.__faryoProtectedOpenSmoke?.closed),
          errorVisible: Boolean(document.getElementById('errorBox')?.innerText),
        }))()`,
        returnByValue: true,
      });
      protectedOpenState = result.result?.value || {};
      if (protectedOpenState.replaced || protectedOpenState.closed || protectedOpenState.errorVisible) break;
    }
    if (!protectedOpenState.replaced.startsWith('blob:') || protectedOpenState.closed || protectedOpenState.errorVisible) {
      throw new Error(`Protected local file did not open through an authenticated blob: ${JSON.stringify(protectedOpenState)}`);
    }
    console.log('faryo-browser-protected-file-open=PASS transport=auth-header target=blob');
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
    if (maxBareTex >= 0 && state.bareTexParenthesisCount > maxBareTex) {
      throw new Error(`Bare TeX parentheses remained visible in ${state.bareTexParenthesisCount} text nodes`);
    }
    if (state.tableCount < minTables) {
      throw new Error(`Expected at least ${minTables} rendered Markdown tables, found ${state.tableCount}`);
    }
    if (state.tableKatexCount < minTableKatex) {
      throw new Error(`Expected at least ${minTableKatex} rendered table formulas, found ${state.tableKatexCount}`);
    }
    if (expectStructured && (!['codex-jsonl', 'codex-app-server'].includes(state.captureSource) || state.captureWarningCount)) {
      throw new Error(`Codex capture did not use structured history: source=${state.captureSource || 'missing'} warning=${state.captureWarningCount || 0}`);
    }
    if (!state.katexAssetsLocal) {
      throw new Error(`KaTeX loaded a missing or external asset: ${JSON.stringify(state.katexAssetUrls)}`);
    }
    if (!state.markdownAssetsLocal) {
      throw new Error(`AST Markdown loaded a missing or external asset: ${JSON.stringify(state.markdownAssetUrls)}`);
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

  if (checkModeSwitch) {
    const beforeMode = await send('Runtime.evaluate', {
      expression: `(() => ({source:document.getElementById('output')?.dataset.captureSource||'',compactBlocks:document.querySelectorAll('#output .compact-block').length,markdown:document.querySelectorAll('#output .markdown-body').length,atChat:document.getElementById('refreshBtn')?.classList.contains('mode-active')||false}))()`,
      returnByValue: true,
    });
    const before = beforeMode.result?.value || {};
    if (!before.atChat || !before.compactBlocks || !before.markdown) throw new Error(`Chat mode was not rich before mode switch: ${JSON.stringify(before)}`);
    await send('Runtime.evaluate', { expression: `document.getElementById('dockFullBtn').click()` });
    let raw = {};
    for (let attempt = 0; attempt < 100; attempt += 1) {
      await delay(50);
      const result = await send('Runtime.evaluate', {
        expression: `(() => ({active:document.getElementById('dockFullBtn')?.classList.contains('mode-active')||false,compactClass:document.getElementById('output')?.classList.contains('compact-blocks')||false,compactBlocks:document.querySelectorAll('#output .compact-block').length}))()`,
        returnByValue: true,
      });
      raw = result.result?.value || {};
      if (raw.active && !raw.compactClass && !raw.compactBlocks) break;
    }
    if (!raw.active || raw.compactClass || raw.compactBlocks) throw new Error(`Raw mode did not replace Compact Chat: ${JSON.stringify(raw)}`);
    const immediateResult = await send('Runtime.evaluate', {
      expression: `(() => {document.getElementById('refreshBtn').click();return{active:document.getElementById('refreshBtn')?.classList.contains('mode-active')||false,compactClass:document.getElementById('output')?.classList.contains('compact-blocks')||false,compactBlocks:document.querySelectorAll('#output .compact-block').length,markdown:document.querySelectorAll('#output .markdown-body').length,source:document.getElementById('output')?.dataset.captureSource||'',liveOpen:Boolean(document.querySelector('#output .compact-live-terminal[open]'))};})()`,
      returnByValue: true,
    });
    const immediate = immediateResult.result?.value || {};
    if (!immediate.active || !immediate.compactClass || !immediate.compactBlocks || !immediate.markdown || immediate.source !== before.source || immediate.liveOpen) {
      throw new Error(`Raw to Chat did not restore the compact cache synchronously: ${JSON.stringify({ before, immediate })}`);
    }
    let settled = immediate;
    for (let attempt = 0; attempt < 100; attempt += 1) {
      await delay(50);
      const result = await send('Runtime.evaluate', {
        expression: `(() => ({active:document.getElementById('refreshBtn')?.classList.contains('mode-active')||false,compactClass:document.getElementById('output')?.classList.contains('compact-blocks')||false,compactBlocks:document.querySelectorAll('#output .compact-block').length,markdown:document.querySelectorAll('#output .markdown-body').length,source:document.getElementById('output')?.dataset.captureSource||'',processPre:document.querySelectorAll('#output .compact-process-line pre').length,liveOpen:Boolean(document.querySelector('#output .compact-live-terminal[open]'))}))()`,
        returnByValue: true,
      });
      settled = result.result?.value || {};
      if (settled.active && settled.compactClass && settled.compactBlocks && settled.markdown && settled.source === before.source) break;
    }
    if (!settled.active || !settled.compactClass || !settled.compactBlocks || !settled.markdown || settled.source !== before.source || settled.processPre || settled.liveOpen) {
      throw new Error(`Chat mode did not remain rich after refresh: ${JSON.stringify({ before, settled })}`);
    }
    console.log(`faryo-browser-mode-switch=PASS source=${settled.source||'fallback'} raw-to-chat=rich`);
  }

  if (checkAstFixture) {
    let fixtureState = {};
    for (let attempt = 0; attempt < 100; attempt += 1) {
      await delay(100);
      const result = await send('Runtime.evaluate', {
        expression: `(() => {
          document.getElementById('faryo-ast-smoke-fixture')?.remove();
          const fixture = document.createElement('section');
          fixture.id = 'faryo-ast-smoke-fixture';
          fixture.className = 'compact-block output markdown-body';
          Object.assign(fixture.style, {
            position: 'fixed',
            left: '-200vw',
            top: '0',
            width: Math.min(740, Math.max(320, innerWidth - 20)) + 'px',
            visibility: 'hidden',
          });
          fixture.innerHTML = window.FaryoMarkdownAst.render(${JSON.stringify(astFixtureSource)});
          document.body.appendChild(fixture);
          const table = fixture.querySelector('table');
          const tableScroll = fixture.querySelector('.markdown-table-scroll');
          const formulaCells = [...fixture.querySelectorAll('tbody tr td:first-child')];
          const highlightedLanguages = [...fixture.querySelectorAll('.markdown-code-block')]
            .filter((block) => block.querySelector('pre.shiki'))
            .map((block) => block.querySelector('.markdown-code-language')?.textContent || '');
          const assetUrls = performance.getEntriesByType('resource')
            .map((entry) => String(entry.name || ''))
            .filter((url) => /\\/vendor\\/markdown-ast\\/highlight\\//i.test(url));
          const stableContainer = document.createElement('div');
          const stableInitial = window.FaryoStableBlocks.plan([
            { kind: 'user', text: 'one' },
            { kind: 'output', text: 'two' },
            { kind: 'user', text: 'three' },
            { kind: 'output', text: 'four' },
          ], { mode: 'settled', revision: 0, tailCount: 2 });
          const makeStableNode = (model) => {
            const node = document.createElement('section');
            node.textContent = model.text;
            return node;
          };
          const stableFirst = window.FaryoStableBlocks.reconcile(stableContainer, stableInitial, makeStableNode);
          const stableOriginalNodes = [...stableContainer.children];
          const stableAppended = window.FaryoStableBlocks.plan([
            { kind: 'user', text: 'one' },
            { kind: 'output', text: 'two' },
            { kind: 'user', text: 'three' },
            { kind: 'output', text: 'four' },
            { kind: 'status', text: 'five' },
          ], { mode: 'settled', revision: 0, tailCount: 2 });
          const stableSecond = window.FaryoStableBlocks.reconcile(stableContainer, stableAppended, makeStableNode);
          const state = {
            ready: ['ts', 'python', 'tex', 'lean4', 'matlab']
              .every((language) => highlightedLanguages.includes(language)),
            katexCount: fixture.querySelectorAll('.katex').length,
            displayCount: fixture.querySelectorAll('.katex-display').length,
            errorCount: fixture.querySelectorAll('.katex-error').length,
            formulaCellCount: formulaCells.filter((cell) => cell.querySelectorAll('.katex').length === 1).length,
            tableRows: fixture.querySelectorAll('tbody tr').length,
            tableScrollable: Boolean(tableScroll && tableScroll.scrollWidth > tableScroll.clientWidth),
            tableDisplay: table ? getComputedStyle(table).display : '',
            codeBlockCount: fixture.querySelectorAll('.markdown-code-block').length,
            highlightedLanguages,
            codeMathCount: fixture.querySelectorAll('pre .katex').length,
            cjkStrong: fixture.querySelector('strong')?.textContent || '',
            rawHtmlExecuted: Boolean(fixture.querySelector('img[src="x"]') || globalThis.pwned),
            pageHorizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
            assetsLocal: assetUrls.length >= 2 && assetUrls.every((url) => new URL(url).origin === location.origin),
            stableBlocks: {
              first: stableFirst,
              second: stableSecond,
              identityPreserved: stableOriginalNodes.every((node, index) => stableContainer.children[index] === node),
              frozenCount: stableContainer.querySelectorAll('[data-faryo-block-stable="true"]').length,
            },
          };
          fixture.remove();
          return state;
        })()`,
        returnByValue: true,
      });
      if (result.exceptionDetails) {
        const message = result.exceptionDetails.exception?.description
          || result.exceptionDetails.text
          || 'unknown fixture evaluation error';
        throw new Error('AST fixture evaluation failed: ' + message);
      }
      fixtureState = result.result?.value || {};
      if (fixtureState.ready) break;
    }
    if (!fixtureState.ready) throw new Error('AST fixture highlighters did not become ready: ' + JSON.stringify(fixtureState));
    if (fixtureState.katexCount !== 6 || fixtureState.displayCount !== 1 || fixtureState.errorCount !== 0) {
      throw new Error('AST fixture math nodes were incorrect: ' + JSON.stringify(fixtureState));
    }
    if (fixtureState.tableRows !== 5 || fixtureState.formulaCellCount !== 5 || fixtureState.tableDisplay !== 'table') {
      throw new Error('AST fixture table structure was incorrect: ' + JSON.stringify(fixtureState));
    }
    if (fixtureState.codeBlockCount !== 6 || fixtureState.codeMathCount !== 0 || fixtureState.cjkStrong !== '注意：') {
      throw new Error('AST fixture Markdown structure was incorrect: ' + JSON.stringify(fixtureState));
    }
    if (fixtureState.rawHtmlExecuted || fixtureState.pageHorizontalOverflow || !fixtureState.assetsLocal) {
      throw new Error('AST fixture crossed a security or layout boundary: ' + JSON.stringify(fixtureState));
    }
    if (fixtureState.stableBlocks?.first?.created !== 4
      || fixtureState.stableBlocks?.second?.created !== 1
      || fixtureState.stableBlocks?.second?.reused !== 4
      || !fixtureState.stableBlocks?.identityPreserved
      || fixtureState.stableBlocks?.frozenCount !== 3) {
      throw new Error('Stable block fixture did not preserve finalized DOM: ' + JSON.stringify(fixtureState.stableBlocks));
    }
    if (viewportWidth > 0 && viewportWidth < 720 && !fixtureState.tableScrollable) {
      throw new Error('AST fixture table did not scroll inside its mobile container: ' + JSON.stringify(fixtureState));
    }
    console.log('faryo-browser-ast-fixture=PASS markdown=GFM math=KaTeX highlight=Shiki');
  }

  if (checkCopyFidelity) {
    const copyResult = await send('Runtime.evaluate', {
      expression: `(() => {
        const root = document.createElement('div');
        root.id = 'faryo-copy-fixture';
        const user = document.createElement('section');
        user.className = 'compact-block user';
        user.innerHTML = '<div class="markdown-body">' + window.FaryoMarkdownAst.render(${JSON.stringify(copyFixtureUser)}) + '</div>';
        const answer = document.createElement('section');
        answer.className = 'compact-block output';
        answer.innerHTML = '<div class="markdown-body">' + window.FaryoMarkdownAst.render(${JSON.stringify(copyFixtureAnswer)}) + '</div><details class="memory-reference-card"><summary>Memory references</summary><div>private metadata</div></details><button class="copy-output-block">⧉</button>';
        const live = document.createElement('details');
        live.className = 'compact-live-terminal';
        live.innerHTML = '<summary>Live from tmux</summary><pre>private live text</pre>';
        root.append(user, answer, live);
        document.body.appendChild(root);
        const controller = window.FaryoCopyFidelity.create({ root, parseMarkdown: (source) => window.FaryoMarkdownAst.parse(source) });
        controller.beginRender();
        controller.bindBlock(user, { source: ${JSON.stringify(copyFixtureUser)}, renderSource: ${JSON.stringify(copyFixtureUser)}, kind: 'user' });
        controller.bindBlock(answer, { source: ${JSON.stringify(copyFixtureAnswer)}, renderSource: ${JSON.stringify(copyFixtureAnswer)}, kind: 'output' });

        const outputRange = document.createRange();
        outputRange.selectNodeContents(answer);
        const outputPayload = controller.payloadForRange(outputRange);

        const crossRange = document.createRange();
        crossRange.setStartBefore(user);
        crossRange.setEndAfter(live);
        const crossPayload = controller.payloadForRange(crossRange);

        const inlineFormula = answer.querySelector('.katex');
        const formulaText = (() => {
          const walker = document.createTreeWalker(inlineFormula, NodeFilter.SHOW_TEXT);
          return walker.nextNode();
        })();
        const formulaRange = document.createRange();
        formulaRange.selectNodeContents(inlineFormula);
        const formulaPayload = controller.payloadForRange(formulaRange, {
          anchorNode: formulaText,
          focusNode: formulaText,
        });

        const paragraph = answer.querySelector('p');
        const paragraphText = [...paragraph.childNodes].find((node) => node.nodeType === Node.TEXT_NODE);
        const formulaEndText = (() => {
          const walker = document.createTreeWalker(inlineFormula, NodeFilter.SHOW_TEXT);
          let node = null, last = null;
          while ((node = walker.nextNode())) last = node;
          return last;
        })();
        const partialRange = document.createRange();
        partialRange.setStart(paragraphText, 0);
        partialRange.setEnd(formulaEndText, Math.min(1, formulaEndText.length));
        const partialPayload = controller.payloadForRange(partialRange);

        const code = answer.querySelector('pre code') || answer.querySelector('pre');
        const codeRange = document.createRange();
        codeRange.selectNodeContents(code);
        const codePayload = controller.payloadForRange(codeRange);

        const copied = {};
        const selection = getSelection();
        selection.removeAllRanges();
        selection.addRange(crossRange);
        let prevented = false;
        const intercepted = controller.handleCopy({
          clipboardData: { setData(type, value) { copied[type] = value; } },
          preventDefault() { prevented = true; },
        });
        let fallbackPrevented = false;
        const defaultPreserved = controller.handleCopy({
          clipboardData: null,
          preventDefault() { fallbackPrevented = true; },
        }) === false && !fallbackPrevented;
        selection.removeAllRanges();

        const sourceInAttribute = [...root.querySelectorAll('*')].some((element) => [...element.attributes]
          .some((attribute) => attribute.value.includes('begin{cases}') || attribute.value.includes('Copy result')));
        const state = {
          moduleReady: typeof window.FaryoCopyFidelity?.create === 'function',
          outputExact: outputPayload?.plain === ${JSON.stringify(copyFixtureAnswer)},
          crossExact: crossPayload?.plain === ${JSON.stringify(`${copyFixtureUser}\n\n${copyFixtureAnswer}`)},
          formulaExact: formulaPayload?.plain === ${JSON.stringify('\\(x_i^2\\)')},
          formulaKind: formulaPayload?.kind || '',
          partialHasTex: partialPayload?.plain?.includes(${JSON.stringify('\\(x_i^2\\)')}) || false,
          partialFormulaCopies: (partialPayload?.plain?.split('x_i^2').length || 1) - 1,
          codeDefaultPreserved: codePayload === null,
          intercepted,
          prevented,
          defaultPreserved,
          eventPlainExact: copied['text/plain'] === ${JSON.stringify(`${copyFixtureUser}\n\n${copyFixtureAnswer}`)},
          eventHtmlSafe: Boolean(copied['text/html'])
            && !/data-|private metadata|private live text|begin%7Bcases%7D/i.test(copied['text/html'])
            && copied['text/html'].includes('<table>')
            && copied['text/html'].includes(${JSON.stringify('<code>\\(x_i^2\\)</code>')}),
          noSourceAttribute: !sourceInAttribute,
        };
        root.remove();
        return state;
      })()`,
      returnByValue: true,
    });
    if (copyResult.exceptionDetails) {
      throw new Error(copyResult.exceptionDetails.exception?.description || copyResult.exceptionDetails.text || 'Copy fixture evaluation failed');
    }
    const copyState = copyResult.result?.value || {};
    if (!copyState.moduleReady || !copyState.outputExact || !copyState.crossExact
      || !copyState.formulaExact || copyState.formulaKind !== 'formula'
      || !copyState.partialHasTex || copyState.partialFormulaCopies !== 1
      || !copyState.codeDefaultPreserved || !copyState.intercepted || !copyState.prevented || !copyState.defaultPreserved
      || !copyState.eventPlainExact || !copyState.eventHtmlSafe || !copyState.noSourceAttribute) {
      throw new Error(`Copy fidelity fixture failed: ${JSON.stringify(copyState)}`);
    }
    console.log('faryo-browser-copy-fidelity=PASS block=exact formula=tex selection=structured');

    const realCopyResult = await send('Runtime.evaluate', {
      expression: `(async () => {
        const output = document.getElementById('output');
        const block = [...(output?.querySelectorAll(':scope > .compact-block.output') || [])].reverse()
          .find((item) => item.querySelector('.katex'));
        const formula = block?.querySelector('.katex');
        if (!block || !formula) return { ready: false };
        const dispatch = (range) => {
          const copied = {};
          const selection = getSelection();
          selection.removeAllRanges();
          selection.addRange(range);
          const event = new Event('copy', { bubbles: true, cancelable: true });
          Object.defineProperty(event, 'clipboardData', { value: { setData(type, value) { copied[type] = value; } } });
          document.dispatchEvent(event);
          selection.removeAllRanges();
          return { copied, prevented: event.defaultPrevented };
        };
        const formulaRange = document.createRange();
        formulaRange.selectNodeContents(formula);
        const formulaCopy = dispatch(formulaRange);
        const blockRange = document.createRange();
        blockRange.selectNodeContents(block);
        const blockCopy = dispatch(blockRange);
        const copyButton = output.querySelector('.copy-output-block');
        const buttonBlock = copyButton?.closest('.compact-block.output');
        let buttonExact = false;
        if (copyButton && buttonBlock) {
          const expectedRange = document.createRange();
          expectedRange.selectNodeContents(buttonBlock);
          const expectedPlain = String(dispatch(expectedRange).copied['text/plain'] || '');
          let writtenPlain = '';
          const previousClipboard = Object.getOwnPropertyDescriptor(navigator, 'clipboard');
          Object.defineProperty(navigator, 'clipboard', {
            configurable: true,
            value: {
              async write(items) { writtenPlain = await (await items[0].getType('text/plain')).text(); },
              async writeText(value) { writtenPlain = String(value); },
            },
          });
          copyButton.click();
          await new Promise((resolve) => setTimeout(resolve, 180));
          if (previousClipboard) Object.defineProperty(navigator, 'clipboard', previousClipboard);
          else delete navigator.clipboard;
          buttonExact = Boolean(expectedPlain && writtenPlain === expectedPlain);
        }
        const formulaPlain = String(formulaCopy.copied['text/plain'] || '');
        const blockPlain = String(blockCopy.copied['text/plain'] || '');
        const blockHtml = String(blockCopy.copied['text/html'] || '');
        const annotation = String(formula.querySelector('annotation[encoding="application/x-tex"]')?.textContent || '');
        const digest = [...new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(blockPlain)))]
          .map((value) => value.toString(16).padStart(2, '0')).join('');
        const attributeLengths = [...output.querySelectorAll('*')].flatMap((element) => [...element.attributes].map((attribute) => attribute.value.length));
        return {
          ready: true,
          controller: document.documentElement.dataset.faryoCopy || '',
          blockBound: block.dataset.faryoCopyBound || '',
          chatMode: document.getElementById('refreshBtn')?.classList.contains('mode-active') || false,
          formulaPrevented: formulaCopy.prevented,
          formulaDelimited: [${JSON.stringify('\\(')}, ${JSON.stringify('\\[')}, '$$', '$'].some((prefix) => formulaPlain.startsWith(prefix)),
          formulaMatchesAnnotation: Boolean(annotation && formulaPlain.includes(annotation)),
          formulaCopies: annotation ? formulaPlain.split(annotation).length - 1 : 0,
          blockPrevented: blockCopy.prevented,
          buttonExact,
          blockLength: blockPlain.length,
          blockHashLength: digest.length,
          blockHasTex: [${JSON.stringify('\\(')}, ${JSON.stringify('\\[')}, '$$'].some((marker) => blockPlain.includes(marker)),
          internalTagsAbsent: !blockPlain.toLowerCase().includes('<oai-mem-citation'),
          htmlSafe: Boolean(blockHtml)
            && !/(?:data-faryo|token=|katex-mathml|memory-reference-card|compact-live-terminal)/i.test(blockHtml),
          maxAttributeLength: Math.max(0, ...attributeLengths),
        };
      })()`,
      awaitPromise: true,
      returnByValue: true,
    });
    if (realCopyResult.exceptionDetails) {
      throw new Error(realCopyResult.exceptionDetails.exception?.description || realCopyResult.exceptionDetails.text || 'Real copy evaluation failed');
    }
    const realCopy = realCopyResult.result?.value || {};
    if (!realCopy.ready || realCopy.controller !== 'ready' || realCopy.blockBound !== 'true' || !realCopy.chatMode
      || !realCopy.formulaPrevented || !realCopy.formulaDelimited
      || !realCopy.formulaMatchesAnnotation || realCopy.formulaCopies !== 1
      || !realCopy.blockPrevented || !realCopy.buttonExact || realCopy.blockLength < 1 || realCopy.blockHashLength !== 64
      || !realCopy.blockHasTex || !realCopy.internalTagsAbsent || !realCopy.htmlSafe
      || realCopy.maxAttributeLength > 512) {
      throw new Error(`Real copy fidelity check failed: ${JSON.stringify(realCopy)}`);
    }
    console.log(`faryo-browser-copy-real=PASS block-bytes=${realCopy.blockLength} sha256=present formula=tex-only`);
  }

  if (checkQuestionNavigator) {
    const fixtureResult = await send('Runtime.evaluate', {
      expression: `(() => {
        // Freeze the production capture loop while this test owns the output
        // DOM. Otherwise a legitimate live refresh can replace the synthetic
        // question fixture halfway through the keyboard-navigation assertions.
        window.dispatchEvent(new PageTransitionEvent('pagehide', { persisted: true }));
        const output = document.getElementById('output');
        const scroller = document.getElementById('outputWrap');
        if (!output || !scroller) return { ready: false };
        const turns = [];
        for (let index = 0; index < 12; index += 1) {
          turns.push('<section class="compact-block user" data-faryo-block-key="question-' + index + '" data-faryo-question-preview="Anonymous question ' + (index + 1) + '">Anonymous question ' + (index + 1) + '</section>');
          turns.push('<section class="compact-block output" data-faryo-block-key="answer-' + index + '" style="min-height:180px"><div class="markdown-body">Anonymous answer ' + (index + 1) + '</div></section>');
        }
        output.className = 'output compact-blocks';
        output.innerHTML = turns.join('');
        scroller.scrollTop = 0;
        return { ready: true };
      })()`,
      returnByValue: true,
    });
    if (!fixtureResult.result?.value?.ready) throw new Error('Question navigator fixture could not be installed');

    let initial = {};
    for (let attempt = 0; attempt < 80; attempt += 1) {
      await delay(50);
      const result = await send('Runtime.evaluate', {
        expression: `(() => {
          const navigator = document.getElementById('questionNavigator');
          const markers = [...document.querySelectorAll('#questionNavMarkers .question-nav-marker')];
          const output = document.getElementById('output');
          const scroller = document.getElementById('outputWrap');
          window.__faryoQuestionNavFirst = markers[0] || null;
          return {
            markerCount: markers.length,
            current: document.getElementById('questionNavCurrent')?.textContent || '',
            total: document.getElementById('questionNavTotal')?.textContent || '',
            available: Boolean(navigator && !navigator.classList.contains('hidden') && navigator.getClientRects().length),
            shown: Boolean(navigator && Number.parseFloat(getComputedStyle(navigator).opacity) > 0.5),
            moduleReady: typeof window.FaryoQuestionNavigator?.createController === 'function',
            pageHorizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
            balancedPadding: Boolean(scroller && Math.abs(
              Number.parseFloat(getComputedStyle(scroller).paddingLeft)
              - Number.parseFloat(getComputedStyle(scroller).paddingRight)
            ) < 1),
            outputWidth: Math.round(output?.getBoundingClientRect().width || 0),
            scrollable: Boolean(scroller && scroller.scrollHeight > scroller.clientHeight),
          };
        })()`,
        returnByValue: true,
      });
      initial = result.result?.value || {};
      if (initial.markerCount === 12 && initial.current === '1') break;
    }
    if (initial.markerCount !== 12 || initial.total !== '12' || initial.current !== '1'
      || !initial.available || initial.shown || !initial.moduleReady || !initial.scrollable
      || initial.pageHorizontalOverflow || !initial.balancedPadding) {
      throw new Error(`Question navigator initial state failed: ${JSON.stringify(initial)}`);
    }

    await send('Runtime.evaluate', {
      expression: `document.getElementById('outputWrap')?.dispatchEvent(new WheelEvent('wheel', { deltaY: 240, bubbles: true }))`,
    });
    let revealed = {};
    for (let attempt = 0; attempt < 20; attempt += 1) {
      await delay(30);
      const result = await send('Runtime.evaluate', {
        expression: `(() => {
          const navigator = document.getElementById('questionNavigator');
          return {
            shown: Boolean(navigator && Number.parseFloat(getComputedStyle(navigator).opacity) > 0.5),
            interactive: getComputedStyle(navigator).pointerEvents !== 'none',
            scrollingClass: Boolean(navigator?.classList.contains('is-scrolling')),
            outputWidth: Math.round(document.getElementById('output')?.getBoundingClientRect().width || 0),
          };
        })()`,
        returnByValue: true,
      });
      revealed = result.result?.value || {};
      if (revealed.shown) break;
    }
    if (!revealed.shown || !revealed.interactive || !revealed.scrollingClass
      || Math.abs(revealed.outputWidth - initial.outputWidth) > 1) {
      throw new Error(`Question navigator did not reveal for fast scrolling: ${JSON.stringify(revealed)}`);
    }
    await delay(220);
    const translucentResult = await send('Runtime.evaluate', {
      expression: `(() => {
        const style = getComputedStyle(document.getElementById('questionNavigator'));
        const match = style.backgroundColor.match(/\\/\\s*([\\d.]+)\\)/);
        return { background: style.backgroundColor, alpha: match ? Number(match[1]) : 1, backdrop: style.backdropFilter };
      })()`,
      returnByValue: true,
    });
    const translucentState = translucentResult.result?.value || {};
    if (translucentState.alpha > 0.62 || !String(translucentState.backdrop || '').includes('blur(')) {
      throw new Error(`Question navigator obscures content while scrolling: ${JSON.stringify(translucentState)}`);
    }

    const focusSetup = await send('Runtime.evaluate', {
      expression: `(() => {
        const firstMarker = document.querySelector('#questionNavMarkers .question-nav-marker');
        const focusable = [...document.querySelectorAll('button:not([disabled]), a[href], input:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])')]
          .filter((element) => element.getClientRects().length > 0);
        const markerIndex = focusable.indexOf(firstMarker);
        const predecessor = markerIndex > 0 ? focusable[markerIndex - 1] : null;
        predecessor?.focus();
        return { markerIndex, predecessor: predecessor?.id || predecessor?.className || '' };
      })()`,
      returnByValue: true,
    });
    if (Number(focusSetup.result?.value?.markerIndex ?? -1) < 1) {
      throw new Error(`Question navigator has no preceding tab stop: ${JSON.stringify(focusSetup.result?.value || {})}`);
    }
    let tabFocus = {};
    for (let attempt = 0; attempt < 2; attempt += 1) {
      await send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9, nativeVirtualKeyCode: 9 });
      await send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9, nativeVirtualKeyCode: 9 });
      const result = await send('Runtime.evaluate', {
        expression: `(() => ({
          marker: document.activeElement?.classList?.contains('question-nav-marker') || false,
          focusedIndex: document.activeElement?.dataset?.questionIndex || '',
        }))()`,
        returnByValue: true,
      });
      tabFocus = result.result?.value || {};
      if (tabFocus.marker) break;
    }
    if (!tabFocus.marker || tabFocus.focusedIndex !== '0') {
      throw new Error(`Question navigator was not reachable by Tab: ${JSON.stringify(tabFocus)}`);
    }
    // CDP keyboard input may focus the page itself, which deliberately wakes
    // the production live connection. Pause it again before inspecting the
    // synthetic fixture.
    await send('Runtime.evaluate', {
      expression: `window.dispatchEvent(new PageTransitionEvent('pagehide', { persisted: true }))`,
    });
    await delay(30);
    const previewResult = await send('Runtime.evaluate', {
      expression: `(() => {
        const preview = document.getElementById('questionNavPreview');
        return {
          visible: Boolean(preview?.classList.contains('visible')),
          text: preview?.textContent || '',
          focusedIndex: document.activeElement?.dataset?.questionIndex || '',
          focusedTag: document.activeElement?.tagName || '',
          navigatorHidden: document.getElementById('questionNavigator')?.classList.contains('hidden'),
          markerCount: document.querySelectorAll('#questionNavMarkers .question-nav-marker').length,
        };
      })()`,
      returnByValue: true,
    });
    const previewState = previewResult.result?.value || {};
    if (!previewState.visible || previewState.text !== '1. Anonymous question 1') {
      throw new Error(`Question navigator preview failed: ${JSON.stringify(previewState)}`);
    }
    await send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'ArrowDown', code: 'ArrowDown', windowsVirtualKeyCode: 40, nativeVirtualKeyCode: 40 });
    await send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'ArrowDown', code: 'ArrowDown', windowsVirtualKeyCode: 40, nativeVirtualKeyCode: 40 });
    let keyboardState = {};
    for (let attempt = 0; attempt < 80; attempt += 1) {
      await delay(50);
      const result = await send('Runtime.evaluate', {
        expression: `(() => ({
          current: document.getElementById('questionNavCurrent')?.textContent || '',
          active: document.querySelector('#questionNavMarkers .question-nav-marker[aria-current="step"]')?.dataset.questionIndex || '',
          focused: document.activeElement?.dataset?.questionIndex || '',
        }))()`,
        returnByValue: true,
      });
      keyboardState = result.result?.value || {};
      if (keyboardState.active === '1') break;
    }
    if (keyboardState.current !== '2' || keyboardState.active !== '1' || keyboardState.focused !== '1') {
      throw new Error(`Question navigator keyboard jump failed: ${JSON.stringify(keyboardState)}`);
    }
    await send('Runtime.evaluate', { expression: `document.activeElement?.blur()` });

    await send('Runtime.evaluate', {
      expression: `document.querySelectorAll('#questionNavMarkers .question-nav-marker')[7]?.click()`,
    });
    let jumped = {};
    for (let attempt = 0; attempt < 80; attempt += 1) {
      await delay(50);
      const result = await send('Runtime.evaluate', {
        expression: `(() => {
          const scroller = document.getElementById('outputWrap');
          const target = document.querySelectorAll('#output .compact-block.user')[7];
          const active = document.querySelector('#questionNavMarkers .question-nav-marker[aria-current="step"]');
          const preview = document.getElementById('questionNavPreview');
          const scrollerRect = scroller?.getBoundingClientRect();
          const targetRect = target?.getBoundingClientRect();
          return {
            scrollTop: scroller?.scrollTop || 0,
            active: active?.dataset.questionIndex || '',
            current: document.getElementById('questionNavCurrent')?.textContent || '',
            targetOffset: scrollerRect && targetRect ? targetRect.top - scrollerRect.top : -1,
            targetDelta: scrollerRect && targetRect ? Math.abs(targetRect.top - scrollerRect.top - 20) : -1,
            previewHidden: !preview?.classList.contains('visible'),
          };
        })()`,
        returnByValue: true,
      });
      jumped = result.result?.value || {};
      if (jumped.active === '7' && jumped.targetDelta >= 0 && jumped.targetDelta < 10) break;
    }
    if (jumped.scrollTop <= 0 || jumped.active !== '7' || jumped.current !== '8'
      || jumped.targetDelta < 0 || jumped.targetDelta >= 10 || !jumped.previewHidden) {
      throw new Error(`Question navigator jump failed: ${JSON.stringify(jumped)}`);
    }
    await delay(30);

    const appendResult = await send('Runtime.evaluate', {
      expression: `(() => {
        const output = document.getElementById('output');
        const scroller = document.getElementById('outputWrap');
        window.__faryoQuestionNavScrollBefore = scroller?.scrollTop || 0;
        const user = document.createElement('section');
        user.className = 'compact-block user';
        user.dataset.faryoBlockKey = 'question-12';
        user.dataset.faryoQuestionPreview = 'Anonymous question 13';
        user.textContent = 'Anonymous question 13';
        const answer = document.createElement('section');
        answer.className = 'compact-block output';
        answer.dataset.faryoBlockKey = 'answer-12';
        answer.style.minHeight = '180px';
        answer.textContent = 'Anonymous answer 13';
        output?.append(user, answer);
        return { appended: Boolean(output && scroller) };
      })()`,
      returnByValue: true,
    });
    if (!appendResult.result?.value?.appended) throw new Error('Question navigator append fixture failed');

    let appended = {};
    for (let attempt = 0; attempt < 80; attempt += 1) {
      await delay(50);
      const result = await send('Runtime.evaluate', {
        expression: `(() => {
          const scroller = document.getElementById('outputWrap');
          const markers = [...document.querySelectorAll('#questionNavMarkers .question-nav-marker')];
          return {
            markerCount: markers.length,
            firstPreserved: markers[0] === window.__faryoQuestionNavFirst,
            scrollDelta: Math.abs((scroller?.scrollTop || 0) - Number(window.__faryoQuestionNavScrollBefore || 0)),
            total: document.getElementById('questionNavTotal')?.textContent || '',
            current: document.getElementById('questionNavCurrent')?.textContent || '',
            active: document.querySelector('#questionNavMarkers .question-nav-marker[aria-current="step"]')?.dataset.questionIndex || '',
          };
        })()`,
        returnByValue: true,
      });
      appended = result.result?.value || {};
      if (appended.markerCount === 13) break;
    }
    if (appended.markerCount !== 13 || appended.total !== '13'
      || appended.current !== '8' || appended.active !== '7'
      || !appended.firstPreserved || appended.scrollDelta > 2) {
      throw new Error(`Question navigator live append moved history: ${JSON.stringify(appended)}`);
    }

    await send('Runtime.evaluate', {
      expression: `(() => {
        const scroller = document.getElementById('outputWrap');
        if (scroller) scroller.scrollTop = scroller.scrollHeight;
      })()`,
    });
    let latest = {};
    for (let attempt = 0; attempt < 40; attempt += 1) {
      await delay(50);
      const result = await send('Runtime.evaluate', {
        expression: `(() => ({
          current: document.getElementById('questionNavCurrent')?.textContent || '',
          active: document.querySelector('#questionNavMarkers .question-nav-marker[aria-current="step"]')?.dataset.questionIndex || '',
        }))()`,
        returnByValue: true,
      });
      latest = result.result?.value || {};
      if (latest.current === '13') break;
    }
    if (latest.current !== '13' || latest.active !== '12') {
      throw new Error(`Question navigator latest tracking failed: ${JSON.stringify(latest)}`);
    }
    if (questionNavScreenshotPath) {
      const screenshot = await send('Page.captureScreenshot', { format: 'png', fromSurface: true });
      await writeFile(questionNavScreenshotPath, Buffer.from(screenshot.data, 'base64'));
      console.log(`faryo-browser-question-navigator-screenshot=${questionNavScreenshotPath}`);
    }
    await send('Runtime.evaluate', { expression: `document.activeElement?.blur()` });
    await delay(1500);
    const hiddenResult = await send('Runtime.evaluate', {
      expression: `(() => {
        const navigator = document.getElementById('questionNavigator');
        return {
          shown: Boolean(navigator && Number.parseFloat(getComputedStyle(navigator).opacity) > 0.05),
          interactive: getComputedStyle(navigator).pointerEvents !== 'none',
        };
      })()`,
      returnByValue: true,
    });
    const hiddenState = hiddenResult.result?.value || {};
    if (hiddenState.shown || hiddenState.interactive) {
      throw new Error(`Question navigator did not auto-hide: ${JSON.stringify(hiddenState)}`);
    }
    await send('Runtime.evaluate', {
      expression: `window.dispatchEvent(new PageTransitionEvent('pageshow', { persisted: true }))`,
    });
    console.log('faryo-browser-question-navigator=PASS questions=13 reveal=fast-scroll translucent=PASS auto-hide=PASS jump=8 live-append=preserved latest=13');
  }

  if (checkLiveScroll) {
    let liveScrollState = {};
    for (let attempt = 0; attempt < 100; attempt += 1) {
      await delay(100);
      const result = await send('Runtime.evaluate', {
        expression: `(() => {
          const panel = document.querySelector('.compact-live-terminal');
          if (panel && !panel.open) {
            panel.open = true;
            return { ready: false, opening: true };
          }
          const pane = panel?.querySelector('pre');
          if (!pane) return { ready: false, panel: Boolean(panel), panelOpen: Boolean(panel?.open), captureSource: document.getElementById('output')?.dataset.captureSource || '' };
          if (pane.scrollHeight <= pane.clientHeight) {
            pane.style.height = '72px';
            pane.style.maxHeight = '72px';
          }
          if (pane.scrollHeight <= pane.clientHeight) return { ready: false, panel: true, panelOpen: Boolean(panel.open), scrollHeight: pane.scrollHeight, clientHeight: pane.clientHeight, lineCount: pane.textContent.split('\\n').length };
          const maximum = pane.scrollHeight - pane.clientHeight;
          const target = Math.max(1, Math.floor(maximum / 3));
          const initialNearBottom = maximum - pane.scrollTop < 48;
          pane.scrollTop = target;
          pane.dataset.faryoSmokeScroll = 'waiting';
          window.__faryoSmokeLiveScrollTarget = target;
          window.__faryoSmokeLivePane = pane;
          window.__faryoSmokeLiveRevision = Number(panel.dataset.liveRevision || 0);
          return { ready: true, initialNearBottom, lineCount: pane.textContent.split('\\n').length };
        })()`,
        returnByValue: true,
      });
      liveScrollState = result.result?.value || {};
      if (liveScrollState.ready) break;
    }
    if (!liveScrollState.ready) throw new Error(`A scrollable Live from tmux pane did not appear: ${JSON.stringify(liveScrollState)}`);
    if (!liveScrollState.initialNearBottom) throw new Error('A new Live from tmux pane did not start at the latest output');

    let preserved = {};
    for (let attempt = 0; attempt < 120; attempt += 1) {
      await delay(100);
      const result = await send('Runtime.evaluate', {
        expression: `(async () => {
          const panel = document.querySelector('.compact-live-terminal');
          const pane = panel?.querySelector('pre');
          const sameNode = Boolean(pane && pane === window.__faryoSmokeLivePane);
          const updated = Number(panel?.dataset.liveRevision || 0) > Number(window.__faryoSmokeLiveRevision || 0);
          const target = Number(window.__faryoSmokeLiveScrollTarget || 0);
          return {
            updated,
            sameNode,
            scrollTop: pane ? pane.scrollTop : -1,
            maximum: pane ? Math.max(0, pane.scrollHeight - pane.clientHeight) : -1,
            scrollHeight: pane ? pane.scrollHeight : -1,
            clientHeight: pane ? pane.clientHeight : -1,
            target,
            delta: pane ? Math.abs(pane.scrollTop - target) : -1,
          };
        })()`,
        awaitPromise: true,
        returnByValue: true,
      });
      preserved = result.result?.value || {};
      if (preserved.updated) break;
    }
    if (!preserved.updated) throw new Error('Live from tmux did not refresh during the scroll test');
    if (!preserved.sameNode) throw new Error('Live from tmux replaced its DOM node during refresh');
    if (preserved.delta > 2 || preserved.delta < 0) throw new Error(`Live from tmux moved the reading position: ${JSON.stringify(preserved)}`);

    const selectionStarted = await send('Runtime.evaluate', {
      expression: `(() => {const panel=document.querySelector('.compact-live-terminal'),pane=panel?.querySelector('pre'),node=pane?.firstChild;if(!panel||!pane||!node||!node.textContent)return false;const selection=getSelection(),range=document.createRange();range.setStart(node,0);range.setEnd(node,Math.min(12,node.textContent.length));selection.removeAllRanges();selection.addRange(range);window.__faryoSmokeSelectionRevision=Number(panel.dataset.liveRevision||0);window.__faryoSmokeSelectionText=selection.toString();return Boolean(window.__faryoSmokeSelectionText);})()`,
      returnByValue: true,
    });
    if (!selectionStarted.result?.value) throw new Error('Live from tmux selection fixture could not start');
    let selectionPaused = {};
    for (let attempt = 0; attempt < 120; attempt += 1) {
      await delay(100);
      const result = await send('Runtime.evaluate', {
        expression: `(() => {const panel=document.querySelector('.compact-live-terminal'),pane=panel?.querySelector('pre'),selection=getSelection();return{sameNode:pane===window.__faryoSmokeLivePane,revision:Number(panel?.dataset.liveRevision||0),initialRevision:Number(window.__faryoSmokeSelectionRevision||0),selectionStable:selection?.toString()===window.__faryoSmokeSelectionText,paused:String(panel?.querySelector('.compact-live-state')?.textContent||'').startsWith('Updates paused'),pending:typeof panel?.__faryoPendingLiveText==='string'};})()`,
        returnByValue: true,
      });
      selectionPaused = result.result?.value || {};
      if (selectionPaused.paused && selectionPaused.pending) break;
    }
    if (!selectionPaused.sameNode || !selectionPaused.selectionStable || !selectionPaused.paused || !selectionPaused.pending || selectionPaused.revision !== selectionPaused.initialRevision) {
      throw new Error(`Live from tmux disturbed an active selection: ${JSON.stringify(selectionPaused)}`);
    }
    await send('Runtime.evaluate', { expression: `getSelection()?.removeAllRanges()` });
    let selectionFlushed = {};
    for (let attempt = 0; attempt < 80; attempt += 1) {
      await delay(100);
      const result = await send('Runtime.evaluate', {
        expression: `(() => {const panel=document.querySelector('.compact-live-terminal'),pane=panel?.querySelector('pre');return{sameNode:pane===window.__faryoSmokeLivePane,revision:Number(panel?.dataset.liveRevision||0),initialRevision:Number(window.__faryoSmokeSelectionRevision||0),pending:typeof panel?.__faryoPendingLiveText==='string',copyReady:Boolean(panel?.querySelector('.compact-live-copy'))};})()`,
        returnByValue: true,
      });
      selectionFlushed = result.result?.value || {};
      if (selectionFlushed.revision > selectionFlushed.initialRevision && !selectionFlushed.pending) break;
    }
    if (!selectionFlushed.sameNode || selectionFlushed.revision <= selectionFlushed.initialRevision || selectionFlushed.pending || !selectionFlushed.copyReady) {
      throw new Error(`Live from tmux did not flush after selection: ${JSON.stringify(selectionFlushed)}`);
    }
    const copyResult = await send('Runtime.evaluate', {
      expression: `(async()=>{const button=document.querySelector('.compact-live-copy'),pane=document.querySelector('.compact-live-terminal pre'),descriptor=Object.getOwnPropertyDescriptor(navigator,'clipboard');let copied='';Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async(value)=>{copied=String(value);}}});button?.click();await new Promise(resolve=>setTimeout(resolve,50));if(descriptor)Object.defineProperty(navigator,'clipboard',descriptor);else delete navigator.clipboard;return Boolean(button&&pane&&copied===pane.textContent);})()`,
      awaitPromise: true,
      returnByValue: true,
    });
    if (!copyResult.result?.value) throw new Error('Live from tmux copy button did not copy the visible terminal text');
    console.log(`faryo-browser-live-scroll=PASS initial=latest lines=${liveScrollState.lineCount} manual=preserved selection=stable copy=ready`);
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

  if (uiScreenshotPath) {
    const uiFixtureResult = await send('Runtime.evaluate', {
      expression: `(() => {
        const text = (id, value) => { const element = document.getElementById(id); if (element) element.textContent = value; };
        text('ownerText', 'Ubuntu Workstation');
        text('topicText', 'Research session');
        text('draftState', 'Project workspace');
        text('ctxText', 'Ctx 42% · 108.5k/258k');
        text('quotaText', 'Week 58% left');
        text('modelText', 'Agent ready');
        const goalPill = document.getElementById('goalPill');
        if (goalPill) { goalPill.hidden = false; goalPill.className = 'pill goal-pill goal-active'; }
        text('goalPill', 'Goal Active');
        text('phasePill', 'git clean');
        text('detailsSession', 'Research session');
        text('detailsOwner', 'Ubuntu Workstation');
        text('detailsModel', 'Agent model');
        text('detailsContext', '108,528 / 258,400 tokens · 42% used');
        text('detailsGoal', 'Active · 18m');
        text('detailsQuota', '58% left · 42% used · resets Aug 20, 10:20');
        text('detailsGit', 'git clean');
        text('detailsSource', 'structured history');
        text('detailsConnection', 'live');
        text('versionToggle', 'Faryo main');
        const prompt = document.getElementById('promptInput');
        if (prompt) prompt.placeholder = 'Ask Codex about this result';
        const smokeSafeText = {
          ownerText: 'Ubuntu Workstation', topicText: 'Research session', draftState: 'Project workspace',
          ctxText: 'Ctx 42% · 108.5k/258k', quotaText: 'Week 58% left', modelText: 'Agent ready', goalPill: 'Goal Active', phasePill: 'git clean',
          detailsSession: 'Research session', detailsOwner: 'Ubuntu Workstation', detailsModel: 'Agent model',
          detailsContext: '108,528 / 258,400 tokens · 42% used', detailsGoal: 'Active · 18m', detailsQuota: '58% left · 42% used · resets Aug 20, 10:20', detailsGit: 'git clean', detailsSource: 'structured history', detailsConnection: 'live',
        };
        const safeStyle = document.createElement('style');
        safeStyle.textContent = '.faryo-smoke-safe-text{font-size:0!important;color:transparent!important}.faryo-smoke-safe-text::after{content:attr(data-faryo-smoke-text);font-size:12px;color:var(--text)}#ownerText.faryo-smoke-safe-text::after,#topicText.faryo-smoke-safe-text::after{font-size:14px}.details-list dd.faryo-smoke-safe-text::after{font-size:12px}';
        document.head.appendChild(safeStyle);
        for (const [id, value] of Object.entries(smokeSafeText)) {
          const element = document.getElementById(id);
          if (!element) continue;
          element.dataset.faryoSmokeText = value;
          element.classList.add('faryo-smoke-safe-text');
        }
        const output = document.getElementById('output');
        if (output) {
          const richOutput = window.FaryoMarkdownAst.render(${JSON.stringify(uiFixtureSource)});
          output.className = 'output compact-blocks';
          output.innerHTML = [
            '<section class="compact-block user">Can you check whether this control argument is mathematically well posed?</section>',
            '<section class="compact-block output"><div class="markdown-body"><p>Yes. The structured history preserves the original notation, so the assumptions and conclusion can be checked directly.</p></div></section>',
            '<section class="compact-block user">Compare the admissible integral operators and render every equation clearly.</section>',
            '<section class="compact-process-line">Read the manuscript and verified the regularity assumptions</section>',
            '<section class="compact-block plan"><div class="compact-plan-title">Verification plan</div><div class="compact-plan-list"><div class="compact-plan-item">1. Check local Lipschitz regularity</div><div class="compact-plan-item">2. Check the growth condition</div></div></section>',
            '<section class="compact-block output"><div class="markdown-body">' + richOutput + '</div><button class="copy-output-block" type="button">⧉</button></section>',
            '<section class="compact-block user">Keep the final equations and implementation code easy to revisit.</section>',
            '<section class="compact-block output"><div class="markdown-body"><p>Done. Use the question rail to jump between these turns without losing your reading position.</p></div></section>',
            '<details class="compact-live-terminal" data-session="example" open><summary class="compact-live-title"><span class="live-dot"></span><span>Live from tmux</span><span class="compact-live-state">Agent working</span></summary><pre>Reviewing references…\\nRunning focused checks…\\nWaiting for the next structured update…</pre></details>',
          ].join('');
        }
        document.getElementById('errorBox')?.classList.add('hidden');
        const panel = ${JSON.stringify(uiScreenshotPanel)};
        if (panel === 'details') document.getElementById('detailsBtn')?.click();
        if (panel === 'session') {
          document.getElementById('draftState')?.click();
          const sessionMenu = document.getElementById('sessionMenu');
          if (sessionMenu) sessionMenu.innerHTML = '<div class="surface-panel-heading"><div><span class="surface-panel-eyebrow">Workspace</span><strong id="sessionPanelTitle">Running sessions</strong></div><button class="panel-close" type="button" data-close-panel aria-label="Close running sessions">×</button></div><button type="button" class="active"><span><strong>Research session</strong><small>Ubuntu Workstation · Project Alpha</small></span><em>Now</em></button><button type="button"><span><strong>Implementation review</strong><small>Ubuntu Workstation · Project Beta</small></span><em>Open</em></button><button type="button"><span><strong>Experiment monitor</strong><small>Ubuntu Workstation · Project Gamma</small></span><em>Open</em></button>';
        }
        if (output?.isConnected) output.replaceWith(output.cloneNode(true));
        const renderedOutput = document.getElementById('output');
        const questionNavigator = document.getElementById('questionNavigator');
        const questionMarkers = document.getElementById('questionNavMarkers');
        if (questionNavigator && questionMarkers) {
          questionNavigator.classList.remove('hidden');
          questionNavigator.classList.add('is-scrolling');
          questionNavigator.setAttribute('aria-hidden', 'false');
          questionMarkers.innerHTML = [0, 1, 2].map((index) => '<button type="button" class="question-nav-marker' + (index === 1 ? ' active' : '') + '" aria-current="' + (index === 1 ? 'step' : 'false') + '"><span class="question-nav-dot"></span></button>').join('');
          text('questionNavCurrent', '2');
          text('questionNavTotal', '3');
        }
        const displays = [...(renderedOutput?.querySelectorAll('.katex-display') || [])];
        const tableScroll = renderedOutput?.querySelector('.markdown-table-scroll');
        const codeBlock = renderedOutput?.querySelector('.markdown-code-block');
        const focus = ${JSON.stringify(uiScreenshotFocus)};
        const focusTarget = focus === 'table'
          ? tableScroll
          : focus === 'math'
            ? (displays[1] || displays[0])
            : focus === 'code'
              ? codeBlock
              : null;
        focusTarget?.scrollIntoView({ block: 'center', inline: 'nearest' });
        document.getElementById('bottomBtn')?.classList.remove('hidden');
        const focusRect = focusTarget?.getBoundingClientRect();
        const outputWidth = renderedOutput?.getBoundingClientRect().width || 0;
        const matrixRows = displays.map((display) => (
          display.querySelectorAll('.katex-mathml mtable > mtr').length
        ));
        return {
          katexCount: renderedOutput?.querySelectorAll('.katex').length || 0,
          displayCount: displays.length,
          tableCount: renderedOutput?.querySelectorAll('.markdown-table-scroll table').length || 0,
          tableScrollable: Boolean(tableScroll && tableScroll.scrollWidth > tableScroll.clientWidth + 1),
          codeBlockCount: renderedOutput?.querySelectorAll('.markdown-code-block').length || 0,
          highlightedCodeCount: renderedOutput?.querySelectorAll('.markdown-code-block pre.shiki').length || 0,
          matrixRows: Math.max(0, ...matrixRows),
          displaysContained: displays.length > 0 && displays.every((display) => (
            display.getBoundingClientRect().width <= outputWidth + 1
          )),
          focusVisible: !focus || Boolean(focusRect
            && focusRect.bottom > 60
            && focusRect.top < innerHeight - 96),
          pageHorizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
        };
      })()`,
      returnByValue: true,
    });
    const uiFixtureState = uiFixtureResult.result?.value || {};
    if (uiFixtureState.katexCount < 8 || uiFixtureState.displayCount !== 3
      || uiFixtureState.tableCount !== 1 || uiFixtureState.codeBlockCount !== 1
      || uiFixtureState.highlightedCodeCount !== 1 || uiFixtureState.matrixRows < 2
      || !uiFixtureState.displaysContained || !uiFixtureState.focusVisible
      || (viewportWidth > 0 && viewportWidth < 720 && !uiFixtureState.tableScrollable)
      || uiFixtureState.pageHorizontalOverflow) {
      throw new Error(`Faryo rich UI screenshot fixture failed: ${JSON.stringify(uiFixtureState)}`);
    }
    await send('Runtime.evaluate', { expression: 'document.fonts.ready', awaitPromise: true });
    await delay(uiScreenshotPanel ? 240 : 120);
    const jumpGeometryResult = await send('Runtime.evaluate', {
      expression: `(() => {
        const button = document.getElementById('bottomBtn');
        button?.classList.remove('hidden');
        const visible = Boolean(button && button.getClientRects().length);
        if (!visible) return { visible: false, rightAligned: true, overlapsFocus: false };
        const rect = button.getBoundingClientRect();
        const promptRect = document.querySelector('.prompt-shell')?.getBoundingClientRect();
        const displays = [...document.querySelectorAll('#output .katex-display')];
        const focus = ${JSON.stringify(uiScreenshotFocus)};
        const target = focus === 'table'
          ? document.querySelector('#output .markdown-table-scroll')
          : focus === 'math'
            ? (displays[1] || displays[0])
            : focus === 'code'
              ? document.querySelector('#output .markdown-code-block')
              : null;
        const targetRect = target?.getBoundingClientRect();
        const overlapsFocus = Boolean(targetRect
          && rect.left < targetRect.right
          && rect.right > targetRect.left
          && rect.top < targetRect.bottom
          && rect.bottom > targetRect.top);
        return {
          visible: true,
          rightAligned: rect.left + rect.width / 2 >= (promptRect
            ? promptRect.left + promptRect.width * 0.78
            : innerWidth * 0.75)
            && rect.right <= innerWidth - 6,
          overlapsFocus,
        };
      })()`,
      returnByValue: true,
    });
    const jumpGeometry = jumpGeometryResult.result?.value || {};
    if (!jumpGeometry.visible || !jumpGeometry.rightAligned || jumpGeometry.overlapsFocus) {
      throw new Error(`Scroll-to-latest control obscured rich output: ${JSON.stringify(jumpGeometry)}`);
    }
    console.log(`faryo-browser-latest-control=PASS visible=true focus=${uiScreenshotFocus || 'none'}`);
    const screenshot = await send('Page.captureScreenshot', {
      format: 'png',
      fromSurface: true,
    });
    await writeFile(uiScreenshotPath, Buffer.from(screenshot.data, 'base64'));
    console.log(`faryo-browser-ui-screenshot=${uiScreenshotPath}`);
  }

  if (sendMatrix.length) {
    for (let index = 0; index < sendMatrix.length; index += 1) {
      const item = sendMatrix[index];
      await send('Runtime.evaluate', {
        expression: `(() => {
          const input = document.getElementById('promptInput');
          input.value = ${JSON.stringify(item.text)};
          input.dispatchEvent(new Event('input', { bubbles: true }));
          document.getElementById('sendBtn').click();
        })()`,
      });

      let sendState = {};
      for (let attempt = 0; attempt < 100; attempt += 1) {
        await delay(100);
        const result = await send('Runtime.evaluate', {
          expression: `(() => ({
            inputValue: document.getElementById('promptInput')?.value || '',
            errorText: document.getElementById('errorBox')?.innerText || '',
            storedDrafts: Object.entries(sessionStorage).filter(([key]) => key.startsWith('faryoPromptDraft:')).map(([, value]) => value),
          }))()`,
          returnByValue: true,
        });
        sendState = result.result?.value || {};
        if (sendState.errorText || !sendState.inputValue) break;
      }
      if (sendState.errorText || sendState.inputValue || sendState.storedDrafts?.includes(item.text)) {
        const detail = privacySafe ? JSON.stringify({
          case: index + 1,
          errorVisible: Boolean(sendState.errorText),
          inputRetained: Boolean(sendState.inputValue),
          draftRetained: Boolean(sendState.storedDrafts?.includes(item.text)),
        }) : JSON.stringify(sendState);
        throw new Error(`Faryo browser matrix send failed: ${detail}`);
      }

      let outputFound = false;
      for (let attempt = 0; attempt < 120; attempt += 1) {
        await delay(100);
        const result = await send('Runtime.evaluate', {
          expression: `String(document.getElementById('output')?.innerText || '').includes(${JSON.stringify(item.expectedOutput)})`,
          returnByValue: true,
        });
        outputFound = Boolean(result.result?.value);
        if (outputFound) break;
      }
      if (!outputFound) throw new Error(`Faryo browser matrix ACK missing: case=${index + 1}`);
      await delay(25);
    }
    console.log(`faryo-browser-send-matrix=PASS count=${sendMatrix.length}`);
    console.log('faryo-browser-auto-update-matrix=PASS reloads=0');
  }

  if (attachmentName) {
    if (attachmentViaClipboard) {
      const nativeTextPaste = await send('Runtime.evaluate', {
        expression: `(() => {const input=document.getElementById('promptInput'),event=new Event('paste',{bubbles:true,cancelable:true});Object.defineProperty(event,'clipboardData',{value:{items:[{kind:'string',type:'text/plain'}],files:[],getData:(type)=>type==='text/plain'?'plain text':''}});input.dispatchEvent(event);return{prevented:event.defaultPrevented,previews:document.querySelectorAll('#attachmentPreview .attachment-thumb').length};})()`,
        returnByValue: true,
      });
      if (nativeTextPaste.result?.value?.prevented || nativeTextPaste.result?.value?.previews) {
        throw new Error('Plain-text clipboard paste was intercepted');
      }
      await send('Runtime.evaluate', {
        expression: `(() => {const input=document.getElementById('promptInput'),binary=atob(${JSON.stringify(attachmentContent)}),bytes=Uint8Array.from(binary,char=>char.charCodeAt(0)),file=new File([bytes],${JSON.stringify(attachmentName)},{type:'image/png'}),event=new Event('paste',{bubbles:true,cancelable:true});Object.defineProperty(event,'clipboardData',{value:{items:[{kind:'file',type:'image/png',getAsFile:()=>file}],files:[file],getData:(type)=>type==='text/plain'?'anonymous clipboard caption':''}});input.dispatchEvent(event);window.__faryoClipboardPasteDefaultPrevented=event.defaultPrevented;})()`,
      });
    } else {
      await send('Runtime.evaluate', {
        expression: `(() => {
          const input = document.getElementById('attachmentInput');
          const transfer = new DataTransfer();
          transfer.items.add(new File(
            [${JSON.stringify(attachmentContent)}],
            ${JSON.stringify(attachmentName)},
            { type: 'text/markdown' },
          ));
          input.files = transfer.files;
          input.dispatchEvent(new Event('change', { bubbles: true }));
        })()`,
      });
    }

    let uploadState = {};
    for (let attempt = 0; attempt < 120; attempt += 1) {
      await delay(100);
      const result = await send('Runtime.evaluate', {
        expression: `(() => {
          const thumb = document.querySelector('#attachmentPreview .attachment-thumb');
          return {
            found: Boolean(thumb),
            ready: Boolean(thumb?.classList.contains('ready')),
            failed: Boolean(thumb?.classList.contains('error')),
            errorText: document.getElementById('errorBox')?.innerText || '',
            previewCount: document.querySelectorAll('#attachmentPreview .attachment-thumb').length,
            inputValue: document.getElementById('promptInput')?.value || '',
            pastePrevented: Boolean(window.__faryoClipboardPasteDefaultPrevented),
            interactionVisible: Boolean(document.querySelector('.interaction-backdrop')?.getClientRects().length),
          };
        })()`,
        returnByValue: true,
      });
      uploadState = result.result?.value || {};
      if (uploadState.ready || uploadState.failed || uploadState.errorText) break;
    }
    if (!uploadState.found || !uploadState.ready || uploadState.failed || uploadState.errorText) {
      throw new Error(`Faryo browser attachment upload failed: ${JSON.stringify(uploadState)}`);
    }
    if (attachmentViaClipboard && (uploadState.previewCount !== 1 || uploadState.inputValue !== 'anonymous clipboard caption' || !uploadState.pastePrevented)) {
      throw new Error(`Faryo clipboard image paste failed: ${JSON.stringify(uploadState)}`);
    }
    if (uploadState.interactionVisible) throw new Error('Attachment preview incorrectly revealed a Codex interaction');

    await send('Runtime.evaluate', {
      expression: `(() => {
        const input = document.getElementById('promptInput');
        input.value = ${JSON.stringify(attachmentPrompt)};
        input.dispatchEvent(new Event('input', { bubbles: true }));
        document.getElementById('sendBtn').click();
      })()`,
    });

    let attachmentSendState = {};
    for (let attempt = 0; attempt < 120; attempt += 1) {
      await delay(100);
      const result = await send('Runtime.evaluate', {
        expression: `(() => ({
          inputValue: document.getElementById('promptInput')?.value || '',
          previewCount: document.querySelectorAll('#attachmentPreview .attachment-thumb').length,
          errorText: document.getElementById('errorBox')?.innerText || '',
        }))()`,
        returnByValue: true,
      });
      attachmentSendState = result.result?.value || {};
      if (attachmentSendState.errorText || (!attachmentSendState.inputValue && attachmentSendState.previewCount === 0)) break;
    }
    if (attachmentSendState.errorText || attachmentSendState.inputValue || attachmentSendState.previewCount !== 0) {
      const detail = privacySafe ? 'anonymous attachment case' : JSON.stringify(attachmentSendState);
      throw new Error(`Faryo browser attachment send failed: ${detail}`);
    }

    let attachmentAckFound = false;
    for (let attempt = 0; attempt < 120; attempt += 1) {
      await delay(100);
      const result = await send('Runtime.evaluate', {
        expression: `String(document.getElementById('output')?.innerText || '').includes(${JSON.stringify(attachmentExpectedOutput)})`,
        returnByValue: true,
      });
      attachmentAckFound = Boolean(result.result?.value);
      if (attachmentAckFound) break;
    }
    if (!attachmentAckFound) throw new Error('Faryo browser attachment ACK did not appear without reload');
    console.log(`faryo-browser-attachment-upload=PASS kind=${attachmentViaClipboard ? 'clipboard-image' : 'markdown'}`);
    console.log('faryo-browser-attachment-send=PASS reloads=0');
  }

  if (checkRecovery) {
    const offlineText = 'anonymous offline recovery';
    const offlineMarker = receiverAck(recoveryStartIndex, offlineText);
    await send('Network.enable');
    await send('Network.emulateNetworkConditions', {
      offline: true,
      latency: 0,
      downloadThroughput: 0,
      uploadThroughput: 0,
    });
    await delay(350);
    await injectReceiverTurn(recoveryTmuxSession, offlineText);
    await delay(250);
    await send('Network.emulateNetworkConditions', {
      offline: false,
      latency: 0,
      downloadThroughput: -1,
      uploadThroughput: -1,
    });
    await send('Runtime.evaluate', { expression: `window.dispatchEvent(new Event('online'))` });

    let offlineRecovered = false;
    for (let attempt = 0; attempt < 160; attempt += 1) {
      await delay(100);
      const result = await send('Runtime.evaluate', {
        expression: `String(document.getElementById('output')?.innerText || '').includes(${JSON.stringify(offlineMarker)})`,
        returnByValue: true,
      });
      offlineRecovered = Boolean(result.result?.value);
      if (offlineRecovered) break;
    }
    if (!offlineRecovered) throw new Error('Faryo did not recover missed output after network restoration');
    console.log('faryo-browser-network-recovery=PASS reloads=0');

    const hiddenText = 'anonymous background recovery';
    const hiddenMarker = receiverAck(recoveryStartIndex + 1, hiddenText);
    const hiddenResult = await send('Runtime.evaluate', {
      expression: `(() => {
        Object.defineProperty(document, 'hidden', { configurable: true, value: true });
        document.dispatchEvent(new Event('visibilitychange'));
        return document.hidden;
      })()`,
      returnByValue: true,
    });
    if (!hiddenResult.result?.value) throw new Error('Could not simulate a hidden Faryo page');
    await delay(250);
    await injectReceiverTurn(recoveryTmuxSession, hiddenText);
    await delay(250);
    await send('Runtime.evaluate', {
      expression: `(() => {
        delete document.hidden;
        document.dispatchEvent(new Event('visibilitychange'));
      })()`,
    });

    let hiddenRecovered = false;
    for (let attempt = 0; attempt < 120; attempt += 1) {
      await delay(100);
      const result = await send('Runtime.evaluate', {
        expression: `String(document.getElementById('output')?.innerText || '').includes(${JSON.stringify(hiddenMarker)})`,
        returnByValue: true,
      });
      hiddenRecovered = Boolean(result.result?.value);
      if (hiddenRecovered) break;
    }
    if (!hiddenRecovered) throw new Error('Faryo did not catch up after the page returned from background');
    console.log('faryo-browser-background-recovery=PASS reloads=0');
  }

  if (checkAmbiguousSend) {
    const ambiguousText = 'anonymous ambiguous delivery';
    const ambiguousMarker = receiverAck(ambiguousSendIndex, ambiguousText);
    await send('Runtime.evaluate', {
      expression: `(() => {
        const originalFetch = window.fetch.bind(window);
        window.__faryoOriginalFetch = originalFetch;
        window.__faryoAmbiguousSendInjected = false;
        window.fetch = async (...args) => {
          const target = String(args[0]?.url || args[0] || '');
          if (!window.__faryoAmbiguousSendInjected && target.includes('/api/send')) {
            window.__faryoAmbiguousSendInjected = true;
            const delivered = await originalFetch(...args);
            await delivered.clone().text();
            return new Response(JSON.stringify({ ok: false, error: 'simulated ambiguous delivery' }), {
              status: 504,
              headers: { 'Content-Type': 'application/json' },
            });
          }
          return originalFetch(...args);
        };
        const input = document.getElementById('promptInput');
        input.value = ${JSON.stringify(ambiguousText)};
        input.dispatchEvent(new Event('input', { bubbles: true }));
        document.getElementById('sendBtn').click();
      })()`,
    });

    let ambiguousState = {};
    for (let attempt = 0; attempt < 120; attempt += 1) {
      await delay(100);
      const result = await send('Runtime.evaluate', {
        expression: `(() => ({
          inputValue: document.getElementById('promptInput')?.value || '',
          errorText: document.getElementById('errorBox')?.innerText || '',
          injected: Boolean(window.__faryoAmbiguousSendInjected),
          outputFound: String(document.getElementById('output')?.innerText || '').includes(${JSON.stringify(ambiguousMarker)}),
        }))()`,
        returnByValue: true,
      });
      ambiguousState = result.result?.value || {};
      if (!ambiguousState.inputValue && !ambiguousState.errorText && ambiguousState.outputFound) break;
    }
    await send('Runtime.evaluate', { expression: 'if (window.__faryoOriginalFetch) window.fetch = window.__faryoOriginalFetch' });
    if (!ambiguousState.injected || ambiguousState.inputValue || ambiguousState.errorText || !ambiguousState.outputFound) {
      throw new Error(`Faryo ambiguous-send recovery failed: ${JSON.stringify(ambiguousState)}`);
    }
    console.log('faryo-browser-ambiguous-send-recovery=PASS duplicates=0 draft=cleared');
  }

  if (checkSessionSendIsolation) {
    const sessionDraftKey = (session) => `faryoPromptDraft:/txy:${session}`;
    const sessionPendingKey = (session) => `${sessionDraftKey(session)}:pending`;
    const clearDraftStorage = `for (const key of Object.keys(sessionStorage)) if (key.startsWith('faryoPromptDraft:')) sessionStorage.removeItem(key);`;
    const switchSessionExpression = (session) => `(() => {
      const menu = document.getElementById('sessionMenu');
      menu.innerHTML = '<button type="button" data-route="txy" data-session=${JSON.stringify(session)}>switch</button>';
      menu.querySelector('button').click();
    })()`;

    const retryText = 'anonymous cross session retry';
    await send('Runtime.evaluate', {
      expression: `(() => {
        ${clearDraftStorage}
        const originalFetch = window.fetch.bind(window);
        window.__faryoIsolationOriginalFetch = originalFetch;
        window.__faryoIsolationFailedOnce = false;
        window.fetch = async (...args) => {
          const target = String(args[0]?.url || args[0] || '');
          if (!window.__faryoIsolationFailedOnce && target.includes('/api/send')) {
            window.__faryoIsolationFailedOnce = true;
            throw new TypeError('anonymous pre-dispatch failure');
          }
          return originalFetch(...args);
        };
        const input = document.getElementById('promptInput');
        input.value = ${JSON.stringify(retryText)};
        input.dispatchEvent(new Event('input', { bubbles: true }));
        document.getElementById('sendBtn').click();
        setTimeout(() => ${switchSessionExpression(isolationSessionB)}, 50);
      })()`,
    });

    let retryState = {};
    for (let attempt = 0; attempt < 160; attempt += 1) {
      await delay(100);
      const result = await send('Runtime.evaluate', {
        expression: `(() => ({
          failedOnce: Boolean(window.__faryoIsolationFailedOnce),
          session: new URLSearchParams(location.search).get('session') || '',
          currentInput: document.getElementById('promptInput')?.value || '',
          aDraft: sessionStorage.getItem(${JSON.stringify(sessionDraftKey(isolationSessionA))}),
          aPending: sessionStorage.getItem(${JSON.stringify(sessionPendingKey(isolationSessionA))}),
          bDraft: sessionStorage.getItem(${JSON.stringify(sessionDraftKey(isolationSessionB))}),
          error: document.getElementById('errorBox')?.innerText || '',
        }))()`,
        returnByValue: true,
      });
      retryState = result.result?.value || {};
      if (retryState.failedOnce && retryState.session === isolationSessionB && retryState.aDraft === null && retryState.aPending === null) break;
    }
    await send('Runtime.evaluate', { expression: 'if (window.__faryoIsolationOriginalFetch) window.fetch = window.__faryoIsolationOriginalFetch' });
    if (!retryState.failedOnce || retryState.session !== isolationSessionB || retryState.aDraft !== null || retryState.aPending !== null || retryState.bDraft !== null || retryState.error) {
      throw new Error(`Faryo retry changed session state: ${JSON.stringify(retryState)}`);
    }

    await send('Page.navigate', { url: targetUrl });
    let reloaded = false;
    for (let attempt = 0; attempt < 100; attempt += 1) {
      await delay(100);
      const result = await send('Runtime.evaluate', {
        expression: `document.documentElement.dataset.faryoAppReady === '1'`,
        returnByValue: true,
      });
      reloaded = Boolean(result.result?.value);
      if (reloaded) break;
    }
    if (!reloaded) throw new Error('Faryo did not reload for delayed-response isolation');

    const sameText = 'anonymous same text independent draft';
    await send('Runtime.evaluate', {
      expression: `(() => {
        ${clearDraftStorage}
        sessionStorage.setItem(${JSON.stringify(sessionDraftKey(isolationSessionB))}, ${JSON.stringify(sameText)});
        const originalFetch = window.fetch.bind(window);
        window.__faryoIsolationOriginalFetch = originalFetch;
        window.__faryoIsolationHeld = false;
        window.fetch = async (...args) => {
          const target = String(args[0]?.url || args[0] || '');
          const response = await originalFetch(...args);
          if (!window.__faryoIsolationHeld && target.includes('/api/send')) {
            window.__faryoIsolationHeld = true;
            await new Promise((resolve) => { window.__faryoIsolationRelease = resolve; });
          }
          return response;
        };
        const input = document.getElementById('promptInput');
        input.value = ${JSON.stringify(sameText)};
        input.dispatchEvent(new Event('input', { bubbles: true }));
        document.getElementById('sendBtn').click();
      })()`,
    });
    let held = false;
    for (let attempt = 0; attempt < 120; attempt += 1) {
      await delay(100);
      const result = await send('Runtime.evaluate', { expression: 'window.__faryoIsolationHeld === true', returnByValue: true });
      held = Boolean(result.result?.value);
      if (held) break;
    }
    if (!held) throw new Error('Faryo accepted response could not be held for session isolation');
    await send('Runtime.evaluate', { expression: `${switchSessionExpression(isolationSessionB)}; window.__faryoIsolationRelease();` });

    let delayedState = {};
    for (let attempt = 0; attempt < 120; attempt += 1) {
      await delay(100);
      const result = await send('Runtime.evaluate', {
        expression: `(() => ({
          session: new URLSearchParams(location.search).get('session') || '',
          currentInput: document.getElementById('promptInput')?.value || '',
          aDraft: sessionStorage.getItem(${JSON.stringify(sessionDraftKey(isolationSessionA))}),
          aPending: sessionStorage.getItem(${JSON.stringify(sessionPendingKey(isolationSessionA))}),
          bDraft: sessionStorage.getItem(${JSON.stringify(sessionDraftKey(isolationSessionB))}),
          bPending: sessionStorage.getItem(${JSON.stringify(sessionPendingKey(isolationSessionB))}),
          error: document.getElementById('errorBox')?.innerText || '',
        }))()`,
        returnByValue: true,
      });
      delayedState = result.result?.value || {};
      if (delayedState.session === isolationSessionB && delayedState.aDraft === null && delayedState.aPending === null) break;
    }
    await send('Runtime.evaluate', { expression: 'if (window.__faryoIsolationOriginalFetch) window.fetch = window.__faryoIsolationOriginalFetch' });
    if (delayedState.session !== isolationSessionB || delayedState.currentInput !== sameText || delayedState.aDraft !== null || delayedState.aPending !== null || delayedState.bDraft !== sameText || delayedState.bPending !== null || delayedState.error) {
      throw new Error(`Faryo delayed response changed another session: ${JSON.stringify(delayedState)}`);
    }
    console.log('faryo-browser-session-send-isolation=PASS retry=original-session delayed-response=isolated');
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
