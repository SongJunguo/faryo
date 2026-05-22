const listEl = document.getElementById('projectList');
const syncEl = document.getElementById('syncStatus');
const submitBtn = document.getElementById('submitChanges');
const sheet = document.getElementById('deckSheet');
const stageEl = document.getElementById('deckStage');
const titleEl = document.getElementById('deckTitle');
const metaEl = document.getElementById('deckMeta');
const deckGoal = document.getElementById('deckGoal');
const deckGoalText = document.getElementById('deckGoalText');
const prevBtn = document.getElementById('prevCard');
const nextBtn = document.getElementById('nextCard');
const deckNav = document.querySelector('.deck-nav');
const openImportBtn = document.getElementById('openImport');
const importSheet = document.getElementById('importSheet');
const importForm = document.getElementById('importForm');
const importStatus = document.getElementById('importStatus');
const faryoController = document.getElementById('faryoController');
const faryoPet = document.getElementById('faryoPet');
const faryoBubble = document.getElementById('faryoBubble');
const faryoActivity = document.getElementById('faryoActivity');
const faryoForm = document.getElementById('faryoForm');
const faryoPrompt = document.getElementById('faryoPrompt');
const faryoSend = document.getElementById('faryoSend');
const faryoOpen = document.getElementById('faryoOpen');

const TYPES = {
  decision: { label: 'Decision', done: ['accepted', 'paused'] },
  action: { label: 'Action', done: ['done', 'skipped'] },
  watch: { label: 'Watch', done: ['seen'] },
};

let state = null;
let deck = { projectId: '', type: 'decision', index: 0 };
let dirty = false;
let faryoSession = '';
let faryoAgentRunning = false;
let faryoStream = null;
const downlinkProjectIds = new Set();

function projects() { return state?.projects || []; }
function setSync(text) { syncEl.textContent = text; }
function setDirty(value) { dirty = value; updateSubmit(); }
function updateSubmit() { submitBtn.disabled = !state || !dirty; submitBtn.textContent = dirty ? 'Submit' : 'Submitted'; }
function saveDraft(project = null, downlink = true) {
  if (downlink && project?.id) downlinkProjectIds.add(project.id);
  setDirty(true);
  return persist();
}

function activeItems(project, type) {
  const done = TYPES[type].done;
  return (project.items || []).filter(item => item.type === type && !done.includes(item.status || 'open'));
}

function itemCounts(project) {
  return Object.fromEntries(Object.keys(TYPES).map(type => [type, activeItems(project, type).length]));
}

function render() {
  const items = projects();
  if (!items.length) { listEl.replaceChildren(empty('No projects')); return; }
  listEl.replaceChildren(...items.map(projectCard));
}

function projectCard(project) {
  const counts = itemCounts(project);
  const card = document.createElement('article');
  card.className = 'project-card';
  card.innerHTML = `
    <section class="project-face" role="button" tabindex="0" aria-label="Open project goal">
      <div>
        <div class="project-title">
          <span class="project-name">${escapeHtml(project.name || 'Untitled')}</span>
          <span class="project-brief">${escapeHtml(project.brief || '')}</span>
        </div>
      </div>
      <div class="project-controls">
        <button class="bucket" type="button" aria-label="Change project bucket">${escapeHtml(project.bucket || 'B')}</button>
        <span class="chevron">›</span>
      </div>
    </section>
    <section class="pile-row">
      ${pileButton('decision', counts.decision)}
      ${pileButton('action', counts.action)}
      ${pileButton('watch', counts.watch)}
    </section>
  `;
  const face = card.querySelector('.project-face');
  face.addEventListener('click', () => openGoal(project));
  face.addEventListener('keydown', event => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      openGoal(project);
    }
  });
  card.querySelector('.bucket').addEventListener('click', event => {
    event.stopPropagation();
    cycleBucket(project);
  });
  card.querySelectorAll('.pile').forEach(button => button.addEventListener('click', () => openDeck(project.id, button.dataset.type)));
  return card;
}

function cycleBucket(project) {
  const order = ['S', 'A', 'B'];
  const current = order.indexOf(project.bucket || 'B');
  project.bucket = order[(current + 1) % order.length];
  render();
  saveDraft(null, false);
}

function pileButton(type, count) {
  const cfg = TYPES[type];
  const icons = { decision: '⚖️', action: '🛠️', watch: '👁️' };
  return `<button class="pile ${type}" type="button" data-type="${type}"><span class="pile-count"><span class="pile-icon">${icons[type]}</span><strong>${count}</strong></span><span class="pile-label">${cfg.label}</span></button>`;
}

