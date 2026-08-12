import { spawn } from 'node:child_process';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';

const targetUrl = process.env.FARYO_SMOKE_URL;
const loginUser = process.env.FARYO_SMOKE_LOGIN_USER || '';
const passwordFile = process.env.FARYO_SMOKE_LOGIN_PASSWORD_FILE || '';
const loginPassword = passwordFile ? (await readFile(passwordFile, 'utf8')).trim() : '';
const expectedActive = Number(process.env.FARYO_SMOKE_EXPECT_ACTIVE || 0);
const expectedManaged = Number(process.env.FARYO_SMOKE_EXPECT_MANAGED || -1);
const expectedDesktop = Number(process.env.FARYO_SMOKE_EXPECT_DESKTOP || -1);
const expectedRouteLabel = process.env.FARYO_SMOKE_EXPECT_ROUTE_LABEL || '';
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
    '--window-size=430,820',
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
    const result = await send('Runtime.evaluate', { expression, returnByValue: true });
    return result.result?.value;
  };

  await send('Page.enable');
  await send('Runtime.enable');
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
      window.__faryoHistoryPageOne = historySignature;
      return {
        ready: activeList && historyList && history.length === 10 && document.getElementById('historyPageLabel')?.textContent.includes('Page 1 of '),
        activeCount: active.length,
        historyCount: history.length,
        managedCount: active.filter((item) => item.querySelector('.close-session')).length,
        desktopCount: active.filter((item) => item.querySelector('.session-meta')?.textContent.includes('Desktop tmux')).length,
        sectionsSeparate: history.every((item) => !item.dataset.session) && active.every((item) => item.dataset.session),
        noDuplicates: historyIds.every((id) => !activeIds.has(id)),
        previousDisabled: Boolean(document.getElementById('historyPrev')?.disabled),
        nextEnabled: !document.getElementById('historyNext')?.disabled,
        routeLabelMatches: !${JSON.stringify(expectedRouteLabel)} || [...document.querySelectorAll('.route-chip strong')].some((item) => item.textContent.trim() === ${JSON.stringify(expectedRouteLabel)}),
        overflowY: style?.overflowY || '',
        scrollable: Boolean(historyList && historyList.scrollHeight > historyList.clientHeight),
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

  await evaluate("document.getElementById('historyNext').click()");
  let second = {};
  for (let attempt = 0; attempt < 100; attempt += 1) {
    await delay(150);
    second = await evaluate(`(() => {
      const history = [...document.querySelectorAll('#sessionList .session-card')];
      const signature = history.map((item) => item.dataset.agentSessionId).filter(Boolean).join('|');
      return {
        ready: document.getElementById('historyPageLabel')?.textContent.includes('Page 2 of '),
        historyCount: history.length,
        changed: Boolean(signature && signature !== window.__faryoHistoryPageOne),
        activeCount: document.querySelectorAll('#activeSessionList .session-card').length,
        previousEnabled: !document.getElementById('historyPrev')?.disabled,
      };
    })()`);
    if (second?.ready) break;
  }

  if (!second?.ready || second.historyCount !== 10 || !second.changed) throw new Error('Next did not render a distinct ten-item second page');
  if (second.activeCount !== first.activeCount) throw new Error('Active sessions changed while paging history');
  if (!second.previousEnabled) throw new Error('Previous remained disabled on page two');

  console.log(`faryo-browser-workbench-smoke=PASS active=${first.activeCount} managed=${first.managedCount} desktop=${first.desktopCount}`);
  console.log(`faryo-browser-workbench-history=PASS page1=${first.historyCount} page2=${second.historyCount} scrollable=yes`);
} finally {
  if (socket?.readyState === WebSocket.OPEN) socket.close();
  if (chrome && chrome.exitCode === null) {
    const exited = new Promise((resolve) => chrome.once('exit', resolve));
    chrome.kill('SIGTERM');
    await Promise.race([exited, delay(3000)]);
  }
  await rm(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
}
