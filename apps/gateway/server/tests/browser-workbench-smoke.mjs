import { readFile, writeFile } from 'node:fs/promises';

import { withBrowser } from '../../../../tools/browser-harness/playwright.mjs';

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
await withBrowser({
  executablePath: chromeBin,
  viewport: { width: viewportWidth, height: viewportHeight },
  mobile: viewportWidth < 720,
  hostResolverRules,
  extraHTTPHeaders: authCookie ? { Cookie: authCookie } : {},
}, async ({ context, page }) => {
  const cdp = await context.newCDPSession(page);
  const send = (method, params = {}) => cdp.send(method, params);
  const evaluate = async (expression) => {
    const result = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
    if (result.exceptionDetails) {
      throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text || 'Browser evaluation failed');
    }
    return result.result?.value;
  };

  if (authCookie) {
    const separator = authCookie.indexOf('=');
    if (separator <= 0) throw new Error('FARYO_SMOKE_AUTH_COOKIE must be name=value');
  }
  await page.goto(targetUrl, { waitUntil: 'domcontentloaded' });

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
      const lifecycleStates = [...active, ...history].map((item) => item.dataset.state || '');
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
        lifecycleStatesValid: lifecycleStates.every((value) => ['starting','running','waiting','exited','desktop','resumable','archived'].includes(value)),
        securityControlsReady: Boolean(document.getElementById('securityActivity') && document.getElementById('revokeSessions') && document.getElementById('attentionCenter') && document.getElementById('notificationControl')),
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
  if (!first.lifecycleStatesValid) throw new Error('Session cards do not expose explicit lifecycle states');
  if (!first.securityControlsReady) throw new Error('Security activity controls are not available');
  const validPalettes = new Set(['#f6f7f9:#5369e7', '#0f1115:#7188ff']);
  if (!validPalettes.has(`${first.palette.bg}:${first.palette.accent}`)) throw new Error(`Unexpected shared palette: ${JSON.stringify(first.palette)}`);
  const expectedPalette = { light: '#f6f7f9:#5369e7', dark: '#0f1115:#7188ff' }[smokeTheme];
  if (expectedPalette && `${first.palette.bg}:${first.palette.accent}` !== expectedPalette) throw new Error(`Theme palette mismatch: ${JSON.stringify(first.palette)}`);
  if (first.pageHorizontalOverflow) throw new Error(`Gateway workbench overflowed horizontally: ${JSON.stringify(first.viewport)}`);

  const keyedCardState = await evaluate(`(async () => {
    const container = document.querySelector('#activeSessionList .session-card')
      ? document.getElementById('activeSessionList')
      : document.getElementById('sessionList');
    const card = container?.querySelector('.session-card');
    if (!card) return { ready: false };
    const identity = [card.dataset.route || '', card.dataset.session || '', card.dataset.agentSessionId || ''].join('|');
    card.tabIndex = 0;
    card.dataset.preactTransient = 'preserved';
    card.focus();
    await refreshWorkbench();
    const current = [...container.querySelectorAll('.session-card')].find((item) =>
      [item.dataset.route || '', item.dataset.session || '', item.dataset.agentSessionId || ''].join('|') === identity
    );
    return {
      ready: true,
      sameNode: current === card,
      focusPreserved: document.activeElement === card,
      transientPreserved: current?.dataset.preactTransient === 'preserved',
    };
  })()`);
  if (!keyedCardState.ready || !keyedCardState.sameNode || !keyedCardState.focusPreserved || !keyedCardState.transientPreserved) {
    throw new Error(`Keyed Preact reconciliation replaced live card state: ${JSON.stringify(keyedCardState)}`);
  }

  const safeTextFixture = await evaluate(`(() => {
    const container = document.createElement('div');
    const title = '<img id="faryoInjectedCard" src=x onerror="window.__faryoInjected=true">';
    const card = window.__faryoRenderSessionFixture({
      id: 'anonymous-text-fixture', title, route: 'txy', routeLabel: 'Workstation',
      source: 'codex-cli', state: 'resumable', updatedTs: 1,
    }, container);
    return {
      title: card.querySelector('.session-title')?.textContent || '',
      injectedElement: Boolean(container.querySelector('#faryoInjectedCard')),
      executed: Boolean(window.__faryoInjected),
    };
  })()`);
  if (!safeTextFixture.title.startsWith('<img') || safeTextFixture.injectedElement || safeTextFixture.executed) {
    throw new Error(`Preact card text escaped the component boundary: ${JSON.stringify(safeTextFixture)}`);
  }

  const lifecycleFixture = await evaluate(`(() => {const states=['starting','running','waiting','exited','desktop','resumable','archived'],labels={starting:'Starting',running:'Running',waiting:'Waiting',exited:'Exited',desktop:'Desktop',resumable:'Resume',archived:'Archived'};return states.map(state=>{const active=!['resumable','archived'].includes(state),container=document.createElement('div'),card=window.__faryoRenderSessionFixture({id:'anonymous-thread',title:'Anonymous session',route:'txy',routeLabel:'Workstation',source:'codex-cli',tmuxSession:active?'anonymous-tmux':'',managed:active&&state!=='desktop',agentRunning:state==='running',archived:state==='archived',state,updatedTs:1},container);return{state:card.dataset.state,label:card.querySelector('.session-meta')?.textContent.includes(labels[state])||false,close:Boolean(card.querySelector('.close-session')),archive:Boolean(card.querySelector('.archive-session')),restore:Boolean(card.querySelector('.restore-session'))};});})()`);
  if (!Array.isArray(lifecycleFixture) || lifecycleFixture.some((item) => !item.label || item.state === 'desktop' && item.close || ['starting','running','waiting','exited'].includes(item.state) && !item.close || item.state==='resumable'&&!item.archive || item.state==='archived'&&!item.restore || !['resumable'].includes(item.state)&&item.archive || item.state!=='archived'&&item.restore)) {
    throw new Error(`Session lifecycle cards are inconsistent: ${JSON.stringify(lifecycleFixture)}`);
  }

  await evaluate(`(() => {const fixture=document.createElement('div');fixture.id='faryoArchiveFixtureCard';fixture.hidden=true;document.body.appendChild(fixture);const card=window.__faryoRenderSessionFixture({id:'anonymous-archive-thread',title:'Anonymous archive fixture',route:'txy',routeLabel:'Workstation',source:'codex-cli',state:'resumable',updatedTs:1},fixture);card.querySelector('.archive-session')?.click();})()`);
  let archiveSheet = {};
  for (let attempt = 0; attempt < 40; attempt += 1) {
    await delay(50);
    archiveSheet = await evaluate(`(() => ({open:document.getElementById('modal')?.classList.contains('open')||false,title:document.getElementById('modalTitle')?.textContent||'',reversible:document.getElementById('modalBody')?.textContent?.includes('restore it')||false,deleteAbsent:!document.getElementById('modal')?.textContent?.includes('Delete')}))()`);
    if (archiveSheet?.open) break;
  }
  if (!archiveSheet.open || archiveSheet.title !== 'Archive session' || !archiveSheet.reversible || !archiveSheet.deleteAbsent) {
    throw new Error(`Archive confirmation is unclear: ${JSON.stringify(archiveSheet)}`);
  }
  await evaluate(`(() => {[...document.querySelectorAll('#modalActions button')].find(item=>item.textContent==='Cancel')?.click();document.getElementById('faryoArchiveFixtureCard')?.remove();})()`);
  await delay(20);

  await evaluate("document.getElementById('securityActivity').click()");
  let activityPanel = {};
  for (let attempt = 0; attempt < 100; attempt += 1) {
    await delay(50);
    activityPanel = await evaluate(`(() => ({open:document.getElementById('modal')?.classList.contains('open')||false,title:document.getElementById('modalTitle')?.textContent||'',privacy:document.getElementById('modalBody')?.textContent?.includes('Message text, titles and paths are never recorded')||false,rows:document.querySelectorAll('#modalChoices .activity-row').length,noHorizontalOverflow:document.documentElement.scrollWidth<=document.documentElement.clientWidth+1}))()`);
    if (activityPanel?.open && activityPanel.title === 'Security activity') break;
  }
  if (!activityPanel.open || activityPanel.title !== 'Security activity' || !activityPanel.privacy || !activityPanel.rows || !activityPanel.noHorizontalOverflow) {
    throw new Error(`Security activity panel failed: ${JSON.stringify(activityPanel)}`);
  }
  await evaluate("[...document.querySelectorAll('#modalActions button')].find((item)=>item.textContent==='Cancel')?.click()");

  const attentionTransition = await evaluate(`(async()=>{
    const response=await fetch('/api/workbench?page=1',{cache:'no-store'}),data=await response.json(),route=data.entries?.[0]?.id||'txy',routeLabel=data.entries?.[0]?.label||'Workstation',before=Number(document.getElementById('attentionCount')?.textContent||0),original=window.Notification;
    class FakeNotification{static permission='granted';constructor(title,options){window.__faryoAttentionNotice={title,body:String(options?.body||''),tag:String(options?.tag||''),data:options?.data};}close(){}}
    Object.defineProperty(window,'Notification',{configurable:true,value:FakeNotification});localStorage.setItem('faryoAttentionNotificationsV1','1');
    const fixture={id:'anonymous-attention-thread',tmuxSession:'anonymous-attention',route,routeLabel,title:'Private fixture title',cwd:'/private/fixture',state:'running',managed:true,source:'codex-cli',updatedTs:1};
    renderWorkbench({...data,activeSessions:[...(data.activeSessions||[]),fixture]});
    renderWorkbench({...data,activeSessions:[...(data.activeSessions||[]),{...fixture,state:'waiting'}]});
    const result={before,after:Number(document.getElementById('attentionCount')?.textContent||0),summary:document.getElementById('attentionSummary')?.textContent||'',notice:window.__faryoAttentionNotice||null,active:document.getElementById('attentionCount')?.dataset.active||''};
    window.__faryoOriginalNotification=original;return result;
  })()`);
  if (attentionTransition.after !== attentionTransition.before + 1 || attentionTransition.active !== 'true'
    || !attentionTransition.summary.includes('need attention') || attentionTransition.notice?.title !== 'Faryo needs attention'
    || attentionTransition.notice?.body !== 'A session completed or needs input.' || attentionTransition.notice?.data !== undefined
    || /anonymous|private|thread|path/i.test(`${attentionTransition.notice?.body||''} ${attentionTransition.notice?.tag||''}`)) {
    throw new Error(`Attention transition failed: ${JSON.stringify(attentionTransition)}`);
  }
  await evaluate("document.getElementById('attentionCenter').click()");
  let attentionSheet = {};
  for (let attempt = 0; attempt < 80; attempt += 1) {
    await delay(50);
    attentionSheet = await evaluate(`(() => ({open:document.getElementById('modal')?.classList.contains('open')||false,title:document.getElementById('modalTitle')?.textContent||'',text:document.getElementById('modal')?.textContent||''}))()`);
    if (attentionSheet.open) break;
  }
  if (!attentionSheet.open || attentionSheet.title !== 'Attention' || /Private fixture title|anonymous-attention|\/private\/fixture/.test(attentionSheet.text)) {
    throw new Error('Attention center exposed private session metadata');
  }
  await evaluate(`(async()=>{[...document.querySelectorAll('#modalActions button')].find(item=>item.textContent==='Cancel')?.click();localStorage.removeItem('faryoAttentionNotificationsV1');if(window.__faryoOriginalNotification)Object.defineProperty(window,'Notification',{configurable:true,value:window.__faryoOriginalNotification});await refreshWorkbench();})()`);

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
});
