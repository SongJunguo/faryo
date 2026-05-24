const APPEARANCE = {
  theme: { key: 'faryoTheme', values: ['system', 'light', 'dark'] },
  font: { key: 'faryoFont', values: ['default', 'serif', 'rounded', 'mono'] },
  size: { key: 'faryoTextSize', values: ['normal', 'large', 'small'] }
};
function appearanceValue(name) {
  const cfg = APPEARANCE[name], value = localStorage.getItem(cfg.key);
  return cfg.values.includes(value) ? value : cfg.values[0];
}
function applyAppearance() {
  const root = document.documentElement;
  for (const name of Object.keys(APPEARANCE)) {
    const cfg = APPEARANCE[name], value = appearanceValue(name);
    if (value === cfg.values[0]) root.removeAttribute(`data-${name}`);
    else root.setAttribute(`data-${name}`, value);
  }
}
applyAppearance();
window.addEventListener('storage', event => {
  if (Object.values(APPEARANCE).some(cfg => cfg.key === event.key)) applyAppearance();
});
const $ = id => document.getElementById(id);
const els = {
  list: $('projectList'), sync: $('syncStatus'), submit: $('submitChanges'), sheet: $('deckSheet'), stage: $('deckStage'),
  title: $('deckTitle'), meta: $('deckMeta'), goal: $('deckGoal'), goalText: $('deckGoalText'), prev: $('prevCard'), next: $('nextCard'),
  nav: document.querySelector('.deck-nav'), importBtn: $('openImport'), importSheet: $('importSheet'), importForm: $('importForm'), importStatus: $('importStatus'),
  menu: $('projectMenu'), menuButton: $('projectMenuButton'), menuPanel: $('projectMenuPanel'), archiveFilter: $('archiveFilter'), archiveFilterLabel: $('archiveFilterLabel'),
  dock: $('faryoController'), pet: $('faryoPet'), bubble: $('faryoBubble'), activity: $('faryoActivity'), faryoForm: $('faryoForm'),
  prompt: $('faryoPrompt'), send: $('faryoSend'), open: $('faryoOpen')
};
const TYPES = {
  decision: { label: 'Decision', done: ['accepted', 'done', 'seen'], actions: [['accept', 'Approve', 'primary'], ['edit', 'Edit', ''], ['pause', 'Pause', 'danger']], left: 'accept', right: 'pause' },
  action: { label: 'Action', done: ['accepted', 'done', 'seen'], actions: [['done', 'Confirm', 'primary'], ['edit', 'Edit', ''], ['to-decision', 'Escalate', 'danger']], left: 'done', right: 'to-decision' },
  watch: { label: 'Watch', done: ['accepted', 'done', 'seen'], actions: [['seen', 'Seen', 'primary'], ['edit', 'Edit', ''], ['to-decision', 'Escalate', 'danger']], left: 'seen', right: 'to-decision' }
};
const METRIC_LABELS = { decision: 'Decision', action: 'Action', watch: 'Watch' };
const METRIC_ICONS = { decision: '⚖️', action: '🛠️', watch: '👁️' };
const STATUS = { pending: 'Pending decision', ready: 'Ready', open: 'Open', accepted: 'Approved', paused: 'Paused', done: 'Confirmed', seen: 'Seen', in_progress: 'In progress', review: 'Receipt review' };
const TRANSITIONS = { accept: 'owner_approved', pause: 'owner_paused', done: 'owner_approved', seen: 'owner_seen', 'to-decision': 'item_escalated' };
const PROJECT_GIT_REFRESH_MS = 30000;
const PROJECT_FILTER = { key: 'faryoProjectFilter', values: ['active', 'all', 'archived'], labels: { active: 'Active', all: 'All', archived: 'Archived' } };
let state = null, deck = { projectId: '', type: 'decision', index: 0 }, dirty = false;
let faryoSession = '', faryoAgentRunning = false, faryoStream = null;
const sheetTimers = new WeakMap();
const projects = () => state?.projects || [];
const html = value => String(value || '').replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
const empty = text => Object.assign(document.createElement('div'), { className: 'empty', textContent: text });
const setLabel = (el, text) => { const label = el?.querySelector?.('.label'); if (label) label.textContent = text; else if (el) el.textContent = text; };
const setSync = text => setLabel(els.sync, text);
const tierBadge = bucket => `<span class="tier-badge tier-${html(String(bucket || 'B').toLowerCase())} sheet-tier">${html(bucket || 'B')}</span>`;
const typeBadge = type => `<span class="sheet-type-badge ${html(type)}" aria-label="${html(TYPES[type]?.label || type)}">${METRIC_ICONS[type] || '•'}</span>`;
function setDeckMeta(markup) { els.meta.innerHTML = markup; }
function resetSheetMode() { els.sheet.classList.remove('project-overview-sheet'); }
function showSheet(el) { clearTimeout(sheetTimers.get(el)); el.classList.remove('is-closing'); el.hidden = false; }
function hideSheet(el) {
  clearTimeout(sheetTimers.get(el));
  el.classList.add('is-closing');
  sheetTimers.set(el, setTimeout(() => { el.hidden = true; el.classList.remove('is-closing'); }, 150));
}
const ownerQueueItem = item => !item.stage || ['awaiting_owner', 'paused', 'needs_fix'].includes(item.stage);
const hasApprovedWork = () => projects().some(project => !project.archived && (project.items || []).some(item => item.stage === 'approved_for_workorder'));
const activeItems = (project, type) => (project.items || []).filter(item => item.type === type && ownerQueueItem(item) && !TYPES[type].done.includes(item.status || 'open'));
const deckProject = () => projects().find(project => project.id === deck.projectId) || projects()[0];
const deckItems = () => { const project = deckProject(); return project ? activeItems(project, deck.type) : []; };
function projectFilter() {
  const value = localStorage.getItem(PROJECT_FILTER.key);
  return PROJECT_FILTER.values.includes(value) ? value : PROJECT_FILTER.values[0];
}
function setDirty(value) { dirty = value; els.submit.disabled = !state || !dirty; setLabel(els.submit, dirty ? 'Submit' : 'Submitted'); }
function render() {
  const mode = projectFilter(), items = projects().filter(project => mode === 'all' || Boolean(project.archived) === (mode === 'archived'));
  if (els.archiveFilterLabel) els.archiveFilterLabel.textContent = PROJECT_FILTER.labels[mode];
  els.list.replaceChildren(...(items.length ? items.map(projectCard) : [empty(mode === 'archived' ? 'No archived projects' : 'No projects')]));
}
function saveDraft() {
  setDirty(true);
  return persist();
}
function toggleArchive(project) {
  project.archived = !project.archived;
  render();
  persist().then(() => refreshProjectGitStatus().catch(() => {}));
}
function projectCard(project) {
  const counts = Object.fromEntries(Object.keys(TYPES).map(type => [type, activeItems(project, type).length]));
  const summary = project.brief || project.current_d || '';
  const git = projectGitMeta(project.gitStatus), meta = projectMeta(project);
  const card = document.createElement('article');
  const rank = stackRank(counts);
  card.className = `project-card stack-rank-${rank}${project.archived ? ' is-archived' : ''}`;
  card.innerHTML = `${cardStack(rank)}<section class="card-face" role="button" tabindex="0" aria-label="Open project goal"><div class="title-row"><h2 class="project-title">${html(project.name || 'Untitled')}</h2><button class="favorite${project.archived ? ' is-archived' : ''}" type="button" aria-label="${project.archived ? 'Unarchive' : 'Archive'} ${html(project.name || 'Untitled')}">${project.archived ? '&#9733;' : '&#9734;'}</button></div><div class="project-meta"><button class="tier-badge tier-${html((project.bucket || 'B').toLowerCase())} bucket" type="button" aria-label="Change project bucket">${html(project.bucket || 'B')}</button><span class="meta-text">${git}${meta ? html(meta) : ''}</span></div><p class="summary${summary ? '' : ' is-empty'}" role="button" tabindex="0" aria-label="Open project overview"><span class="summary-text">${html(summary)}</span></p><section class="metrics" aria-label="Project status counts">${Object.keys(TYPES).map(type => metricButton(type, counts[type])).join('')}</section></section>`;
  const open = () => openGoal(project);
  card.querySelector('.card-face').addEventListener('click', open);
  card.querySelector('.card-face').addEventListener('keydown', event => { if (['Enter', ' '].includes(event.key)) { event.preventDefault(); open(); } });
  const summaryEl = card.querySelector('.summary');
  summaryEl.addEventListener('click', event => { event.stopPropagation(); openProjectOverview(project); });
  summaryEl.addEventListener('keydown', event => { if (['Enter', ' '].includes(event.key)) { event.preventDefault(); event.stopPropagation(); openProjectOverview(project); } });
  card.querySelector('.favorite').addEventListener('click', event => { event.stopPropagation(); toggleArchive(project); });
  card.querySelector('.bucket').addEventListener('click', event => { event.stopPropagation(); cycleBucket(project); });
  card.querySelectorAll('.metric').forEach(button => button.addEventListener('click', event => { event.stopPropagation(); openDeck(project.id, button.dataset.type); }));
  return card;
}
function metricButton(type, count) {
  return `<button class="metric" type="button" data-type="${type}"><span class="metric-icon" aria-hidden="true">${METRIC_ICONS[type]}</span><span class="metric-label">${METRIC_LABELS[type]}</span><span class="metric-value">${count}</span></button>`;
}
function stackRank(counts) {
  const total = Object.values(counts).reduce((sum, count) => sum + count, 0);
  if (total <= 5) return 1;
  if (total <= 10) return 2;
  if (total <= 15) return 3;
  if (total <= 20) return 4;
  return 5;
}
function cardStack(rank) {
  const sheets = Math.max(1, Math.min(5, rank));
  return Array.from({ length: sheets }, (_, index) => `<span class="paper-sheet sheet-${index + 1}"></span>`).join('');
}
function projectMeta(project) {
  const version = project.version || project.release || '';
  const pr = project.pr ?? project.prs ?? project.pull_requests;
  const issues = project.issues ?? project.issue_count;
  const art = project.art ?? project.design;
  return [
    version ? String(version) : '',
    pr === undefined || pr === null || pr === '' ? '' : `PR ${pr}`,
    issues === undefined || issues === null || issues === '' ? '' : `Issues ${issues}`,
    art ? `Art ${art}` : ''
  ].filter(Boolean).join(' · ');
}
function projectGitMeta(git) {
  if (!git?.label) return '';
  return `<span class="project-git ${html(git.state || 'muted')}" title="${html(git.title || '')}">${html(compactGitLabel(git))}</span>`;
}
function compactGitLabel(git) {
  const clean = git.state === 'clean', icon = clean ? '🌿' : '✏️';
  const raw = String(git.label || '').replace(/^(?:🌿|✏️|✏)\s*/u, '').trim();
  if (git.state === 'error') return raw ? `⚠️ ${raw.replace(/^(?:⚠️|⚠)\s*/u, '')}` : '⚠️ git';
  const markRe = /^(?:[+-]\d+|±\d+|\?\d+|[↑↓]\d+|m[+-]\d+)$/;
  const parts = raw.split(/\s+/).filter(Boolean), marks = parts.filter(part => markRe.test(part)).join(' ');
  const branch = parts.filter(part => !markRe.test(part)).join(' ') || 'git';
  return `${icon}${marks ? ` ${marks}` : ''} ${branch.length > 14 ? `${branch.slice(0, 13)}…` : branch}`;
}
function cycleBucket(project) {
  const order = ['S', 'A', 'B'];
  project.bucket = order[(order.indexOf(project.bucket || 'B') + 1) % order.length];
  render();
  saveDraft();
}
function openGoal(project) {
  resetSheetMode(); showSheet(els.sheet); els.nav.hidden = true; els.goal.hidden = true; setDeckMeta(tierBadge(project.bucket)); els.title.textContent = `${project.name} · Goal`;
  const form = document.createElement('form');
  form.className = 'goal-form';
  form.innerHTML = `<label class="goal-editor"><span>Stage Goal</span><textarea name="goal" rows="5">${html(project.current_d)}</textarea></label><button class="goal-save" type="submit">Save Goal</button>`;
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
function openProjectOverview(project) {
  const counts = Object.fromEntries(Object.keys(TYPES).map(type => [type, activeItems(project, type).length]));
  const def = project.definition || {}, dod = definitionDodItems(def.stage_dod);
  const stageTitle = [def.current_stage_id, def.current_stage_title].filter(Boolean).join(' · ') || def.current_phase || '阶段未设定';
  const goal = def.stage_goal || project.current_d || '阶段目标未设定。';
  showSheet(els.sheet); els.sheet.classList.add('project-overview-sheet'); els.nav.hidden = true; els.goal.hidden = true;
  setDeckMeta(tierBadge(project.bucket)); els.title.textContent = `${project.name || 'Project'} · Overview`;
  const card = document.createElement('article');
  card.className = `project-overview-card overview-bucket-${html(String(project.bucket || 'B').toLowerCase())}`;
  card.innerHTML = `<section class="overview-stage"><p class="overview-eyebrow">Current Stage</p><div class="overview-stage-title"><strong>${html(stageTitle)}</strong><span>IN PROGRESS</span></div><div class="overview-rail" aria-hidden="true"><i class="done">✓</i><i class="current"></i><i></i><i></i></div><div class="overview-rail-labels"><span>Define</span><span>Decide</span><span>Execute</span><span>Close</span></div></section><section class="overview-panel overview-goal"><h4>⚐ Stage Goal</h4><p>${html(goal)}</p></section><section class="overview-panel overview-dod"><h4>Definition of Done</h4>${overviewDod(dod, def.stage_dod)}</section>${overviewCompleted(def.completed_stages)}${overviewBoundary(def.stage_out_of_scope)}<section class="metrics overview-metrics" aria-label="Project status counts">${Object.keys(TYPES).map(type => metricButton(type, counts[type])).join('')}</section>`;
  card.addEventListener('click', closeDeck);
  card.querySelectorAll('.metric').forEach(button => button.addEventListener('click', event => { event.stopPropagation(); openDeck(project.id, button.dataset.type); }));
  els.stage.replaceChildren(card);
}
function definitionDodItems(text) { return String(text || '').split(/[；;、，,]/).map(item => item.trim()).filter(Boolean).slice(0, 6); }
function overviewDod(items, raw) {
  if (!items.length) return `<p class="overview-empty">${html(raw || '阶段 DoD 未设定。')}</p>`;
  return `<div class="overview-dod-grid"><ul>${items.map(item => `<li>${html(item)}</li>`).join('')}</ul><div class="overview-donut"><b>${items.length}</b><small>项</small><em>target</em></div></div>`;
}
function overviewCompleted(stages) {
  const items = Array.isArray(stages) ? stages.slice(0, 3) : [];
  if (!items.length) return '';
  return `<section class="overview-completed"><header><b>Completed Stages</b><span>${items.length}</span></header>${items.map(stage => `<p>${html(stage)}</p>`).join('')}</section>`;
}
function overviewBoundary(text) {
  return text ? `<section class="overview-boundary"><h4>Current Boundary</h4><p>${html(text)}</p></section>` : '';
}
function openDeck(projectId, type) { resetSheetMode(); deck = { projectId, type, index: 0 }; showSheet(els.sheet); renderDeck(); }
function closeDeck() { hideSheet(els.sheet); }
function renderDeck() {
  const project = deckProject(), items = deckItems(), cfg = TYPES[deck.type];
  els.nav.hidden = false; els.goal.hidden = !project; els.goalText.textContent = project?.current_d || ''; els.title.textContent = project ? `${project.name} · ${cfg.label}` : cfg.label;
  if (!items.length) { setDeckMeta(typeBadge(deck.type)); els.stage.replaceChildren(empty(`${cfg.label} deck is clear`)); els.prev.disabled = els.next.disabled = true; return; }
  deck.index = Math.max(0, Math.min(deck.index, items.length - 1));
  setDeckMeta(typeBadge(deck.type)); els.prev.disabled = deck.index === 0; els.next.disabled = deck.index >= items.length - 1;
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
    refreshProjectGitStatus().catch(() => {});
  } catch (error) { setSync('Failed'); els.list.replaceChildren(empty(error.message || 'Load failed')); }
}
async function refreshProjectGitStatus() {
  if (!state) return;
  const data = await fetchJson('/api/project-workbench/git-status');
  projects().forEach(project => { project.gitStatus = (data.statuses || {})[project.id] || null; });
  render();
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
function openImport() { showSheet(els.importSheet); els.importStatus.textContent = dirty ? 'Submit current draft before importing.' : ''; els.importForm.elements.project_root.focus(); }
function closeImport() { hideSheet(els.importSheet); }
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
els.menuButton?.addEventListener('click', event => {
  event.stopPropagation();
  const open = Boolean(els.menuPanel?.hidden);
  if (els.menuPanel) els.menuPanel.hidden = !open;
  els.menuButton.setAttribute('aria-expanded', open ? 'true' : 'false');
});
els.archiveFilter?.addEventListener('click', event => {
  event.stopPropagation();
  const values = PROJECT_FILTER.values;
  localStorage.setItem(PROJECT_FILTER.key, values[(values.indexOf(projectFilter()) + 1) % values.length]);
  render();
});
document.addEventListener('click', event => {
  if (event.target.closest?.('#projectMenu') || !els.menuPanel) return;
  els.menuPanel.hidden = true;
  els.menuButton?.setAttribute('aria-expanded', 'false');
});
document.addEventListener('visibilitychange', () => { if (document.hidden) closeFaryoStream(); else { loadFaryoStatus().catch(() => {}); refreshProjectGitStatus().catch(() => {}); } });
setInterval(() => { if (!document.hidden) refreshProjectGitStatus().catch(() => {}); }, PROJECT_GIT_REFRESH_MS);
load();
loadFaryoStatus();