function openGoal(project) {
  sheet.hidden = false;
  deckNav.hidden = true;
  deckGoal.hidden = true;
  metaEl.textContent = project.bucket || '';
  titleEl.textContent = `${project.name} · Goal`;
  const form = document.createElement('form');
  form.className = 'goal-form';
  form.innerHTML = `<textarea name="goal" rows="5">${escapeHtml(project.current_d || '')}</textarea><button class="goal-save" type="submit">Save Goal</button>`;
  form.addEventListener('submit', event => {
    event.preventDefault();
    const next = form.elements.goal.value.trim();
    if (!next) return;
    project.current_d = next;
    closeDeck();
    render();
    saveDraft(project);
  });
  stageEl.replaceChildren(form);
  form.elements.goal.focus();
}

function openDeck(projectId, type) {
  deck = { projectId, type, index: 0 };
  sheet.hidden = false;
  renderDeck();
}

function closeDeck() { sheet.hidden = true; }

function setDeckGoal(project, visible = true) {
  deckGoal.hidden = !visible;
  deckGoalText.textContent = visible ? (project.current_d || '') : '';
}

function deckProject() { return projects().find(project => project.id === deck.projectId) || projects()[0]; }

function deckItems() {
  const project = deckProject();
  return project ? activeItems(project, deck.type) : [];
}

function renderDeck() {
  const project = deckProject();
  const items = deckItems();
  const cfg = TYPES[deck.type];
  deckNav.hidden = false;
  if (project) setDeckGoal(project);
  titleEl.textContent = project ? `${project.name} · ${cfg.label}` : cfg.label;
  if (!items.length) {
    metaEl.textContent = '0 / 0';
    stageEl.replaceChildren(empty(`${cfg.label} deck is clear`));
    prevBtn.disabled = true; nextBtn.disabled = true;
    return;
  }
  deck.index = Math.max(0, Math.min(deck.index, items.length - 1));
  metaEl.textContent = `${deck.index + 1} / ${items.length}`;
  stageEl.replaceChildren(deckCard(project, items[deck.index]));
  prevBtn.disabled = deck.index === 0;
  nextBtn.disabled = deck.index >= items.length - 1;
}

function deckCard(project, item) {
  const card = document.createElement('article');
  card.className = 'deck-card';
  card.innerHTML = `
    <span class="deck-kind ${item.type}">${TYPES[item.type].label}</span>
    <h3>${escapeHtml(item.title || '')}</h3>
    <p class="item-body">${escapeHtml(item.body || '')}</p>
    ${item.recommendation ? `<p class="recommendation">${escapeHtml(item.recommendation)}</p>` : ''}
    <div class="deck-status">${statusText(item)}</div>
    <div class="deck-actions">${actionButtons(item.type)}</div>
  `;
  card.querySelectorAll('[data-action]').forEach(button => {
    button.addEventListener('click', () => applyItemAction(project, item, button.dataset.action));
  });
  attachSwipe(card, project, item);
  return card;
}

function actionButtons(type) {
  if (type === 'decision') {
    return '<button class="primary" data-action="accept" type="button">Approve</button><button data-action="edit" type="button">Edit</button><button class="danger" data-action="pause" type="button">Pause</button>';
  }
  if (type === 'action') {
    return '<button class="primary" data-action="done" type="button">Confirm</button><button data-action="edit" type="button">Edit</button><button class="danger" data-action="to-decision" type="button">Escalate</button>';
  }
  return '<button class="primary" data-action="seen" type="button">Seen</button><button data-action="edit" type="button">Edit</button><button class="danger" data-action="to-decision" type="button">Escalate</button>';
}

function applyItemAction(project, item, action) {
  if (action === 'edit') {
    openItemEditor(project, item);
    return;
  } else if (action === 'accept') {
    item.status = 'accepted';
  } else if (action === 'pause') {
    item.status = 'paused';
  } else if (action === 'done') {
    item.status = 'done';
  } else if (action === 'seen') {
    item.status = 'seen';
  } else if (action === 'to-decision') {
    item.type = 'decision';
    item.status = 'pending';
  }
  render();
  if (activeItems(project, deck.type).length) {
    renderDeck();
    saveDraft(project).then(() => { if (!sheet.hidden) renderDeck(); });
  } else {
    closeDeck();
    saveDraft(project);
  }
}

