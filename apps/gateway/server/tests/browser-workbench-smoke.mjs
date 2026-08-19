import { spawn } from 'node:child_process';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';

const targetUrl = process.env.FARYO_SMOKE_URL;
const loginUser = process.env.FARYO_SMOKE_LOGIN_USER || '';
const passwordFile = process.env.FARYO_SMOKE_LOGIN_PASSWORD_FILE || '';
const loginPassword = passwordFile ? (await readFile(passwordFile, 'utf8')).trim() : '';
const authCookie = process.env.FARYO_SMOKE_AUTH_COOKIE || '';
const startCodex = process.env.FARYO_SMOKE_START_CODEX === '1';
const expectedActive = Number(process.env.FARYO_SMOKE_EXPECT_ACTIVE || 0);
const expectedManaged = Number(process.env.FARYO_SMOKE_EXPECT_MANAGED || -1);
const expectedDesktop = Number(process.env.FARYO_SMOKE_EXPECT_DESKTOP || -1);
const expectedRouteLabel = process.env.FARYO_SMOKE_EXPECT_ROUTE_LABEL || '';
const viewportWidth = Number(process.env.FARYO_SMOKE_VIEWPORT_WIDTH || 430);
const viewportHeight = Number(process.env.FARYO_SMOKE_VIEWPORT_HEIGHT || 820);
const smokeTheme = process.env.FARYO_SMOKE_THEME || '';
const directoryScreenshotPath = process.env.FARYO_SMOKE_DIRECTORY_SCREENSHOT || '';
const hostResolverRules = process.env.FARYO_SMOKE_HOST_RESOLVER_RULES || 'MAP * ~NOTFOUND, EXCLUDE 127.0.0.1';
const chromeBin = process.env.CHROME_BIN || '/usr/bin/google-chrome';

if (!targetUrl) throw new Error('FARYO_SMOKE_URL is required');

