import { spawn } from 'node:child_process';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';

const targetUrl = process.env.FARYO_IMMERSIVE_URL;
const chromeBin = process.env.CHROME_BIN || '/usr/bin/google-chrome';
const viewportWidth = Number(process.env.FARYO_IMMERSIVE_WIDTH || 390);
const viewportHeight = Number(process.env.FARYO_IMMERSIVE_HEIGHT || 844);
const screenshotPath = process.env.FARYO_IMMERSIVE_SCREENSHOT || '';
const authCookie = process.env.FARYO_IMMERSIVE_AUTH_COOKIE || '';
const expectDocumentScroll = process.env.FARYO_IMMERSIVE_EXPECT_DOCUMENT_SCROLL === '1';
if (!targetUrl) throw new Error('FARYO_IMMERSIVE_URL is required');

const delay = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));
const profile = await mkdtemp(path.join(os.tmpdir(), 'faryo-immersive-browser-'));
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
    '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1',
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
    socket.addEventListener('open', () => { clearTimeout(timer); resolve(); }, { once: true });
    socket.addEventListener('error', () => { clearTimeout(timer); reject(new Error('Chrome target connection failed')); }, { once: true });
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
    if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
    return result.result?.value;
  };
  const trustedClick = async (selector) => {
    await send('Page.bringToFront');
    await delay(30);
    const point = await evaluate(`(() => {const item=document.querySelector(${JSON.stringify(selector)}),rect=item?.getBoundingClientRect();if(!rect||!rect.width||!rect.height)return null;const x=rect.left+rect.width/2,y=rect.top+rect.height/2,hit=document.elementFromPoint(x,y),header=item.closest('header'),app=document.querySelector('.app'),main=document.querySelector('main'),output=document.getElementById('output');return{x,y,hit:hit?.id||hit?.closest?.('[id]')?.id||'',targeted:Boolean(hit&&(hit===item||item.contains(hit))),scrollY:window.scrollY,headerPosition:header?getComputedStyle(header).position:'',headerTop:header?.getBoundingClientRect().top,appHeight:app?.getBoundingClientRect().height,mainHeight:main?.getBoundingClientRect().height,outputHeight:output?.getBoundingClientRect().height};})()`);
    if (!point) throw new Error(`Control is not visible: ${selector}`);
    if (!point.targeted) throw new Error(`Control is covered: ${selector} ${JSON.stringify(point)}`);
    await send('Input.dispatchMouseEvent', { type: 'mousePressed', x: point.x, y: point.y, button: 'left', clickCount: 1 });
    await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: point.x, y: point.y, button: 'left', clickCount: 1 });
  };

  await send('Page.enable');
  await send('Runtime.enable');
  await send('Network.enable');
  if (authCookie) await send('Network.setExtraHTTPHeaders', { headers: { Cookie: authCookie } });
  await send('Emulation.setDeviceMetricsOverride', {
    width: viewportWidth,
    height: viewportHeight,
    deviceScaleFactor: 1,
    mobile: viewportWidth < 720,
  });
  await send('Page.navigate', { url: targetUrl });

  let baseline = {};
  for (let attempt = 0; attempt < 120; attempt += 1) {
    await delay(100);
    baseline = await evaluate(`(() => ({
      ready: document.documentElement.dataset.faryoAppReady === '1' && document.documentElement.dataset.faryoImmersive === 'ready',
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
    }))()`);
    if (baseline.ready && (!expectDocumentScroll || baseline.documentScrollable)) break;
  }
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
    await evaluate("window.scrollTo({top:0,behavior:'auto'})");
    await delay(60);
    if (viewportWidth < 720) {
      await send('Emulation.setTouchEmulationEnabled', { enabled: true, maxTouchPoints: 1 });
      const x = viewportWidth / 2;
      const point = (y) => [{ x, y, radiusX: 2, radiusY: 2, force: 1, id: 1 }];
      await send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: point(viewportHeight * 0.76) });
      for (const ratio of [0.66, 0.56, 0.46, 0.36]) {
        await send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: point(viewportHeight * ratio) });
        await delay(18);
      }
      await send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
    } else {
      await send('Input.dispatchMouseEvent', { type: 'mouseWheel', x: viewportWidth / 2, y: viewportHeight / 2, deltaY: 360, deltaX: 0 });
    }
    let rootScroll = {};
    for (let attempt = 0; attempt < 60; attempt += 1) {
      await delay(50);
      rootScroll = await evaluate(`(() => {const footer=document.querySelector('footer')?.getBoundingClientRect();return{
        y:window.scrollY,
        innerMain:document.getElementById('outputWrap')?.scrollTop||0,
        footerVisible:Boolean(footer&&footer.bottom<=innerHeight+1&&footer.top>=0),
        markerCount:document.querySelectorAll('#questionNavMarkers .question-nav-marker').length,
        railRevealed:document.getElementById('questionNavigator')?.classList.contains('is-scrolling')||false,
      };})()`);
      if (rootScroll.y > 40) break;
    }
    if (rootScroll.y <= 40 || rootScroll.innerMain !== 0 || !rootScroll.footerVisible) {
      throw new Error(`Trusted document scroll failed: ${JSON.stringify(rootScroll)}`);
    }
    if (rootScroll.markerCount >= 2 && !rootScroll.railRevealed) {
      throw new Error(`Document scroll did not reach question navigation: ${JSON.stringify(rootScroll)}`);
    }
    const promptBefore = await evaluate(`(() => {const rect=document.querySelector('.prompt-shell')?.getBoundingClientRect();return rect?{width:rect.width,height:rect.height,visible:rect.top>=0&&rect.bottom<=innerHeight+1}:null;})()`);
    await trustedClick('#promptInput');
    await delay(80);
    const promptFocused = await evaluate(`(() => {const rect=document.querySelector('.prompt-shell')?.getBoundingClientRect();return rect?{width:rect.width,height:rect.height,visible:rect.top>=0&&rect.bottom<=innerHeight+1}:null;})()`);
    await evaluate("document.getElementById('promptInput')?.blur()");
    await delay(140);
    const promptBlurred = await evaluate(`(() => {const rect=document.querySelector('.prompt-shell')?.getBoundingClientRect();return rect?{width:rect.width,height:rect.height,visible:rect.top>=0&&rect.bottom<=innerHeight+1}:null;})()`);
    if (!promptBefore?.visible || !promptFocused?.visible || !promptBlurred?.visible
      || Math.abs(promptBefore.width - promptFocused.width) > 1 || Math.abs(promptBefore.height - promptFocused.height) > 1
      || Math.abs(promptBefore.width - promptBlurred.width) > 1 || Math.abs(promptBefore.height - promptBlurred.height) > 1) {
      throw new Error(`Document-scroll composer geometry changed: ${JSON.stringify({ promptBefore, promptFocused, promptBlurred })}`);
    }
  };

  if (!baseline.supported) {
    await trustedClick('#immersiveBtn');
    await delay(100);
    const fallback = await evaluate("document.getElementById('errorBox')?.textContent.includes('Install Faryo from Home') || false");
    if (!fallback) throw new Error('Unsupported Fullscreen API did not show the PWA fallback');
    await verifyDocumentScroll();
    console.log(`faryo-browser-immersive=PASS viewport=${viewportWidth}x${viewportHeight} api=unsupported fallback=pwa root-scroll=${expectDocumentScroll?'yes':'no'}`);
  } else {
    await delay(220);
    await trustedClick('#immersiveBtn');
    let entered = {};
    for (let attempt = 0; attempt < 80; attempt += 1) {
      await delay(50);
      entered = await evaluate(`(() => ({
        active: Boolean(document.fullscreenElement || document.webkitFullscreenElement),
        rootState: document.documentElement.dataset.faryoFullscreen,
        topExitVisible: Boolean(document.getElementById('immersiveBtn')?.getClientRects().length),
        floatingExitHidden: document.getElementById('immersiveExitBtn')?.hidden === false && !document.getElementById('immersiveExitBtn')?.getClientRects().length,
        toggleLabel: document.getElementById('immersiveBtn')?.getAttribute('aria-label') || '',
        toggleText: document.getElementById('immersiveBtn')?.textContent?.trim() || '',
        error: document.getElementById('errorBox')?.textContent || '',
        horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
      }))()`);
      if (entered.active) break;
    }
    if (!entered.active || entered.rootState !== 'active' || !entered.topExitVisible || !entered.floatingExitHidden
      || entered.toggleLabel !== 'Exit full screen' || entered.toggleText !== 'Exit' || entered.horizontalOverflow) {
      throw new Error(`Entering full screen failed: ${JSON.stringify(entered)}`);
    }
    if (screenshotPath) {
      const screenshot = await send('Page.captureScreenshot', { format: 'png', fromSurface: true });
      await writeFile(screenshotPath, Buffer.from(screenshot.data, 'base64'));
    }

    await trustedClick('#immersiveBtn');
    let exited = {};
    for (let attempt = 0; attempt < 80; attempt += 1) {
      await delay(50);
      exited = await evaluate(`(() => ({
        active: Boolean(document.fullscreenElement || document.webkitFullscreenElement),
        rootState: document.documentElement.dataset.faryoFullscreen,
        exitHidden: document.getElementById('immersiveExitBtn')?.hidden === true,
        toggleLabel: document.getElementById('immersiveBtn')?.getAttribute('aria-label') || '',
      }))()`);
      if (!exited.active) break;
    }
    if (exited.active || exited.rootState !== 'ready' || !exited.exitHidden || exited.toggleLabel !== 'Enter full screen') {
      throw new Error(`Exiting full screen failed: ${JSON.stringify(exited)}`);
    }

    await trustedClick('#detailsBtn');
    for (let attempt = 0; attempt < 40; attempt += 1) {
      await delay(25);
      if (await evaluate("!document.getElementById('detailsPanel')?.classList.contains('hidden')")) break;
    }
    await trustedClick('#detailsFullscreenBtn');
    let detailsEntered = {};
    for (let attempt = 0; attempt < 80; attempt += 1) {
      await delay(50);
      detailsEntered = await evaluate(`(() => ({
        active: Boolean(document.fullscreenElement || document.webkitFullscreenElement),
        panelClosed: document.getElementById('detailsPanel')?.classList.contains('hidden') || false,
        topExitVisible: Boolean(document.getElementById('immersiveBtn')?.getClientRects().length),
      }))()`);
      if (detailsEntered.active) break;
    }
    if (!detailsEntered.active || !detailsEntered.panelClosed || !detailsEntered.topExitVisible) {
      throw new Error(`Details full screen flow failed: ${JSON.stringify(detailsEntered)}`);
    }
    await trustedClick('#sessionTitle');
    for (let attempt = 0; attempt < 40; attempt += 1) {
      await delay(25);
      if (await evaluate("Boolean(document.getElementById('immersiveExitBtn')?.getClientRects().length)")) break;
    }
    if (!await evaluate("Boolean(document.getElementById('immersiveExitBtn')?.getClientRects().length)")) {
      throw new Error('Collapsed header did not reveal the floating full screen exit');
    }
    await trustedClick('#immersiveExitBtn');
    for (let attempt = 0; attempt < 80; attempt += 1) {
      await delay(50);
      if (!await evaluate("Boolean(document.fullscreenElement || document.webkitFullscreenElement)")) break;
    }
    if (await evaluate("Boolean(document.fullscreenElement || document.webkitFullscreenElement)")) {
      throw new Error('Details full screen flow did not exit');
    }
    await verifyDocumentScroll();
    console.log(`faryo-browser-immersive=PASS viewport=${viewportWidth}x${viewportHeight} api=fullscreen topbar=yes details=yes exit=yes root-scroll=${expectDocumentScroll?'yes':'no'}`);
  }
} finally {
  if (socket?.readyState === WebSocket.OPEN) socket.close();
  if (chrome && chrome.exitCode === null) {
    const exited = new Promise((resolve) => chrome.once('exit', resolve));
    chrome.kill('SIGTERM');
    await Promise.race([exited, delay(3000)]);
  }
  await rm(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
}