function openItemEditor(project, item) {
  deckNav.hidden = true;
  const form = document.createElement('form');
  form.className = 'deck-card edit-card';
  form.innerHTML = `
    <span class="deck-kind ${item.type}">${TYPES[item.type].label}</span>
    <label><span>Card Title</span><input name="title" value="${escapeHtml(item.title || '')}"></label>
    <label><span>Body</span><textarea name="body" rows="4">${escapeHtml(item.body || '')}</textarea></label>
    <label><span>Recommendation</span><textarea name="recommendation" rows="3">${escapeHtml(item.recommendation || '')}</textarea></label>
    <div class="deck-actions edit-actions">
      <button class="primary" type="submit">Save</button>
      <button type="button" data-cancel>Cancel</button>
    </div>
  `;
  form.addEventListener('submit', event => {
    event.preventDefault();
    const title = form.elements.title.value.trim();
    if (!title) return;
    item.title = title;
    item.body = form.elements.body.value.trim();
    item.recommendation = form.elements.recommendation.value.trim();
    render();
    renderDeck();
    saveDraft(project).then(() => { if (!sheet.hidden) renderDeck(); });
  });
  form.querySelector('[data-cancel]').addEventListener('click', renderDeck);
  stageEl.replaceChildren(form);
  form.elements.title.focus();
}

function attachSwipe(card, project, item) {
  let startX = null;
  let deltaX = 0;
  card.addEventListener('pointerdown', event => {
    if (event.target.closest('button, input, textarea')) return;
    startX = event.clientX; deltaX = 0; card.classList.add('swiping'); card.setPointerCapture(event.pointerId);
  });
  card.addEventListener('pointermove', event => {
    if (startX === null) return;
    deltaX = event.clientX - startX;
    card.style.transform = `translateX(${Math.max(-90, Math.min(90, deltaX))}px) rotate(${deltaX / 28}deg)`;
  });
  card.addEventListener('pointerup', () => {
    card.classList.remove('swiping');
    card.style.transform = '';
    if (Math.abs(deltaX) > 72) applyItemAction(project, item, deltaX > 0 ? rightAction(item.type) : leftAction(item.type));
    startX = null; deltaX = 0;
  });
  card.addEventListener('pointercancel', () => {
    card.classList.remove('swiping');
    card.style.transform = '';
    startX = null; deltaX = 0;
  });
}

function leftAction(type) {
  if (type === 'decision') return 'accept';
  if (type === 'action') return 'done';
  return 'seen';
}

function rightAction(type) {
  if (type === 'decision') return 'pause';
  if (type === 'action') return 'to-decision';
  return 'to-decision';
}

function statusText(item) {
  const map = { pending: 'Pending decision', ready: 'Ready', open: 'Open', accepted: 'Approved', paused: 'Paused', done: 'Confirmed', seen: 'Seen' };
  return map[item.status] || item.status || 'open';
}

async function load() {
  try {
    const response = await fetch('/api/project-workbench', { cache: 'no-store' });
    const data = await response.json();
    if (!data.ok) throw new Error(data.error || 'Load failed');
    state = data.workbench;
    setDirty(false);
    setSync('Loaded');
    render();
  } catch (error) {
    setSync('Failed');
    listEl.replaceChildren(empty(error.message || 'Load failed'));
  }
}

async function persist() {
  if (!state) return;
  setSync('Saving');
  try {
    const response = await fetch('/api/project-workbench', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(state),
    });
    const data = await response.json();
    if (!data.ok) throw new Error(data.error || 'Save failed');
    state = data.workbench;
    setSync(dirty ? 'Draft' : 'Saved');
    render();
    updateSubmit();
  } catch (error) {
    setSync('Failed');
  }
}

async function submitChanges() {
  if (!state) return;
  submitBtn.disabled = true;
  setSync('Submitting');
  try {
    const response = await fetch('/api/project-workbench/submit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...state, downlink_project_ids: [...downlinkProjectIds] }),
    });
    const data = await response.json();
    if (!data.ok) throw new Error(data.error || 'Submit failed');
    state = data.workbench;
    const status = data.downlink?.status || '';
    if (status === 'applied' || status === 'skipped') {
      downlinkProjectIds.clear();
      setDirty(false);
    } else {
      setDirty(true);
    }
    setSync(downlinkStatusText(data.downlink));
    render();
  } catch (error) {
    setSync('Submit failed');
    updateSubmit();
  }
}

function downlinkStatusText(downlink) {
  const status = downlink?.status || '';
  if (status === 'applied') return 'Applied';
  if (status === 'skipped') return 'Saved';
  const targets = [...new Set((downlink?.packages || []).map(item => String(item.target || '').trim().toUpperCase()).filter(Boolean))];
  const suffix = targets.length ? ` ${targets.join('/')}` : '';
  if (status === 'failed') return `Failed${suffix}`;
  return `Pending${suffix}`;
}

