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
const PROJECT_GIT_REFRESH_MS = 120000;
const PROJECT_FILTER = { key: 'faryoProjectFilter', values: ['active', 'all', 'archived'], labels: { active: 'Active', all: 'All', archived: 'Archived' } };
const STAGE_FLOW = [
  { state: 'stage_to_define', label: 'Stage' },
  { state: 'define_to_execute', label: 'Define' },
  { state: 'execute_to_close', label: 'Execute' },
  { state: 'closed', label: 'Close' }
];
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
function resetSheetMode() { els.sheet.classList.remove('project-overview-sheet', 'project-direction-sheet'); }
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
async function saveProjection(status = 'Saved') {
  if (!state) return;
  setSync('Saving');
  try { const data = await fetchJson('/api/project-workbench', state); state = data.workbench; setDirty(hasApprovedWork()); setSync(status); render(); }
  catch (error) { setSync(error.message || 'Save failed'); }
}
function toggleArchive(project) {
  project.archived = !project.archived;
  render();
  saveProjection();
}
function projectCard(project) {
  const counts = Object.fromEntries(Object.keys(TYPES).map(type => [type, activeItems(project, type).length]));
  const summary = project.brief || project.current_d || '';
  const git = projectGitMeta(project.gitStatus), meta = projectMeta(project);
  const card = document.createElement('article');
  const rank = stackRank(counts);
  card.className = `project-card stack-rank-${rank}${project.archived ? ' is-archived' : ''}`;
  card.innerHTML = `${cardStack(rank)}<section class="card-face" role="button" tabindex="0" aria-label="Open project direction"><div class="title-row"><h2 class="project-title">${html(project.name || 'Untitled')}</h2><button class="favorite${project.archived ? ' is-archived' : ''}" type="button" aria-label="${project.archived ? 'Unarchive' : 'Archive'} ${html(project.name || 'Untitled')}">${project.archived ? '&#9733;' : '&#9734;'}</button></div><div class="project-meta"><button class="tier-badge tier-${html((project.bucket || 'B').toLowerCase())} bucket" type="button" aria-label="Change project bucket">${html(project.bucket || 'B')}</button><span class="meta-text">${git}${meta ? html(meta) : ''}</span></div><p class="summary${summary ? '' : ' is-empty'}" role="button" tabindex="0" aria-label="Open project overview"><span class="summary-text">${html(summary)}</span></p><section class="metrics" aria-label="Project status counts">${Object.keys(TYPES).map(type => metricButton(type, counts[type])).join('')}</section></section>`;
  const open = () => openDirectionEditor(project);
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
  saveProjection();
}
function openDirectionEditor(project) {
  const def = project.definition || {}, goal = def.stage_goal || project.current_d || '';
  resetSheetMode(); showSheet(els.sheet); els.sheet.classList.add('project-direction-sheet'); els.nav.hidden = true; els.goal.hidden = true;
  const card = document.createElement('article');
  card.className = `project-direction-card overview-bucket-${html(String(project.bucket || 'B').toLowerCase())}`;
  card.innerHTML = `<form class="direction-form"><section class="direction-hero"><span class="tier-badge tier-${html((project.bucket || 'B').toLowerCase())} direction-tier">${html(project.bucket || 'B')}</span><h3>${html(project.name || 'Untitled')}</h3><button class="direction-save" type="submit">✓ Save</button></section><label class="direction-field"><span>One-line intro</span><textarea name="brief" rows="3">${html(project.brief || '')}</textarea><button type="button" data-focus="brief" aria-label="Edit intro">✎</button></label><label class="direction-field"><span>Current stage goal</span><textarea name="stage_goal" rows="5">${html(goal)}</textarea><button type="button" data-focus="stage_goal" aria-label="Edit stage goal">✎</button></label></form>`;
  const form = card.querySelector('form');
  card.querySelectorAll('[data-focus]').forEach(button => button.addEventListener('click', () => form.elements[button.dataset.focus]?.focus()));
  form.addEventListener('submit', event => {
    event.preventDefault();
    saveProjectDirection(project, {
      brief: form.elements.brief.value.trim(),
      stage_goal: form.elements.stage_goal.value.trim()
    });
  });
  els.stage.replaceChildren(card);
}
function overviewDraft(project) {
  const def = project.definition || {}, stage_dod = definitionDodItems(def.stage_dod);
  const stage_state = STAGE_FLOW.some(item => item.state === def.stage_state) ? def.stage_state : 'stage_to_define';
  return cleanOverviewDraft({ stage_state, stage_dod, stage_dod_done: Array.isArray(def.stage_dod_done) ? def.stage_dod_done : [] });
}
function cleanOverviewDraft(draft) {
  const items = [];
  for (const item of (draft.stage_dod || []).map(value => String(value || '').trim())) {
    if (item && !items.includes(item)) items.push(item);
  }
  const done = new Set((draft.stage_dod_done || []).map(item => String(item || '').trim()));
  draft.stage_dod = items;
  draft.stage_dod_done = items.filter(item => done.has(item));
  return draft;
}
function sameList(left, right) { return left.length === right.length && left.every((item, index) => item === right[index]); }
function overviewDraftChanged(project, draft) {
  const base = overviewDraft(project);
  return base.stage_state !== draft.stage_state || !sameList(base.stage_dod, draft.stage_dod) || !sameList(base.stage_dod_done, draft.stage_dod_done);
}
function overviewProject(project, draft) {
  return { ...project, definition: { ...(project.definition || {}), stage_state: draft.stage_state, stage_dod: draft.stage_dod.join('；'), stage_dod_done: draft.stage_dod_done } };
}
function openProjectOverview(project, draft = overviewDraft(project), status = '') {
  cleanOverviewDraft(draft);
  const view = overviewProject(project, draft);
  const counts = Object.fromEntries(Object.keys(TYPES).map(type => [type, activeItems(project, type).length]));
  const def = view.definition || {}, dod = draft.stage_dod, done = new Set(draft.stage_dod_done);
  const stageTitle = [def.current_stage_id, def.current_stage_title].filter(Boolean).join(' · ') || def.current_phase || '阶段未设定';
  const goal = def.stage_goal || project.current_d || '阶段目标未设定。';
  showSheet(els.sheet); els.sheet.classList.add('project-overview-sheet'); els.nav.hidden = true; els.goal.hidden = true;
  setDeckMeta(tierBadge(project.bucket)); els.title.textContent = `${project.name || 'Project'} · Overview`;
  const card = document.createElement('article');
  card.className = `project-overview-card overview-bucket-${html(String(project.bucket || 'B').toLowerCase())}`;
  card.innerHTML = `${overviewHero(view, draft.stage_state, overviewDraftChanged(project, draft))}<p class="overview-summary">${html(project.brief || '项目一句话定义未设定。')}</p><section class="overview-stage"><div class="overview-stage-head"><p>Current Stage</p><strong>${html(stageTitle)}</strong></div>${overviewStageFlow(draft.stage_state)}</section><section class="overview-panel overview-goal"><h4>⚐ Stage Goal</h4><p>${html(goal)}</p></section><section class="overview-panel overview-dod"><div class="overview-panel-head"><h4>Definition of Done</h4><div class="overview-dod-tools"><span class="overview-dod-count">${html(overviewDodCount(dod, done))}</span><button class="overview-dod-add" type="button" aria-label="Add DoD">+</button></div></div>${overviewDod(dod, done)}</section>${overviewCompleted(def.completed_stages)}${overviewBoundary(def.stage_out_of_scope)}<section class="metrics overview-metrics" aria-label="Project status counts">${Object.keys(TYPES).map(type => metricButton(type, counts[type])).join('')}</section>`;
  card.addEventListener('click', event => {
    if (!event.target.closest('button, input, textarea, select, form')) closeDeck();
  });
  card.querySelector('.overview-star')?.addEventListener('click', event => { event.stopPropagation(); toggleArchive(project); });
  card.querySelector('.overview-save')?.addEventListener('click', event => { event.stopPropagation(); saveOverviewDraft(project, draft); });
  attachStageFlow(card, project, draft);
  attachDod(card, project, draft);
  card.querySelectorAll('.metric').forEach(button => button.addEventListener('click', event => { event.stopPropagation(); openDeck(project.id, button.dataset.type); }));
  els.stage.replaceChildren(card);
  if (status) setSync(status);
}
function overviewHero(project, stageState, canSave) {
  const stateLabel = STAGE_FLOW.find(item => item.state === stageState)?.label || 'Stage';
  const meta = [projectGitMeta(project.gitStatus), projectMeta(project) ? html(projectMeta(project)) : ''].filter(Boolean).join('<span class="overview-dot"> · </span>');
  return `<section class="overview-hero"><span class="tier-badge tier-${html((project.bucket || 'B').toLowerCase())} overview-tier">${html(project.bucket || 'B')}</span><div><h3>${html(project.name || 'Untitled')}</h3><p>${meta || html(project.owner_route || 'project')}</p></div><span class="overview-state">${html(stateLabel)}</span><button class="overview-save" type="button"${canSave ? '' : ' disabled'}>Save</button><button class="overview-star" type="button" aria-label="${project.archived ? 'Unarchive' : 'Archive'} ${html(project.name || 'Untitled')}">${project.archived ? '&#9733;' : '&#9734;'}</button></section>`;
}
function overviewStageFlow(stageState) {
  const index = Math.max(0, STAGE_FLOW.findIndex(item => item.state === stageState));
  const nodes = STAGE_FLOW.map((item, idx) => `<button class="overview-node${idx === index ? ' is-current' : ''}${idx < index || stageState === 'closed' ? ' is-done' : ''}" type="button" data-state="${item.state}"${item.state === 'closed' ? ' data-confirm-close="true"' : ''}><span>${item.label}</span></button>`).join('');
  return `<div class="overview-flow flow-${index}" aria-label="Stage state"><span class="overview-line" aria-hidden="true"></span>${nodes}</div>`;
}
function attachStageFlow(card, project, draft) {
  card.querySelectorAll('.overview-node').forEach(button => button.addEventListener('click', event => {
    event.stopPropagation();
    if (button.dataset.confirmClose) return showCloseConfirm(card, project, draft);
    draft.stage_state = button.dataset.state;
    openProjectOverview(project, draft, 'Unsaved');
  }));
}
function showCloseConfirm(card, project, draft) {
  card.querySelector('.overview-confirm')?.remove();
  const box = document.createElement('div');
  box.className = 'overview-confirm';
  box.innerHTML = '<span>确认关闭当前阶段？</span><button class="primary" type="button">Close</button><button type="button" data-cancel>Cancel</button>';
  box.addEventListener('click', event => event.stopPropagation());
  box.querySelector('.primary').addEventListener('click', () => { draft.stage_state = 'closed'; openProjectOverview(project, draft, 'Unsaved'); });
  box.querySelector('[data-cancel]').addEventListener('click', () => box.remove());
  card.querySelector('.overview-flow').appendChild(box);
}
function definitionDodItems(text) { return String(text || '').split(/[\r\n；;、，,]/).map(item => item.trim()).filter(Boolean); }
function overviewDodCount(items, doneSet) { return `${items.filter(item => doneSet.has(item)).length}/${items.length}`; }
function overviewDod(items, doneSet) {
  const doneCount = items.filter(item => doneSet.has(item)).length, pct = items.length ? Math.round((doneCount / items.length) * 100) : 0;
  const list = items.map((item, index) => {
    const done = doneSet.has(item);
    return `<li class="overview-dod-row" data-dod-index="${index}"><button class="overview-dod-check${done ? ' is-done' : ''}" type="button" aria-label="${done ? 'Mark incomplete' : 'Mark done'}"><span aria-hidden="true"></span></button><button class="overview-dod-text${done ? ' is-done' : ''}" type="button">${html(item)}</button><button class="overview-dod-edit" type="button" aria-label="Edit DoD">Edit</button><button class="overview-dod-delete" type="button" aria-label="Delete DoD">×</button></li>`;
  }).join('');
  return `<div class="overview-dod-progress" aria-hidden="true"><span style="--dod-pct:${items.length ? pct : 0}%"></span></div>${items.length ? `<ul class="overview-dod-list">${list}</ul>` : '<p class="overview-empty">阶段 DoD 未设定。</p>'}`;
}
function attachDod(card, project, draft) {
  const items = draft.stage_dod, done = new Set(draft.stage_dod_done);
  card.querySelector('.overview-dod')?.addEventListener('click', event => {
    const add = event.target.closest('.overview-dod-add'), row = event.target.closest('.overview-dod-row');
    if (!add && !row) return;
    event.stopPropagation();
    if (add) return openStageDodItemEditor(card, project, draft, items.length);
    const index = Number(row.dataset.dodIndex), item = items[index], remove = event.target.closest('.overview-dod-delete');
    if (event.target.closest('.overview-dod-check')) {
      if (!item) return;
      draft.stage_dod_done = done.has(item) ? draft.stage_dod_done.filter(value => value !== item) : [...draft.stage_dod_done, item];
      return openProjectOverview(project, draft, 'Unsaved');
    }
    if (event.target.closest('.overview-dod-text, .overview-dod-edit')) return openStageDodItemEditor(card, project, draft, index);
    if (!remove) return;
    if (remove.dataset.confirm !== '1') {
      remove.dataset.confirm = '1';
      remove.textContent = 'Sure';
      remove.classList.add('is-confirm');
      return;
    }
    draft.stage_dod = items.filter((_item, itemIndex) => itemIndex !== index);
    draft.stage_dod_done = draft.stage_dod_done.filter(value => draft.stage_dod.includes(value));
    openProjectOverview(project, draft, 'Unsaved');
  });
}
function openStageDodItemEditor(card, project, draft, index) {
  const panel = card.querySelector('.overview-dod'), items = draft.stage_dod, value = items[index] || '';
  if (!panel) return;
  let list = panel.querySelector('.overview-dod-list');
  if (!list) {
    panel.querySelector('.overview-empty')?.remove();
    list = document.createElement('ul');
    list.className = 'overview-dod-list';
    panel.appendChild(list);
  }
  const editor = document.createElement('li');
  editor.className = 'overview-dod-row overview-dod-editor';
  editor.innerHTML = `<form class="overview-dod-inline-form"><textarea name="stage_dod_item" rows="2">${html(value)}</textarea><div class="overview-edit-actions"><button class="primary" type="submit">Save</button><button type="button" data-cancel>Cancel</button></div></form>`;
  const current = list.querySelector(`[data-dod-index="${index}"]`);
  if (current) current.replaceWith(editor); else list.appendChild(editor);
  const form = editor.querySelector('form');
  form.addEventListener('click', event => event.stopPropagation());
  form.addEventListener('submit', event => {
    event.preventDefault();
    const next = form.elements.stage_dod_item.value.trim();
    if (!next) return;
    const nextItems = items.slice();
    nextItems[index < nextItems.length ? index : nextItems.length] = next;
    draft.stage_dod = nextItems;
    draft.stage_dod_done = draft.stage_dod_done.filter(item => nextItems.includes(item));
    openProjectOverview(project, draft, 'Unsaved');
  });
  form.querySelector('[data-cancel]').addEventListener('click', () => openProjectOverview(project, draft));
  form.elements.stage_dod_item.focus();
}
async function saveOverviewDraft(project, draft) {
  cleanOverviewDraft(draft);
  if (!overviewDraftChanged(project, draft)) { setSync('No changes'); return; }
  setSync('Saving');
  try {
    const data = await fetchJson('/api/project-workbench/stage-dod', { project_id: project.id, stage_state: draft.stage_state, stage_dod: draft.stage_dod.join('\n'), stage_dod_done: draft.stage_dod_done });
    state = data.workbench; setDirty(hasApprovedWork()); setSync('Saved'); render();
    const next = projects().find(row => row.id === project.id);
    if (next && !els.sheet.hidden) openProjectOverview(next);
  }
  catch (error) { setSync(error.message || 'Update failed'); }
}
async function saveProjectDirection(project, payload) {
  if (!payload.stage_goal) { setSync('Stage goal required'); return; }
  setSync('Saving');
  try {
    const data = await fetchJson('/api/project-workbench/direction', { project_id: project.id, ...payload });
    state = data.workbench; setDirty(hasApprovedWork()); setSync('Saved'); render();
    const next = projects().find(row => row.id === project.id);
    if (next && !els.sheet.hidden) openDirectionEditor(next);
  } catch (error) { setSync(error.message || 'Update failed'); }
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