const delay = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));
const profile = await mkdtemp(path.join(os.tmpdir(), 'faryo-workbench-chrome-'));
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
    `--window-size=${viewportWidth},${viewportHeight}`,
    `--host-resolver-rules=${hostResolverRules}`,
    `--user-data-dir=${profile}`,
    '--remote-debugging-port=0',
    'about:blank',
  ], { stdio: ['ignore', 'ignore', 'pipe'] });

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

  const debuggingPort = new URL(browserWebSocketUrl).port;
  const targetResponse = await fetch(`http://127.0.0.1:${debuggingPort}/json/new?about%3Ablank`, { method: 'PUT' });
  if (!targetResponse.ok) throw new Error(`Could not create Chrome target: HTTP ${targetResponse.status}`);
  const target = await targetResponse.json();

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
    const callbacks = pending.get(message.id);
    pending.delete(message.id);
    if (message.error) callbacks.reject(new Error(message.error.message));
    else callbacks.resolve(message.result);
  });
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++nextId;
    pending.set(id, { resolve, reject });
    socket.send(JSON.stringify({ id, method, params }));
  });
  const evaluate = async (expression) => {
    const result = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
    if (result.exceptionDetails) {
      throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text || 'Browser evaluation failed');
    }
    return result.result?.value;
  };

  await send('Page.enable');
  await send('Runtime.enable');
  await send('Network.enable');
  if (authCookie) {
    const separator = authCookie.indexOf('=');
    if (separator <= 0) throw new Error('FARYO_SMOKE_AUTH_COOKIE must be name=value');
    // A __Host- cookie cannot be installed for the loopback HTTP smoke URL.
    // CDP request headers preserve the production cookie contract while
    // keeping this local-only credential out of page JavaScript.
    await send('Network.setExtraHTTPHeaders', { headers: { Cookie: authCookie } });
  }
  await send('Emulation.setDeviceMetricsOverride', {
    width: viewportWidth,
    height: viewportHeight,
    deviceScaleFactor: 1,
    mobile: viewportWidth < 720,
  });
  await send('Page.navigate', { url: targetUrl });

  if (loginUser && loginPassword) {
    let loginReady = false;
    for (let attempt = 0; attempt < 100; attempt += 1) {
      await delay(100);
      loginReady = Boolean(await evaluate("document.querySelector('input[name=\"username\"]') && document.querySelector('input[name=\"password\"]')"));
      if (loginReady) break;
    }
    if (!loginReady) throw new Error('Faryo Gateway login form did not appear');
    await evaluate(`(() => {
      const username = document.querySelector('input[name="username"]');
      const password = document.querySelector('input[name="password"]');
      username.value = ${JSON.stringify(loginUser)};
      password.value = ${JSON.stringify(loginPassword)};
      username.form.requestSubmit();
    })()`);
  }

  if (smokeTheme) {
    let appearanceReady = false;
    for (let attempt = 0; attempt < 100; attempt += 1) {
      await delay(100);
      appearanceReady = Boolean(await evaluate("document.getElementById('activeSessionList') && window.FaryoAppearance"));
      if (appearanceReady) break;
    }
    if (!appearanceReady) throw new Error('Faryo appearance controls did not become ready');
    await evaluate(`(() => {
      localStorage.setItem('faryoTheme', ${JSON.stringify(smokeTheme)});
      window.FaryoAppearance.apply();
    })()`);
  }

  let first = {};
  for (let attempt = 0; attempt < 100; attempt += 1) {
    await delay(150);
    first = await evaluate(`(() => {
      const activeList = document.getElementById('activeSessionList');
      const historyList = document.getElementById('sessionList');
      const active = [...(activeList?.querySelectorAll('.session-card') || [])];
      const history = [...(historyList?.querySelectorAll('.session-card') || [])];
      const activeIds = new Set(active.map((item) => item.dataset.agentSessionId).filter(Boolean));
      const historyIds = history.map((item) => item.dataset.agentSessionId).filter(Boolean);
      const historySignature = historyIds.join('|');
      const style = historyList ? getComputedStyle(historyList) : null;
      const rootStyle = getComputedStyle(document.documentElement);
      const launchers = [...document.querySelectorAll('#newSessionSlot .launcher-card')];
      const packageList = document.getElementById('packageList');
      window.__faryoHistoryPageOne = historySignature;
      return {
        ready: activeList && historyList && history.length === 10 && document.getElementById('historyPageInput')?.value === '1' && Number(document.getElementById('historyPageTotal')?.textContent) > 2,
        activeCount: active.length,
        historyCount: history.length,
        firstHistoryTitle: history[0]?.querySelector('.session-title')?.textContent?.trim() || '',
        managedCount: active.filter((item) => item.querySelector('.close-session')).length,
        desktopCount: active.filter((item) => item.querySelector('.session-meta')?.textContent.includes('Desktop tmux')).length,
        sectionsSeparate: history.every((item) => !item.dataset.session) && active.every((item) => item.dataset.session),
        noDuplicates: historyIds.every((id) => !activeIds.has(id)),
        previousDisabled: Boolean(document.getElementById('historyPrev')?.disabled),
        nextEnabled: !document.getElementById('historyNext')?.disabled,
        routeLabelMatches: !${JSON.stringify(expectedRouteLabel)} || [...document.querySelectorAll('.route-chip strong')].some((item) => item.textContent.trim() === ${JSON.stringify(expectedRouteLabel)}),
        overflowY: style?.overflowY || '',
        scrollable: Boolean(historyList && historyList.scrollHeight > historyList.clientHeight),
        fileTransferReady: Boolean(
          document.getElementById('newPackage')?.textContent.includes('Choose files')
          && (packageList?.querySelector('.send-package') || packageList?.textContent.includes('send them to a session'))
        ),
        launcherCount: launchers.length,
        launcherLabelsClear: launchers.every((item) => item.textContent.includes('Start ') && !item.textContent.includes('$ ')),
        launcherIsCodexOnly: launchers.length === 1 && launchers[0].textContent.includes('Start Codex'),
        palette: {
          bg: rootStyle.getPropertyValue('--bg').trim().toLowerCase(),
          accent: rootStyle.getPropertyValue('--accent').trim().toLowerCase(),
        },
        viewport: { width: innerWidth, height: innerHeight },
        pageHorizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
        historyToolsReady: Boolean(document.getElementById('historySearchInput') && document.querySelector('[data-history-period="7d"]') && document.querySelector('[data-history-archive="archived"]')),
      };
    })()`);
    if (first?.ready) break;
  }

  if (!first?.ready) throw new Error('Workbench did not render a ten-item first history page');
  if (expectedActive && first.activeCount !== expectedActive) throw new Error(`Unexpected active session count: ${first.activeCount}`);
  if (expectedManaged >= 0 && first.managedCount !== expectedManaged) throw new Error(`Unexpected managed session count: ${first.managedCount}`);
  if (expectedDesktop >= 0 && first.desktopCount !== expectedDesktop) throw new Error(`Unexpected desktop session count: ${first.desktopCount}`);
  if (!first.sectionsSeparate || !first.noDuplicates) throw new Error('Active sessions leaked into Session History');
  if (!first.previousDisabled || !first.nextEnabled) throw new Error('First-page navigation state is incorrect');
  if (!first.routeLabelMatches) throw new Error('Configured route label did not render');
  if (!['auto', 'scroll'].includes(first.overflowY) || !first.scrollable) throw new Error('Session History is not independently scrollable');
  if (!first.fileTransferReady) throw new Error('Files-to-session controls are not discoverable');
  if (!first.launcherCount || !first.launcherLabelsClear) throw new Error('New-session launchers are unclear');
  if (!first.launcherIsCodexOnly) throw new Error('Retired agent launchers are still visible');
  if (!first.historyToolsReady || !first.firstHistoryTitle) throw new Error('Session History search controls are not ready');
  const validPalettes = new Set(['#f6f7f9:#5369e7', '#0f1115:#7188ff']);
  if (!validPalettes.has(`${first.palette.bg}:${first.palette.accent}`)) throw new Error(`Unexpected shared palette: ${JSON.stringify(first.palette)}`);
  const expectedPalette = { light: '#f6f7f9:#5369e7', dark: '#0f1115:#7188ff' }[smokeTheme];
  if (expectedPalette && `${first.palette.bg}:${first.palette.accent}` !== expectedPalette) throw new Error(`Theme palette mismatch: ${JSON.stringify(first.palette)}`);
  if (first.pageHorizontalOverflow) throw new Error(`Gateway workbench overflowed horizontally: ${JSON.stringify(first.viewport)}`);

  const historyQuery = first.firstHistoryTitle.slice(0, Math.min(10, first.firstHistoryTitle.length));
  await evaluate(`(() => {const input=document.getElementById('historySearchInput');input.value=${JSON.stringify(historyQuery)};input.dispatchEvent(new Event('input',{bubbles:true}));})()`);
  let searched = {};
  for (let attempt = 0; attempt < 100; attempt += 1) {
    await delay(100);
    searched = await evaluate(`(() => {const cards=[...document.querySelectorAll('#sessionList .session-card')],params=new URLSearchParams(location.search),cached=JSON.parse(sessionStorage.getItem('faryoWorkbenchSnapshot')||'null');return{ready:params.get('q')===${JSON.stringify(historyQuery)}&&cards.length>0,count:cards.length,activeCount:document.querySelectorAll('#activeSessionList .session-card').length,cacheHasSearch:cached?.data?.history?.filter?.q===${JSON.stringify(historyQuery)},noHorizontalOverflow:document.documentElement.scrollWidth<=document.documentElement.clientWidth+1};})()`);
    if (searched?.ready) break;
  }
  if (!searched.ready || searched.count > 10 || searched.activeCount !== first.activeCount || searched.cacheHasSearch || !searched.noHorizontalOverflow) {
    throw new Error(`Session History search failed: ${JSON.stringify(searched)}`);
  }
  await evaluate("document.getElementById('historySearchClear').click()");
  let searchCleared = false;
  for (let attempt = 0; attempt < 100; attempt += 1) {
    await delay(100);
    searchCleared = Boolean(await evaluate("!new URLSearchParams(location.search).has('q') && document.querySelectorAll('#sessionList .session-card').length === 10"));
    if (searchCleared) break;
  }
  if (!searchCleared) throw new Error('Clearing Session History search did not restore page one');

  await evaluate("document.querySelector('[data-history-period=\"7d\"]').click()");
  let periodApplied = false;
  for (let attempt = 0; attempt < 100; attempt += 1) {
    await delay(100);
    periodApplied = Boolean(await evaluate("new URLSearchParams(location.search).get('period') === '7d' && document.querySelector('[data-history-period=\"7d\"]').classList.contains('active')"));
    if (periodApplied) break;
  }
  if (!periodApplied) throw new Error('Session History period filter did not apply');
  await evaluate("document.querySelector('[data-history-period=\"all\"]').click()");
  for (let attempt = 0; attempt < 100; attempt += 1) {
    await delay(100);
    const restored = await evaluate("!new URLSearchParams(location.search).has('period') && document.querySelectorAll('#sessionList .session-card').length === 10");
    if (restored) break;
    if (attempt === 99) throw new Error('Session History period filter did not restore all-time results');
  }

  const responseErrors = await evaluate(`(async () => {
    const capture = async (response, label) => {
      try { await readJsonResponse(response, label); return { failed: false }; }
      catch (error) { return { failed: true, message: error.message, retryable: Boolean(error.retryable) }; }
    };
    const temporary = await capture(new Response('<!DOCTYPE html><html><title>Bad gateway</title></html>', { status: 502, headers: { 'Content-Type': 'text/html' } }), 'Start Codex');
    const expired = await capture(new Response('<!DOCTYPE html><html><title>Cloudflare Access</title></html>', { status: 200, headers: { 'Content-Type': 'text/html' } }), 'Start Codex');
    const json = await readJsonResponse(new Response('{"ok":true,"value":7}', { status: 200, headers: { 'Content-Type': 'application/json' } }), 'Start Codex');
    return { temporary, expired, jsonValue: json.value };
  })()`);
  if (!responseErrors?.temporary?.failed || !responseErrors.temporary.retryable
    || !responseErrors.temporary.message.includes('temporarily unavailable')
    || !responseErrors?.expired?.failed || responseErrors.expired.retryable
    || !responseErrors.expired.message.includes('sign-in expired')
    || responseErrors.jsonValue !== 7) {
    throw new Error(`Gateway API response handling is not robust: ${JSON.stringify(responseErrors)}`);
  }

  const directoryOverlap = await evaluate(`(() => {
    const data = {
      path: '/workspace/parent',
      parent: '/workspace',
      roots: [{ path: '/workspace', displayPath: '/workspace' }],
      directories: [
        { name: 'shared-project', path: '/workspace/parent/shared-project' },
        { name: 'other-project', path: '/workspace/parent/other-project' },
      ],
    };
    const recent = [
      { label: 'shared-project', value: '/workspace/parent/shared-project', path: '/workspace/parent/shared-project' },
      { label: 'shared-project duplicate', value: '/workspace/parent/shared-project', path: '/workspace/parent/shared-project' },
    ];
    const model = directoryPickerModel(data, recent, '', false);
    const filtered = directoryPickerModel(data, recent, 'shared', false);
    return {
      recentCopies: model.recent.filter((item) => item.path === '/workspace/parent/shared-project').length,
      folderCopies: model.folders.filter((item) => item.path === '/workspace/parent/shared-project').length,
      parentFirst: model.folders[0]?.label === '..',
      filteredRecent: filtered.recent.some((item) => item.label === 'shared-project'),
      filteredFolder: filtered.folders.some((item) => item.label === 'shared-project'),
      filteredParent: filtered.folders[0]?.label === '..',
    };
  })()`);
  if (directoryOverlap?.recentCopies !== 1 || directoryOverlap.folderCopies !== 1
    || !directoryOverlap.parentFirst || !directoryOverlap.filteredRecent
    || !directoryOverlap.filteredFolder || !directoryOverlap.filteredParent) {
    throw new Error(`Recent shortcuts hid a real child folder: ${JSON.stringify(directoryOverlap)}`);
  }

  await evaluate("document.querySelector('#newSessionSlot .launcher-card').click()");
  let launchConfirmation = {};
  for (let attempt = 0; attempt < 40; attempt += 1) {
    await delay(50);
    launchConfirmation = await evaluate(`(() => ({
      open: document.getElementById('modal')?.classList.contains('open'),
      title: document.getElementById('modalTitle')?.textContent || '',
      choices: document.querySelectorAll('#modalChoices .choice-btn').length,
      hasCancel: [...document.querySelectorAll('#modalActions button')].some((item) => item.textContent === 'Cancel'),
    }))()`);
    if (launchConfirmation?.open) break;
  }
  const explicitLaunchTitle = launchConfirmation.title.startsWith('Start ') || launchConfirmation.title === 'Agent limit reached';
  if (!launchConfirmation.open || !explicitLaunchTitle || !launchConfirmation.choices || !launchConfirmation.hasCancel) {
    throw new Error(`Launcher confirmation did not open: ${JSON.stringify(launchConfirmation)}`);
  }
  if (launchConfirmation.title.startsWith('Start ')) {
    await evaluate("document.querySelector('#modalChoices .choice-btn:not([disabled])')?.click()");
    let cwdConfirmation = {};
    for (let attempt = 0; attempt < 40; attempt += 1) {
      await delay(50);
      cwdConfirmation = await evaluate(`(() => ({
        open: document.getElementById('modal')?.classList.contains('open'),
        directoryMode: document.getElementById('modal')?.classList.contains('directory-mode'),
        title: document.getElementById('modalTitle')?.textContent || '',
        body: document.getElementById('modalBody')?.textContent || '',
        breadcrumbs: document.querySelectorAll('#directoryBreadcrumb .directory-crumb').length,
        breadcrumbLabelsClean: [...document.querySelectorAll('#directoryBreadcrumb .directory-crumb')].every((item) => !item.textContent.includes('/')),
        currentCrumb: document.querySelector('#directoryBreadcrumb .directory-crumb[aria-current="location"]')?.textContent || '',
        headerBackAbsent: !document.getElementById('modalBack'),
        searchVisible: (() => { const item=document.getElementById('directorySearch');return Boolean(item&&item.getClientRects().length); })(),
        sections: [...document.querySelectorAll('#modalChoices .directory-section')].map((item) => item.dataset.directorySection),
        recentCount: document.querySelectorAll('#modalChoices .directory-row-recent').length,
        folderCount: document.querySelectorAll('#modalChoices .directory-row-folder').length,
        parentRowFirst: (() => { const section=document.querySelector('#modalChoices [data-directory-section="folders"]'),row=section?.querySelector('.directory-row');return Boolean(row?.classList.contains('directory-row-parent')&&row.querySelector('strong')?.textContent==='..'&&row.querySelector('small')?.textContent==='Parent folder'); })(),
        folderRowsHaveNoPaths: !document.querySelector('#modalChoices .directory-row-folder small'),
        flatPrefixesAbsent: ![...document.querySelectorAll('#modalChoices strong')].some((item) => /^(?:Use this folder|Parent folder|Root ·|Recent ·|Folder ·)/.test(item.textContent)),
        hasCancel: [...document.querySelectorAll('#modalActions button')].some((item) => item.textContent === 'Cancel'),
        hasPrimary: [...document.querySelectorAll('#modalActions button')].some((item) => item.textContent === 'Start Codex here'),
        cancelVisible: (() => { const item=[...document.querySelectorAll('#modalActions button')].find((button)=>button.textContent==='Cancel'),rect=item?.getBoundingClientRect();return Boolean(rect&&rect.top>=0&&rect.bottom<=innerHeight); })(),
        sheetContained: (() => { const rect=document.querySelector('#modal .sheet')?.getBoundingClientRect();return Boolean(rect&&rect.top>=0&&rect.bottom<=innerHeight); })(),
        listScrollable: (() => { const list=document.getElementById('modalChoices');return Boolean(list&&list.scrollHeight>list.clientHeight); })(),
        listOverflowY: (() => { const list=document.getElementById('modalChoices');return list?getComputedStyle(list).overflowY:''; })(),
        actionsBelowList: (() => { const list=document.getElementById('modalChoices')?.getBoundingClientRect(),actions=document.getElementById('modalActions')?.getBoundingClientRect();return Boolean(list&&actions&&list.bottom<=actions.top+1); })(),
        noHorizontalOverflow: document.documentElement.scrollWidth<=document.documentElement.clientWidth+1,
      }))()`);
      if (cwdConfirmation?.title === 'Choose working directory') break;
    }
    if (!cwdConfirmation.open || cwdConfirmation.title !== 'Choose working directory'
      || !cwdConfirmation.directoryMode || !cwdConfirmation.breadcrumbs || cwdConfirmation.breadcrumbs > 4
      || !cwdConfirmation.breadcrumbLabelsClean || !cwdConfirmation.currentCrumb
      || !cwdConfirmation.headerBackAbsent || !cwdConfirmation.searchVisible
      || !cwdConfirmation.sections.includes('folders') || cwdConfirmation.recentCount > 4
      || !cwdConfirmation.folderCount || !cwdConfirmation.parentRowFirst || !cwdConfirmation.folderRowsHaveNoPaths
      || !cwdConfirmation.flatPrefixesAbsent || !cwdConfirmation.hasCancel || !cwdConfirmation.hasPrimary
      || !cwdConfirmation.cancelVisible || !cwdConfirmation.sheetContained || !cwdConfirmation.actionsBelowList
      || !cwdConfirmation.noHorizontalOverflow
      || !['auto', 'scroll'].includes(cwdConfirmation.listOverflowY)) {
      throw new Error(`Working-directory confirmation did not open: ${JSON.stringify(cwdConfirmation)}`);
    }
    const searchState = await evaluate(`(() => {
      const input=document.getElementById('directorySearch'),rows=[...document.querySelectorAll('#modalChoices .directory-row-folder')],label=rows[0]?.querySelector('strong')?.textContent||'',query=label.slice(0,Math.min(3,label.length));input.value=query;input.dispatchEvent(new Event('input',{bubbles:true}));const filtered=[...document.querySelectorAll('#modalChoices .directory-row-folder')],parentVisible=Boolean(document.querySelector('#modalChoices .directory-row-parent'));const ok=Boolean(query&&filtered.length&&filtered.length<=rows.length&&filtered.every(item=>item.textContent.toLowerCase().includes(query.toLowerCase())));input.value='';input.dispatchEvent(new Event('input',{bubbles:true}));return{ok,parentVisible,queryLength:query.length,restored:document.querySelectorAll('#modalChoices .directory-row-folder').length===rows.length};})()`);
    if (!searchState.ok || !searchState.parentVisible || !searchState.restored) throw new Error(`Working-directory search failed: ${JSON.stringify(searchState)}`);
    if (directoryScreenshotPath) {
      const screenshot = await send('Page.captureScreenshot', { format: 'png', fromSurface: true });
      await writeFile(directoryScreenshotPath, Buffer.from(screenshot.data, 'base64'));
    }
    const expandedState = await evaluate(`(() => {const more=document.querySelector('#modalChoices .directory-more'),before=document.querySelectorAll('#modalChoices .directory-row-recent').length;if(!more)return{available:false,ok:true};more.click();const after=document.querySelectorAll('#modalChoices .directory-row-recent').length;return{available:true,ok:after>before,before,after};})()`);
    if (!expandedState.ok) throw new Error(`Recent folders did not expand: ${JSON.stringify(expandedState)}`);
    await evaluate("document.querySelector('#modalChoices .directory-row-parent')?.click()");
    let parentDirectory = {};
    for (let attempt = 0; attempt < 40; attempt += 1) {
      await delay(50);
      parentDirectory = await evaluate(`(() => ({
        title: document.getElementById('modalTitle')?.textContent || '',
        currentCrumb: document.querySelector('#directoryBreadcrumb .directory-crumb[aria-current="location"]')?.textContent || '',
        canSelect: [...document.querySelectorAll('#modalActions button')].some((item) => item.textContent === 'Start Codex here'),
      }))()`);
      if (parentDirectory.currentCrumb && parentDirectory.currentCrumb !== cwdConfirmation.currentCrumb) break;
    }
    if (parentDirectory.title !== 'Choose working directory' || !parentDirectory.canSelect
      || !parentDirectory.currentCrumb || parentDirectory.currentCrumb === cwdConfirmation.currentCrumb) {
      throw new Error(`Parent-directory navigation failed: ${JSON.stringify(parentDirectory)}`);
    }
  }
  await evaluate("[...document.querySelectorAll('#modalActions button')].find((item) => item.textContent === 'Cancel')?.click()");

  await evaluate("document.getElementById('historyNext').click()");
  let second = {};
  for (let attempt = 0; attempt < 100; attempt += 1) {
    await delay(150);
    second = await evaluate(`(() => {
      const history = [...document.querySelectorAll('#sessionList .session-card')];
      const signature = history.map((item) => item.dataset.agentSessionId).filter(Boolean).join('|');
      const page = document.getElementById('historyPageInput')?.value;
      const changed = Boolean(signature && signature !== window.__faryoHistoryPageOne);
      if (page === '2' && changed) window.__faryoHistoryPageTwo = signature;
      return {
        ready: page === '2' && changed,
        historyCount: history.length,
        changed,
        activeCount: document.querySelectorAll('#activeSessionList .session-card').length,
        previousEnabled: !document.getElementById('historyPrev')?.disabled,
      };
    })()`);
    if (second?.ready) break;
  }

  if (!second?.ready || second.historyCount !== 10 || !second.changed) throw new Error('Next did not render a distinct ten-item second page');
  if (second.activeCount !== first.activeCount) throw new Error('Active sessions changed while paging history');
  if (!second.previousEnabled) throw new Error('Previous remained disabled on page two');

  await evaluate(`(() => {
    const input = document.getElementById('historyPageInput');
    input.value = '3';
    document.getElementById('historyJump').requestSubmit();
  })()`);
  let third = {};
  for (let attempt = 0; attempt < 100; attempt += 1) {
    await delay(150);
    third = await evaluate(`(() => {
      const history = [...document.querySelectorAll('#sessionList .session-card')];
      const signature = history.map((item) => item.dataset.agentSessionId).filter(Boolean).join('|');
      const changed = Boolean(signature && signature !== window.__faryoHistoryPageTwo);
      return {
        ready: document.getElementById('historyPageInput')?.value === '3' && changed,
        historyCount: history.length,
        changed,
      };
    })()`);
    if (third?.ready) break;
  }

  if (!third?.ready || third.historyCount !== 10 || !third.changed) throw new Error('Direct page jump did not render a distinct ten-item third page');

  if (startCodex) {
    await evaluate("document.querySelector('#newSessionSlot .launcher-card').click()");
    let startSheet = {};
    for (let attempt = 0; attempt < 80; attempt += 1) {
      await delay(50);
      startSheet = await evaluate(`(() => ({
        title: document.getElementById('modalTitle')?.textContent || '',
        ready: document.getElementById('modal')?.classList.contains('open') && Boolean(document.querySelector('#modalChoices .choice-btn:not([disabled])')),
      }))()`);
      if (startSheet?.ready) break;
    }
    if (!startSheet.ready || !startSheet.title.startsWith('Start ')) throw new Error(`Start Codex route sheet did not open: ${JSON.stringify(startSheet)}`);
    await evaluate("document.querySelector('#modalChoices .choice-btn:not([disabled])').click()");
    let directorySheet = {};
    for (let attempt = 0; attempt < 100; attempt += 1) {
      await delay(50);
      directorySheet = await evaluate(`(() => ({
        title: document.getElementById('modalTitle')?.textContent || '',
        ready: [...document.querySelectorAll('#modalActions button')].some((item) => item.textContent === 'Start Codex here'),
      }))()`);
      if (directorySheet?.ready) break;
    }
    if (!directorySheet.ready || directorySheet.title !== 'Choose working directory') throw new Error(`Start Codex directory sheet did not open: ${JSON.stringify(directorySheet)}`);
    await evaluate("[...document.querySelectorAll('#modalActions button')].find((item) => item.textContent === 'Start Codex here').click()");
    let launched = {};
    for (let attempt = 0; attempt < 250; attempt += 1) {
      await delay(100);
      try {
        launched = await evaluate(`(() => {
          const route = location.pathname.split('/').filter(Boolean)[0] || '';
          const session = new URLSearchParams(location.search).get('session') || '';
          const uiReady = document.documentElement.dataset.faryoAppReady === '1'
            && document.documentElement.dataset.faryoCopy === 'ready'
            && typeof window.FaryoCodexCommands?.match === 'function'
            && typeof window.FaryoCopyFidelity?.create === 'function';
          return { route, session, uiReady, ready: /^(?:hp|pc|txy)$/.test(route) && /^faryo[1-9][0-9]*$/.test(session) && uiReady };
        })()`);
      } catch (_error) {
        launched = {};
      }
      if (launched?.ready) break;
    }
    if (!launched.ready) throw new Error('Start Codex did not navigate to a managed ready session');
    const cleanup = await evaluate(`(async () => {
      const csrfResponse = await fetch('/api/csrf', { cache: 'no-store' });
      const csrfData = await csrfResponse.json();
      const response = await fetch('/${launched.route}/api/session/close', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Faryo-Csrf': csrfData.csrf || '' },
        body: JSON.stringify({ session: ${JSON.stringify(launched.session)} }),
      });
      const data = await response.json();
      return { status: response.status, ok: Boolean(data.ok) };
    })()`);
    if (!cleanup?.ok || cleanup.status !== 200) throw new Error(`Started Codex session was not cleaned up: ${JSON.stringify(cleanup)}`);
    console.log('faryo-browser-start-codex=PASS directory=selected ready=yes cleanup=yes');
  }

  console.log(`faryo-browser-workbench-smoke=PASS viewport=${first.viewport.width}x${first.viewport.height} active=${first.activeCount} managed=${first.managedCount} desktop=${first.desktopCount}`);
  console.log(`faryo-browser-workbench-history=PASS page1=${first.historyCount} page2=${second.historyCount} page3=${third.historyCount} direct-jump=yes scrollable=yes`);
} finally {
  if (socket?.readyState === WebSocket.OPEN) socket.close();
  if (chrome && chrome.exitCode === null) {
    const exited = new Promise((resolve) => chrome.once('exit', resolve));
    chrome.kill('SIGTERM');
    await Promise.race([exited, delay(3000)]);
  }
  await rm(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
}