function openImport() {
  importSheet.hidden = false;
  importStatus.textContent = dirty ? 'Submit current draft before importing.' : '';
  importForm.elements.project_root.focus();
}

function closeImport() {
  importSheet.hidden = true;
}

async function importProject(event) {
  event.preventDefault();
  if (dirty) {
    importStatus.textContent = 'Submit current draft before importing.';
    return;
  }
  const ownerRoute = importForm.elements.owner_route.value;
  const projectRoot = importForm.elements.project_root.value.trim();
  if (!projectRoot) {
    importStatus.textContent = 'Project Root is required.';
    return;
  }
  const button = importForm.querySelector('button[type="submit"]');
  button.disabled = true;
  importStatus.textContent = 'Importing';
  setSync('Importing');
  try {
    const response = await fetch('/api/project-workbench/import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ owner_route: ownerRoute, project_root: projectRoot }),
    });
    const data = await response.json();
    if (!data.ok) throw new Error(data.error || 'Import failed');
    state = data.workbench;
    setDirty(false);
    setSync('Imported');
    importForm.elements.project_root.value = '';
    closeImport();
    render();
  } catch (error) {
    importStatus.textContent = error.message || 'Import failed';
    setSync('Import failed');
    updateSubmit();
  } finally {
    button.disabled = false;
  }
}

function empty(text) {
  const div = document.createElement('div');
  div.className = 'empty';
  div.textContent = text;
  return div;
}

function setFaryoPhase(phase) {
  faryoPet.className = `controller-pet pet-${phase}`;
}

function setFaryoBusy(value) {
  faryoSend.disabled = value;
  faryoOpen.disabled = value;
}

function setFaryoStatus(label, activity, phase = 'resting') {
  faryoController.dataset.state = label;
  faryoController.title = label;
  faryoActivity.textContent = activity;
  setFaryoPhase(phase);
}

function setFaryoExpanded(value) {
  faryoController.classList.toggle('is-expanded', value);
  faryoController.classList.toggle('is-collapsed', !value);
  if (value) {
    faryoPrompt.focus();
    resizeFaryoPrompt();
  }
}

function toggleFaryoExpanded() {
  setFaryoExpanded(!faryoController.classList.contains('is-expanded'));
}

function resizeFaryoPrompt() {
  faryoPrompt.style.height = '';
  faryoPrompt.style.height = `${Math.min(faryoPrompt.scrollHeight, 104)}px`;
}

function lastActivityLine(text) {
  const lines = String(text || '').split('\n').map(line => line.trim()).filter(Boolean);
  return (lines.pop() || '').replace(/\s+/g, ' ').slice(0, 180);
}

function closeFaryoStream() {
  if (faryoStream) faryoStream.close();
  faryoStream = null;
}

function applyFaryoStatus(data) {
  if (data?.conflict) {
    faryoSession = '';
    faryoAgentRunning = false;
    closeFaryoStream();
    setFaryoStatus('Conflict', 'Close extra Faryo sessions.', 'offline');
    return;
  }
  const nextSession = data?.running ? data.session : '';
  faryoAgentRunning = false;
  if (!nextSession) {
    faryoSession = '';
    closeFaryoStream();
    setFaryoStatus('Idle', 'Standing by.', 'offline');
    return;
  }
  const changed = faryoSession !== nextSession;
  if (!changed && faryoStream) return;
  faryoSession = nextSession;
  setFaryoStatus('Ready', 'Ready.', 'resting');
  if (changed || !faryoStream) startFaryoStream();
}

function startFaryoStream() {
  closeFaryoStream();
  if (!window.EventSource || !faryoSession) return;
  const source = new EventSource(`/gcp/api/events?session=${encodeURIComponent(faryoSession)}&lines=60`);
  faryoStream = source;
  source.addEventListener('capture', event => {
    const capture = JSON.parse(event.data || '{}');
    faryoAgentRunning = Boolean(capture.agentRunning);
    const line = lastActivityLine(capture.text);
    setFaryoStatus(faryoAgentRunning ? 'Working' : 'Ready', line || 'Ready.', faryoAgentRunning ? 'running' : 'resting');
  });
  source.onerror = () => {
    if (faryoStream !== source) return;
    closeFaryoStream();
    loadFaryoStatus().catch(() => setFaryoStatus('Offline', 'Standing by.', 'offline'));
  };
}

