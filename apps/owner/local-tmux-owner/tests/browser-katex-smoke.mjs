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
const attachmentName = process.env.FARYO_SMOKE_ATTACHMENT_NAME || '';
const attachmentContent = process.env.FARYO_SMOKE_ATTACHMENT_CONTENT || '';
const attachmentPrompt = process.env.FARYO_SMOKE_ATTACHMENT_PROMPT || '';
const attachmentExpectedOutput = process.env.FARYO_SMOKE_ATTACHMENT_EXPECT_OUTPUT || '';
const checkRecovery = process.env.FARYO_SMOKE_CHECK_RECOVERY === '1';
const recoveryTmuxSession = process.env.FARYO_SMOKE_TMUX_SESSION || '';
const recoveryStartIndex = Number(process.env.FARYO_SMOKE_RECOVERY_START_INDEX || 0);
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
const checkAstFixture = process.env.FARYO_SMOKE_CHECK_AST_FIXTURE === '1';
const expectedLivePanelState = process.env.FARYO_SMOKE_EXPECT_LIVE_PANEL_STATE || '';
const expectedKeyNavState = process.env.FARYO_SMOKE_EXPECT_KEY_NAV || 'hidden';
const viewportWidth = Number(process.env.FARYO_SMOKE_VIEWPORT_WIDTH || 0);
const viewportHeight = Number(process.env.FARYO_SMOKE_VIEWPORT_HEIGHT || 0);
const smokeTheme = process.env.FARYO_SMOKE_THEME || '';
const screenshotPath = process.env.FARYO_SMOKE_SCREENSHOT || '';
const uiScreenshotPath = process.env.FARYO_SMOKE_UI_SCREENSHOT || '';
const uiScreenshotPanel = process.env.FARYO_SMOKE_UI_PANEL || '';
const uiScreenshotFocus = process.env.FARYO_SMOKE_UI_FOCUS || '';
const expectedTex = JSON.parse(process.env.FARYO_SMOKE_EXPECT_TEX || '[]');
const expectedOutput = process.env.FARYO_SMOKE_EXPECT_OUTPUT || '';
const minMatrixRows = Number(process.env.FARYO_SMOKE_MIN_MATRIX_ROWS || 0);
const minKatex = Number(process.env.FARYO_SMOKE_MIN_KATEX ?? 2);
const minDisplay = Number(process.env.FARYO_SMOKE_MIN_DISPLAY ?? 1);
const minTables = Number(process.env.FARYO_SMOKE_MIN_TABLES || 0);
const minTableKatex = Number(process.env.FARYO_SMOKE_MIN_TABLE_KATEX || 0);
const minProtectedLinks = Number(process.env.FARYO_SMOKE_MIN_PROTECTED_LINKS || 0);
const minProtectedImages = Number(process.env.FARYO_SMOKE_MIN_PROTECTED_IMAGES || 0);
const maxBareTex = Number(process.env.FARYO_SMOKE_MAX_BARE_TEX ?? -1);
const screenshotTex = process.env.FARYO_SMOKE_SCREENSHOT_TEX || expectedTex.at(-1) || '';
const loginUser = process.env.FARYO_SMOKE_LOGIN_USER || '';
const loginPasswordFile = process.env.FARYO_SMOKE_LOGIN_PASSWORD_FILE || '';
const loginPassword = loginPasswordFile ? (await readFile(loginPasswordFile, 'utf8')).trim() : '';
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
const uiFixtureSource = [
  '## 结论',
  '',
  '公式、表格、列表、引用和代码由同一个 AST 管线渲染；长内容应在自己的容器内滚动，而不是挤压整页。',
  '',
  '| 算子 | 建议 |',
  '| --- | --- |',
  '| \\(\\Psi_i=\\eta_i\\) | 精确恢复基准结构 |',
  '| \\(\\Psi_i=e_i\\) | 标准误差积分 |',
  '| \\(\\Psi_i=\\vartheta_{i,\\nu_i}(k_i)e_i\\) | 保留带下标的调度项，并允许这一列横向滚动 |',
  '| \\(\\Psi_i=\\delta_i\\tanh(e_i/\\gamma_i)\\) | 非线性积分增益 |',
  '| \\(\\Psi_i=e_i-\\sigma_i z_i\\) | 泄漏修正机制 |',
  '',
  '> 宽公式保持单一数学布局，不拆成逐字符竖排文本。',
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
  '### 实现检查',
  '',
  '- 行内代码 `render(markdown)` 不应触发公式解析。',
  '- 围栏代码保持原始换行，并按需加载高亮语言。',
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
if (!['hidden', 'visible'].includes(expectedKeyNavState)) {
  throw new Error('FARYO_SMOKE_EXPECT_KEY_NAV must be hidden or visible');
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
  if (['light', 'dark', 'system'].includes(smokeTheme)) {
    await send('Page.addScriptToEvaluateOnNewDocument', {
      source: `localStorage.setItem('faryoTheme', ${JSON.stringify(smokeTheme)});`,
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
        const livePanel = output?.querySelector('.compact-live-terminal');
        const statusLine = document.querySelector('.status-line');
        const keyNav = document.querySelector('.key-nav');
        const promptRect = promptShell?.getBoundingClientRect();
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
          captureSource: String(output?.dataset.captureSource || ''),
          captureWarningCount: output?.querySelectorAll('.compact-capture-warning').length || 0,
          stableBlockState: {
            apiReady: typeof window.FaryoStableBlocks?.reconcile === 'function',
            keyedCount: output?.querySelectorAll('[data-faryo-block-key]').length || 0,
            created: Number(output?.dataset.compactCreated || -1),
            reused: Number(output?.dataset.compactReused || -1),
            stable: Number(output?.dataset.compactStable || -1),
          },
          viewport: { width: innerWidth, height: innerHeight },
          pageHorizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
          outputHorizontalOverflow: Boolean(outputWrap && outputWrap.scrollWidth > outputWrap.clientWidth + 1),
          ownerLayout: {
            ui: String(document.documentElement.dataset.faryoUi || ''),
            outputWidth: Math.round(output?.getBoundingClientRect().width || 0),
            prompt: promptRect ? {
              left: Math.round(promptRect.left),
              right: Math.round(promptRect.right),
              width: Math.round(promptRect.width),
              height: Math.round(promptRect.height),
            } : null,
            visibleComposerControls,
            statusCollapsed: Boolean(statusLine?.classList.contains('collapsed')),
            statusAutoExpanded: Boolean(statusLine?.classList.contains('auto-expanded')),
            keyNavVisible: Boolean(keyNav && keyNav.getClientRects().length),
            livePanel: livePanel ? { open: Boolean(livePanel.open), session: String(livePanel.dataset.session || '') } : null,
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
      && state.protectedImagePendingCount === 0;
    if (skipRenderChecks
      ? state.domReady && (!checkOwnerLayout || state.stableBlockState?.keyedCount >= 1) && protectedResourcesReady
      : state.ready && protectedResourcesReady) break;
  }

  const protectedResourcesReady = state.protectedLinkCount >= minProtectedLinks
    && state.protectedImageCount >= minProtectedImages
    && state.protectedImagePendingCount === 0;
  if (!(skipRenderChecks
    ? state.domReady && (!checkOwnerLayout || state.stableBlockState?.keyedCount >= 1) && protectedResourcesReady
    : state.ready && protectedResourcesReady)) {
    throw new Error(`KaTeX did not appear in the live Faryo DOM: ${JSON.stringify(state)}`);
  }
  if (state.ownerTokenDomCount) {
    throw new Error(`Owner token appeared in ${state.ownerTokenDomCount} DOM attributes`);
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
    if (state.viewport.width < 720 && prompt.width < state.viewport.width - 24) {
      throw new Error(`Mobile Owner composer is unexpectedly narrow: ${JSON.stringify({ viewport: state.viewport, prompt })}`);
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
    const expectKeyNavVisible = expectedKeyNavState === 'visible';
    if (!layout.statusCollapsed || layout.keyNavVisible !== expectKeyNavVisible
      || (expectKeyNavVisible && !layout.statusAutoExpanded)) {
      throw new Error(`Owner terminal control visibility is wrong: ${JSON.stringify({ expectedKeyNavState, layout })}`);
    }
    const keyNavResult = await send('Runtime.evaluate', {
      expression: `(() => {
        const line = document.querySelector('.status-line');
        const footer = document.querySelector('footer');
        const nav = document.querySelector('.key-nav');
        const wasAutoExpanded = Boolean(line?.classList.contains('auto-expanded'));
        line?.classList.add('auto-expanded');
        footer?.classList.add('auto-expanded');
        const expandedVisible = Boolean(nav && nav.getClientRects().length);
        line?.classList.toggle('auto-expanded', wasAutoExpanded);
        footer?.classList.toggle('auto-expanded', wasAutoExpanded);
        return { expandedVisible, restoredVisible: Boolean(nav && nav.getClientRects().length) };
      })()`,
      returnByValue: true,
    });
    const keyNavState = keyNavResult.result?.value || {};
    if (!keyNavState.expandedVisible || keyNavState.restoredVisible !== expectKeyNavVisible) {
      throw new Error(`Owner terminal controls did not follow the approval expansion state: ${JSON.stringify(keyNavState)}`);
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
    console.log(`faryo-browser-owner-layout=PASS viewport=${state.viewport.width}x${state.viewport.height}`);
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
    if (expectStructured && (state.captureSource !== 'codex-app-server' || state.captureWarningCount)) {
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
        expression: `(async () => {
          let pane = document.querySelector('.compact-live-terminal pre');
          const replaced = Boolean(pane && pane.dataset.faryoSmokeScroll !== 'waiting');
          if (replaced) {
            await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
            pane = document.querySelector('.compact-live-terminal pre');
          }
          const target = Number(window.__faryoSmokeLiveScrollTarget || 0);
          return {
            replaced,
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
      if (preserved.replaced) break;
    }
    if (!preserved.replaced) throw new Error('Live from tmux did not refresh during the scroll test');
    if (preserved.delta > 2 || preserved.delta < 0) throw new Error(`Live from tmux moved the reading position: ${JSON.stringify(preserved)}`);
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

  if (uiScreenshotPath) {
    const uiFixtureResult = await send('Runtime.evaluate', {
      expression: `(() => {
        const text = (id, value) => { const element = document.getElementById(id); if (element) element.textContent = value; };
        text('ownerText', 'Ubuntu Workstation');
        text('topicText', 'Research session');
        text('draftState', 'Project workspace');
        text('ctxText', 'Ctx 42%');
        text('modelText', 'Agent ready');
        text('phasePill', 'git clean');
        text('detailsSession', 'Research session');
        text('detailsOwner', 'Ubuntu Workstation');
        text('detailsModel', 'Agent model');
        text('detailsContext', 'Ctx 42%');
        text('detailsGit', 'git clean');
        text('detailsSource', 'structured history');
        text('detailsConnection', 'live');
        const smokeSafeText = {
          ownerText: 'Ubuntu Workstation', topicText: 'Research session', draftState: 'Project workspace',
          ctxText: 'Ctx 42%', modelText: 'Agent ready', phasePill: 'git clean',
          detailsSession: 'Research session', detailsOwner: 'Ubuntu Workstation', detailsModel: 'Agent model',
          detailsContext: 'Ctx 42%', detailsGit: 'git clean', detailsSource: 'structured history', detailsConnection: 'live',
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
            '<section class="compact-block user">请检查这一节的推导，并给出修改建议。</section>',
            '<section class="compact-process-line">Read manuscript and compared the assumptions</section>',
            '<section class="compact-block plan"><div class="compact-plan-title">Plan</div><div class="compact-plan-list"><div class="compact-plan-item">1. Verify the regularity assumptions</div><div class="compact-plan-item">2. Tighten the theorem wording</div></div></section>',
            '<section class="compact-block output"><div class="markdown-body">' + richOutput + '</div><button class="copy-output-block" type="button">⧉</button></section>',
            '<details class="compact-live-terminal" data-session="example" open><summary class="compact-live-title"><span class="live-dot"></span><span>Live from tmux</span><span class="compact-live-state">Agent working</span></summary><pre>Reviewing references…\\nRunning focused checks…\\nWaiting for the next structured update…</pre></details>',
          ].join('');
        }
        document.getElementById('bottomBtn')?.classList.add('hidden');
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
    if (!jumpGeometry.rightAligned || jumpGeometry.overlapsFocus) {
      throw new Error(`Scroll-to-latest control obscured rich output: ${JSON.stringify(jumpGeometry)}`);
    }
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
    console.log('faryo-browser-attachment-upload=PASS kind=markdown');
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
