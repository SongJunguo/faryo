const $ = id => document.getElementById(id);
const els = {
  list: $('projectList'), sync: $('syncStatus'), submit: $('submitChanges'), sheet: $('deckSheet'), stage: $('deckStage'),
  title: $('deckTitle'), meta: $('deckMeta'), goal: $('deckGoal'), goalText: $('deckGoalText'), prev: $('prevCard'), next: $('nextCard'),
  nav: document.querySelector('.deck-nav'), importBtn: $('openImport'), importSheet: $('importSheet'), importForm: $('importForm'), importStatus: $('importStatus'),
  dock: $('faryoController'), pet: $('faryoPet'), bubble: $('faryoBubble'), activity: $('faryoActivity'), faryoForm: $('faryoForm'),
  prompt: $('faryoPrompt'), send: $('faryoSend'), open: $('faryoOpen')
};
const TYPES = {
  decision: { label: 'Decision', done: ['accepted', 'done', 'seen'], actions: [['accept', 'Approve', 'primary'], ['edit', 'Edit', ''], ['pause', 'Pause', 'danger']], left: 'accept', right: 'pause' },
  action: { label: 'Action', done: ['accepted', 'done', 'seen'], actions: [['done', 'Confirm', 'primary'], ['edit', 'Edit', ''], ['to-decision', 'Escalate', 'danger']], left: 'done', right: 'to-decision' },
  watch: { label: 'Watch', done: ['accepted', 'done', 'seen'], actions: [['seen', 'Seen', 'primary'], ['edit', 'Edit', ''], ['to-decision', 'Escalate', 'danger']], left: 'seen', right: 'to-decision' }
};
const ICONS = { decision: '⚖️', action: '🛠️', watch: '👁️' };
const STATUS = { pending: 'Pending decision', ready: 'Ready', open: 'Open', paused: 'Paused', in_progress: 'In progress', review: 'Receipt review' };
const TRANSITIONS = { accept: 'owner_approved', pause: 'owner_paused', done: 'owner_approved', seen: 'owner_seen', 'to-decision': 'item_escalated' };
let state = null, deck = { projectId: '', type: 'decision', index: 0 }, dirty = false;
let faryoSession = '', faryoAgentRunning = false, faryoStream = null;
const projects = () => state?.projects || [];
const html = value => String(value || '').replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
const empty = text => Object.assign(document.createElement('div'), { className: 'empty', textContent: text });
const setSync = text => { els.sync.textContent = text; };
const ownerQueueItem = item => !item.stage || ['awaiting_owner', 'paused', 'needs_fix'].includes(item.stage);
const hasApprovedWork = () => projects().some(project => (project.items || []).some(item => item.stage === 'approved_for_workorder'));
const activeItems = (project, type) => (project.items || []).filter(item => item.type === type && ownerQueueItem(item) && !TYPES[type].done.includes(item.status || 'open'));
const deckProject = () => projects().find(project => project.id === deck.projectId) || projects()[0];
const deckItems = () => { const project = deckProject(); return project ? activeItems(project, deck.type) : []; };
function setDirty(value) { dirty = value; els.submit.disabled = !state || !dirty; els.submit.textContent = dirty ? 'Submit' : 'Submitted'; }
function render() { const items = projects(); els.list.replaceChildren(...(items.length ? items.map(projectCard) : [empty('No projects')])); }
function saveDraft() {
  setDirty(true);
  return persist();
}
function projectCard(project) {
  const counts = Object.fromEntries(Object.keys(TYPES).map(type => [type, activeItems(project, type).length]));
  const card = document.createElement('article');
  card.className = 'project-card';
  card.innerHTML = `<section class="project-face" role="button" tabindex="0" aria-label="Open project goal"><div><div class="project-title"><span class="project-name">${html(project.name || 'Untitled')}</span><span class="project-brief">${html(project.brief)}</span></div></div><div class="project-controls"><button class="bucket" type="button" aria-label="Change project bucket">${html(project.bucket || 'B')}</button><span class="chevron">›</span></div></section><section class="pile-row">${Object.keys(TYPES).map(type => pileButton(type, counts[type])).join('')}</section>`;
  const open = () => openGoal(project);
  card.querySelector('.project-face').addEventListener('click', open);
  card.querySelector('.project-face').addEventListener('keydown', event => { if (['Enter', ' '].includes(event.key)) { event.preventDefault(); open(); } });
  card.querySelector('.bucket').addEventListener('click', event => { event.stopPropagation(); cycleBucket(project); });
  card.querySelectorAll('.pile').forEach(button => button.addEventListener('click', () => openDeck(project.id, button.dataset.type)));
  return card;
}
function pileButton(type, count) {
  return `<button class="pile ${type}" type="button" data-type="${type}"><span class="pile-count"><span class="pile-icon">${ICONS[type]}</span><strong>${count}</strong></span><span class="pile-label">${TYPES[type].label}</span></button>`;
}
function cycleBucket(project) {
  const order = ['S', 'A', 'B'];
  project.bucket = order[(order.indexOf(project.bucket || 'B') + 1) % order.length];
  render();
  saveDraft();
}
function openGoal(project) {
  els.sheet.hidden = false; els.nav.hidden = true; els.goal.hidden = true; els.meta.textContent = project.bucket || ''; els.title.textContent = `${project.name} · Goal`;
  const form = document.createElement('form');
  form.className = 'goal-form';
  form.innerHTML = `<textarea name="goal" rows="5">${html(project.current_d)}</textarea><button class="goal-save" type="submit">Save Goal</button>`;
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const next = form.elements.goal.value.trim();
    if (!next) return;
    await applyProjectUpdate(project, { current_d: next }, 'Goal updated');
    closeDeck();
  });
  els.stage.replaceChildren(form);
  form.elements.goal.focus();
}
function openDeck(projectId, type) { deck = { projectId, type, index: 0 }; els.sheet.hidden = false; renderDeck(); }
function closeDeck() { els.sheet.hidden = true; }
function renderDeck() {
  const project = deckProject(), items = deckItems(), cfg = TYPES[deck.type];
  els.nav.hidden = false; els.goal.hidden = !project; els.goalText.textContent = project?.current_d || ''; els.title.textContent = project ? `${project.name} · ${cfg.label}` : cfg.label;
  if (!items.length) { els.meta.textContent = '0 / 0'; els.stage.replaceChildren(empty(`${cfg.label} deck is clear`)); els.prev.disabled = els.next.disabled = true; return; }
  deck.index = Math.max(0, Math.min(deck.index, items.length - 1));
  els.meta.textContent = `${deck.index + 1} / ${items.length}`; els.prev.disabled = deck.index === 0; els.next.disabled = deck.index >= items.length - 1;
  els.stage.replaceChildren(deckCard(project, items[deck.index]));
}
function deckCard(project, item) {
  const card = document.createElement('article');
  card.className = 'deck-card';
  card.innerHTML = `<span class="deck-kind ${item.type}">${TYPES[item.type].label}</span><h3>${html(item.title)}</h3><p class="item-body">${html(item.body)}</p>${item.recommendation ? `<p class="recommendation">${html(item.recommendation)}</p>` : ''}<div class="deck-status">${STATUS[item.status] || item.status || 'open'}</div><div class="deck-actions">${TYPES[item.type].actions.map(([action, label, cls]) => `<button class="${cls}" data-action="${action}" type="button">${label}</button>`).join('')}</div>`;
  card.querySelectorAll('[data-action]').forEach(button => button.addEventListener('click', () => applyItemAction(project, item, button.dataset.action)));
  attachSwipe(card, project, item);
  return card;
}
async function applyItemAction(project, item, action) {
  if (action === 'edit') return openItemEditor(project, item);
  const eventType = TRANSITIONS[action];
  if (!eventType) { setSync('Action needs event flow'); return; }
  setSync('Applying');
  try {
    const data = await fetchJson('/api/project-workbench/transition', {
      project_id: project.id,
      item_id: item.id,
      event_type: eventType,
      actor: 'owner',
      source: 'gateway-ui',
      summary: `${action}: ${item.title || item.id}`
    });
    state = data.workbench;
    setDirty(hasApprovedWork());
    setSync('Applied');
    render();
    const nextProject = deckProject();
    if (nextProject && activeItems(nextProject, deck.type).length) renderDeck(); else closeDeck();
  } catch (error) { setSync(error.message || 'Action failed'); }
}
function openItemEditor(project, item) {
  els.nav.hidden = true;
  const form = document.createElement('form');
  form.className = 'deck-card edit-card';
  form.innerHTML = `<span class="deck-kind ${item.type}">${TYPES[item.type].label}</span><label><span>Card Title</span><input name="title" value="${html(item.title)}"></label><label><span>Body</span><textarea name="body" rows="4">${html(item.body)}</textarea></label><label><span>Recommendation</span><textarea name="recommendation" rows="3">${html(item.recommendation)}</textarea></label><div class="deck-actions edit-actions"><button class="primary" type="submit">Save</button><button type="button" data-cancel>Cancel</button></div>`;
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const title = form.elements.title.value.trim();
    if (!title) return;
    await applyItemUpdate(project, item, {
      title,
      body: form.elements.body.value.trim(),
      recommendation: form.elements.recommendation.value.trim()
    });
  });
  form.querySelector('[data-cancel]').addEventListener('click', renderDeck);
  els.stage.replaceChildren(form);
  form.elements.title.focus();
}
async function applyProjectUpdate(project, fields, summary) {
  setSync('Applying');
  try {
    const data = await fetchJson('/api/project-workbench/transition', { project_id: project.id, event_type: 'project_updated', actor: 'owner', source: 'gateway-ui', summary, ...fields });
    state = data.workbench; setDirty(false); setSync('Applied'); render();
  } catch (error) { setSync(error.message || 'Update failed'); }
}
async function applyItemUpdate(project, item, fields) {
  setSync('Applying');
  try {
    const data = await fetchJson('/api/project-workbench/transition', { project_id: project.id, item_id: item.id, event_type: 'item_updated', actor: 'owner', source: 'gateway-ui', summary: `Edit: ${fields.title || item.title}`, item: fields });
    state = data.workbench; setDirty(false); setSync('Applied'); render(); if (!els.sheet.hidden) renderDeck();
  } catch (error) { setSync(error.message || 'Update failed'); }
}
function attachSwipe(card, project, item) {
  let startX = null, deltaX = 0;
  const reset = () => { card.classList.remove('swiping'); card.style.transform = ''; startX = null; deltaX = 0; };
  card.addEventListener('pointerdown', event => { if (event.target.closest('button, input, textarea')) return; startX = event.clientX; deltaX = 0; card.classList.add('swiping'); card.setPointerCapture(event.pointerId); });
  card.addEventListener('pointermove', event => { if (startX === null) return; deltaX = event.clientX - startX; card.style.transform = `translateX(${Math.max(-90, Math.min(90, deltaX))}px) rotate(${deltaX / 28}deg)`; });
  card.addEventListener('pointerup', () => { const action = Math.abs(deltaX) > 72 ? TYPES[item.type][deltaX > 0 ? 'left' : 'right'] : ''; reset(); if (action) applyItemAction(project, item, action); });
  card.addEventListener('pointercancel', reset);
}
async function load() {
  try {
    const data = await fetchJson('/api/project-workbench');
    state = data.workbench; setDirty(false); setSync('Loaded'); render();
  } catch (error) { setSync('Failed'); els.list.replaceChildren(empty(error.message || 'Load failed')); }
}
async function persist() {
  if (!state) return;
  setSync('Saving');
  try { const data = await fetchJson('/api/project-workbench', state); state = data.workbench; setSync(dirty ? 'Draft' : 'Saved'); render(); setDirty(dirty); }
  catch (_error) { setSync('Failed'); }
}
async function submitChanges() {
  if (!state) return;
  els.submit.disabled = true; setSync('Submitting');
  try {
    const data = await fetchJson('/api/project-workbench/submit', state);
    state = data.workbench;
    if (['applied', 'skipped'].includes(data.downlink?.status || '')) setDirty(false); else setDirty(true);
    setSync(downlinkStatusText(data.downlink)); render();
  } catch (_error) { setSync('Submit failed'); setDirty(dirty); }
}
function downlinkStatusText(downlink) {
  const status = downlink?.status || '', targets = [...new Set((downlink?.packages || []).map(item => String(item.target || '').trim().toUpperCase()).filter(Boolean))];
  if (status === 'applied') return 'Applied';
  if (status === 'skipped') return 'Saved';
  return `${status === 'failed' ? 'Failed' : 'Pending'}${targets.length ? ` ${targets.join('/')}` : ''}`;
}
async function fetchJson(url, body = null) {
  const init = body ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : { cache: 'no-store' };
  const data = await (await fetch(url, init)).json();
  if (!data.ok) throw new Error(data.error || 'Request failed');
  return data;
}
function openImport() { els.importSheet.hidden = false; els.importStatus.textContent = dirty ? 'Submit current draft before importing.' : ''; els.importForm.elements.project_root.focus(); }
function closeImport() { els.importSheet.hidden = true; }
async function importProject(event) {
  event.preventDefault();
  if (dirty) { els.importStatus.textContent = 'Submit current draft before importing.'; return; }
  const project_root = els.importForm.elements.project_root.value.trim(), owner_route = els.importForm.elements.owner_route.value;
  if (!project_root) { els.importStatus.textContent = 'Project Root is required.'; return; }
  const button = els.importForm.querySelector('button[type="submit"]');
  button.disabled = true; els.importStatus.textContent = 'Importing'; setSync('Importing');
  try { const data = await fetchJson('/api/project-workbench/import', { owner_route, project_root }); state = data.workbench; setDirty(false); setSync('Imported'); els.importForm.elements.project_root.value = ''; closeImport(); render(); }
  catch (error) { els.importStatus.textContent = error.message || 'Import failed'; setSync('Import failed'); setDirty(dirty); }
  finally { button.disabled = false; }
}
const setFaryoBusy = value => { els.send.disabled = value; els.open.disabled = value; };
function setFaryoStatus(label, activity, phase = 'resting') { els.dock.dataset.state = label; els.dock.title = label; els.activity.textContent = activity; els.pet.className = `controller-pet pet-${phase}`; }
function setFaryoExpanded(value) { els.dock.classList.toggle('is-expanded', value); els.dock.classList.toggle('is-collapsed', !value); if (value) { els.prompt.focus(); resizeFaryoPrompt(); } }
function resizeFaryoPrompt() { els.prompt.style.height = ''; els.prompt.style.height = `${Math.min(els.prompt.scrollHeight, 104)}px`; }
function closeFaryoStream() { if (faryoStream) faryoStream.close(); faryoStream = null; }
function lastActivityLine(text) { const lines = String(text || '').split('\n').map(line => line.trim()).filter(Boolean); return (lines.pop() || '').replace(/\s+/g, ' ').slice(0, 180); }
function applyFaryoStatus(data) {
  if (data?.conflict) { faryoSession = ''; faryoAgentRunning = false; closeFaryoStream(); setFaryoStatus('Conflict', 'Close extra Faryo sessions.', 'offline'); return; }
  const next = data?.running ? data.session : '';
  faryoAgentRunning = false;
  if (!next) { faryoSession = ''; closeFaryoStream(); setFaryoStatus('Idle', 'Standing by.', 'offline'); return; }
  const changed = faryoSession !== next;
  faryoSession = next; setFaryoStatus('Ready', 'Ready.', 'resting');
  if (changed || !faryoStream) startFaryoStream();
}
function startFaryoStream() {
  closeFaryoStream();
  if (!window.EventSource || !faryoSession) return;
  const source = new EventSource(`/gcp/api/events?session=${encodeURIComponent(faryoSession)}&lines=60`);
  faryoStream = source;
  source.addEventListener('capture', event => { const capture = JSON.parse(event.data || '{}'), line = lastActivityLine(capture.text); faryoAgentRunning = Boolean(capture.agentRunning); setFaryoStatus(faryoAgentRunning ? 'Working' : 'Ready', line || 'Ready.', faryoAgentRunning ? 'running' : 'resting'); });
  source.onerror = () => { if (faryoStream !== source) return; closeFaryoStream(); loadFaryoStatus().catch(() => setFaryoStatus('Offline', 'Standing by.', 'offline')); };
}
async function loadFaryoStatus() {
  try { const data = await fetchJson('/api/faryo/status'); applyFaryoStatus(data); return data; }
  catch (error) { faryoSession = ''; faryoAgentRunning = false; closeFaryoStream(); setFaryoStatus('Offline', error.message || 'Faryo unavailable.', 'offline'); return { ok: false, running: false }; }
}
async function ensureFaryoSession(prompt = '') {
  const status = await loadFaryoStatus();
  if (status?.running && faryoSession) return { session: faryoSession, redirect: `/gcp/?session=${encodeURIComponent(faryoSession)}` };
  setFaryoBusy(true); setFaryoStatus('Waking', prompt ? 'Resuming.' : 'Starting.', 'running');
  try { const data = await fetchJson('/api/faryo/start', { prompt }); faryoSession = data.session || ''; if (!faryoSession) throw new Error('Faryo session missing'); setFaryoStatus('Ready', 'Ready.', 'resting'); startFaryoStream(); return data; }
  finally { setFaryoBusy(false); }
}
async function sendToFaryoSession(text) { return fetchJson('/gcp/api/send', { session: faryoSession, text }); }
async function sendFaryoPrompt(event) {
  event.preventDefault();
  const text = els.prompt.value.trim();
  if (!text) return;
  setFaryoBusy(true);
  try {
    const status = await loadFaryoStatus();
    if (!status?.running) await ensureFaryoSession(text);
    else try { await sendToFaryoSession(text); } catch (_error) { faryoSession = ''; closeFaryoStream(); await ensureFaryoSession(text); }
    els.prompt.value = ''; resizeFaryoPrompt(); setFaryoExpanded(false); faryoAgentRunning = true; setFaryoStatus('Working', 'Sent.', 'running');
  } catch (error) { setFaryoStatus('Failed', error.message || 'Send failed.', 'offline'); }
  finally { setFaryoBusy(false); }
}
async function openFaryoSession() { try { const data = await ensureFaryoSession(); location.href = data.redirect || `/gcp/?session=${encodeURIComponent(faryoSession)}`; } catch (error) { setFaryoStatus('Failed', error.message || 'Open failed.', 'offline'); } }
async function tapFaryoPet() {
  if (!faryoSession || !faryoAgentRunning) return;
  setFaryoStatus('Stopping', 'Stopping.', 'working');
  try { await fetchJson('/gcp/api/interrupt', { session: faryoSession }); faryoAgentRunning = false; setFaryoStatus('Ready', 'Ready.', 'resting'); }
  catch (error) { setFaryoStatus('Failed', error.message || 'Faryo action failed.', 'offline'); }
}
els.prev.addEventListener('click', () => { deck.index -= 1; renderDeck(); });
els.next.addEventListener('click', () => { deck.index += 1; renderDeck(); });
$('deckClose').addEventListener('click', closeDeck);
els.sheet.addEventListener('click', event => { if (event.target.matches('[data-close]')) closeDeck(); });
els.submit.addEventListener('click', submitChanges);
els.importBtn.addEventListener('click', openImport);
els.importForm.addEventListener('submit', importProject);
els.importSheet.addEventListener('click', event => { if (event.target.matches('[data-import-close]')) closeImport(); });
els.faryoForm.addEventListener('submit', sendFaryoPrompt);
els.open.addEventListener('click', openFaryoSession);
els.bubble.addEventListener('click', () => setFaryoExpanded(!els.dock.classList.contains('is-expanded')));
els.pet.addEventListener('click', tapFaryoPet);
els.prompt.addEventListener('input', resizeFaryoPrompt);
els.prompt.addEventListener('keydown', event => { if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) { event.preventDefault(); els.faryoForm.requestSubmit(); } });
document.addEventListener('visibilitychange', () => { if (document.hidden) closeFaryoStream(); else loadFaryoStatus().catch(() => {}); });
load();
loadFaryoStatus();