async function loadFaryoStatus() {
  try {
    const response = await fetch('/api/faryo/status', { cache: 'no-store' });
    const data = await response.json();
    if (!data.ok) throw new Error(data.error || 'Faryo status failed');
    applyFaryoStatus(data);
    return data;
  } catch (error) {
    faryoSession = '';
    faryoAgentRunning = false;
    closeFaryoStream();
    setFaryoStatus('Offline', error.message || 'Faryo unavailable.', 'offline');
    return { ok: false, running: false };
  }
}

async function ensureFaryoSession(prompt = '') {
  const status = await loadFaryoStatus();
  if (status?.running && faryoSession) return { session: faryoSession, redirect: `/gcp/?session=${encodeURIComponent(faryoSession)}` };
  setFaryoBusy(true);
  setFaryoStatus('Waking', prompt ? 'Resuming.' : 'Starting.', 'running');
  try {
    const response = await fetch('/api/faryo/start', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ prompt }) });
    const data = await response.json();
    if (!data.ok) throw new Error(data.error || 'Failed to wake Faryo');
    faryoSession = data.session || '';
    if (!faryoSession) throw new Error('Faryo session missing');
    setFaryoStatus('Ready', 'Ready.', 'resting');
    startFaryoStream();
    return data;
  } finally {
    setFaryoBusy(false);
  }
}

async function sendToFaryoSession(text) {
  const response = await fetch('/gcp/api/send', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session: faryoSession, text }),
  });
  const data = await response.json();
  if (!data.ok) throw new Error(data.error || 'Send failed');
  return data;
}

async function sendFaryoPrompt(event) {
  event.preventDefault();
  const text = faryoPrompt.value.trim();
  if (!text) return;
  setFaryoBusy(true);
  try {
    const status = await loadFaryoStatus();
    if (!status?.running) {
      await ensureFaryoSession(text);
    } else {
      try {
        await sendToFaryoSession(text);
      } catch (_error) {
        faryoSession = '';
        closeFaryoStream();
        await ensureFaryoSession(text);
      }
    }
    faryoPrompt.value = '';
    resizeFaryoPrompt();
    setFaryoExpanded(false);
    faryoAgentRunning = true;
    setFaryoStatus('Working', 'Sent.', 'running');
  } catch (error) {
    setFaryoStatus('Failed', error.message || 'Send failed.', 'offline');
  } finally {
    setFaryoBusy(false);
  }
}

async function openFaryoSession() {
  try {
    const data = await ensureFaryoSession();
    location.href = data.redirect || `/gcp/?session=${encodeURIComponent(faryoSession)}`;
  } catch (error) {
    setFaryoStatus('Failed', error.message || 'Open failed.', 'offline');
  }
}

async function tapFaryoPet() {
  try {
    if (!faryoSession || !faryoAgentRunning) {
      return;
    }
    setFaryoStatus('Stopping', 'Stopping.', 'working');
    const response = await fetch('/gcp/api/interrupt', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session: faryoSession }),
    });
    const data = await response.json();
    if (!data.ok) throw new Error(data.error || 'Interrupt failed');
    faryoAgentRunning = false;
    setFaryoStatus('Ready', 'Ready.', 'resting');
  } catch (error) {
    setFaryoStatus('Failed', error.message || 'Faryo action failed.', 'offline');
  }
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
}

prevBtn.addEventListener('click', () => { deck.index -= 1; renderDeck(); });
nextBtn.addEventListener('click', () => { deck.index += 1; renderDeck(); });
document.getElementById('deckClose').addEventListener('click', closeDeck);
sheet.addEventListener('click', event => { if (event.target.matches('[data-close]')) closeDeck(); });
submitBtn.addEventListener('click', submitChanges);
openImportBtn.addEventListener('click', openImport);
importForm.addEventListener('submit', importProject);
importSheet.addEventListener('click', event => { if (event.target.matches('[data-import-close]')) closeImport(); });
faryoForm.addEventListener('submit', sendFaryoPrompt);
faryoOpen.addEventListener('click', openFaryoSession);
faryoBubble.addEventListener('click', toggleFaryoExpanded);
faryoPet.addEventListener('click', tapFaryoPet);
faryoPrompt.addEventListener('input', resizeFaryoPrompt);
faryoPrompt.addEventListener('keydown', event => {
  if (event.key !== 'Enter' || !(event.ctrlKey || event.metaKey)) return;
  event.preventDefault();
  faryoForm.requestSubmit();
});
document.addEventListener('visibilitychange', () => {
  if (document.hidden) closeFaryoStream();
  else loadFaryoStatus().catch(() => {});
});

load();
loadFaryoStatus();
