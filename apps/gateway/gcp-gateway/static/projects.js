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
  decision: { label: 'Decision', done: ['accepted', 'done', 'seen'], actions: [['accept', 'Approve', 'primary'], ['revise', 'Revise', ''], ['pause', 'Pause', 'danger']], left: 'accept', right: 'pause' },
  action: { label: 'Action', done: ['accepted', 'done', 'seen'], actions: [['done', 'Confirm', 'primary'], ['revise', 'Revise', ''], ['to-decision', 'Escalate', 'danger']], left: 'done', right: 'to-decision' },
  watch: { label: 'Watch', done: ['accepted', 'done', 'seen'], actions: [['seen', 'Seen', 'primary'], ['revise', 'Revise', ''], ['to-decision', 'Escalate', 'danger']], left: 'seen', right: 'to-decision' }
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
const projectRuntime = new Map();
const pendingDecisions = new Map();
const pendingTransitions = new Set();
let faryoSession = '', faryoAgentRunning = false, faryoStream = null;
const sheetTimers = new WeakMap();
let projectionSaveTimer = null;
const projects = () => state?.projects || [];
const html = value => String(value || '').replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
const empty = text => Object.assign(document.createElement('div'), { className: 'empty', textContent: text });
const setLabel = (el, text) => { const label = el?.querySelector?.('.label'); if (label) label.textContent = text; else if (el) el.textContent = text; };
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
const transitionKey = (project, item) => `${project.id}:${item.id}`;
const activeItems = (project, type) => (project.items || []).filter(item => item.type === type && !pendingTransitions.has(transitionKey(project, item)) && ownerQueueItem(item) && !TYPES[type].done.includes(item.status || 'open'));
const dispatchableProjects = () => projects().filter(projectReadyForDispatch);
const deckProject = () => projects().find(project => project.id === deck.projectId) || projects()[0];
const deckItems = () => { const project = deckProject(); return project ? activeItems(project, deck.type) : []; };
function projectFilter() {
  const value = localStorage.getItem(PROJECT_FILTER.key);
  return PROJECT_FILTER.values.includes(value) ? value : PROJECT_FILTER.values[0];
}
function setSaveState(label, disabled) {
  setLabel(els.sync, label);
  els.sync.disabled = disabled;
}
function projectState(projectId) {
  return projectRuntime.get(projectId) || { sync: 'saved' };
}
function projectSyncLabel(projectId) {
  const runtime = projectState(projectId);
  return runtime.syncLabel || ({ saved: 'Saved', syncing: 'Syncing', sync_needed: 'Sync Needed', sync_failed: 'Sync Failed' }[runtime.sync || 'saved']);
}
function projectNeedsSync(project) {
  return Boolean(project?.definition && Object.keys(project.definition).length) && project.definition_sync?.status !== 'applied';
}
function hydrateProjectRuntime(rows) {
  projectRuntime.clear();
  (rows || []).forEach(project => {
    if (!projectNeedsSync(project)) return;
    const failed = project.definition_sync?.status === 'failed';
    projectRuntime.set(project.id, { sync: failed ? 'sync_failed' : 'sync_needed', syncLabel: failed ? 'Sync Failed' : 'Sync Needed' });
  });
  syncTopActions();
}
function setProjectState(projectId, patch) {
  const next = { ...projectState(projectId), ...patch };
  const project = projects().find(item => item.id === projectId);
  if ((next.sync || 'saved') === 'saved' && projectNeedsSync(project)) {
    const failed = project.definition_sync?.status === 'failed';
    next.sync = failed ? 'sync_failed' : 'sync_needed';
    next.syncLabel = failed ? 'Sync Failed' : 'Sync Needed';
  }
  if ((next.sync || 'saved') === 'saved' && !next.submitting && !next.submitError && !next.syncLabel) projectRuntime.delete(projectId);
  else projectRuntime.set(projectId, next);
  syncTopActions();
}
function projectBlocked(project) {
  const runtime = projectState(project.id);
  return runtime.submitting || ['syncing', 'sync_needed', 'sync_failed'].includes(runtime.sync);
}
function projectReadyForDispatch(project) {
  return !project.archived && !projectBlocked(project) && (project.items || []).some(item => item.stage === 'approved_for_workorder');
}
function topSyncState() {
  const runtimes = projects().map(project => projectState(project.id));
  const busy = runtimes.find(runtime => runtime.submitting || runtime.sync === 'syncing');
  if (busy) return { label: busy.syncLabel || (busy.submitting ? 'Submitting' : 'Syncing'), disabled: true };
  const failed = runtimes.find(runtime => runtime.sync === 'sync_failed' || runtime.submitError);
  if (failed) return { label: failed.syncLabel || failed.submitError || 'Sync Failed', disabled: true };
  const needed = runtimes.find(runtime => runtime.sync === 'sync_needed');
  if (needed) return { label: needed.syncLabel || 'Sync Needed', disabled: true };
  if (dirty) return { label: 'Save', disabled: !state };
  return { label: 'Saved', disabled: true };
}
function syncSubmitState() {
  els.submit.disabled = !state || projects().some(projectBlocked) || !dispatchableProjects().length;
}
function syncTopActions() {
  const sync = topSyncState();
  setSaveState(sync.label, sync.disabled);
  syncSubmitState();
}
function setDirty(value) {
  dirty = Boolean(value);
  syncTopActions();
}
function setGlobalBusy(label) {
  setSaveState(label, true);
  els.submit.disabled = true;
}
function withLocalOverviewMeta(workbench) {
  if (!dirty || !workbench?.projects) return workbench;
  const local = new Map(projects().map(project => [project.id, project]));
  return { ...workbench, projects: workbench.projects.map(project => {
    const current = local.get(project.id);
    return current ? { ...project, bucket: current.bucket, rank: current.rank, archived: current.archived } : project;
  }) };
}
function render() {
  const mode = projectFilter(), items = projects().filter(project => mode === 'all' || Boolean(project.archived) === (mode === 'archived'));
  if (els.archiveFilterLabel) els.archiveFilterLabel.textContent = PROJECT_FILTER.labels[mode];
  els.list.replaceChildren(...(items.length ? items.map(projectCard) : [empty(mode === 'archived' ? 'No archived projects' : 'No projects')]));
}
async function saveProjection() {
  if (!state || !dirty) return;
  setGlobalBusy('Saving');
  try {
    const data = await fetchJson('/api/project-workbench', state);
    state = data.workbench;
    setDirty(false);
    render();
  } catch (_error) {
    setDirty(true);
  }
}
function toggleArchive(project) {
  project.archived = !project.archived;
  render();
  setDirty(true);
  queueProjectionSave();
}
function projectCard(project) {
  const counts = Object.fromEntries(Object.keys(TYPES).map(type => [type, activeItems(project, type).length]));
  const summary = project.brief || project.current_d || '';
  const git = projectGitMeta(project.gitStatus), meta = projectMeta(project);
  const card = document.createElement('article');
  const rank = stackRank(counts);
  card.className = `project-card stack-rank-${rank}${project.archived ? ' is-archived' : ''}`;
  card.innerHTML = `${cardStack(rank)}<section class="card-face" role="button" tabindex="0" aria-label="Open project overview"><div class="title-row"><h2 class="project-title">${html(project.name || 'Untitled')}</h2><button class="favorite${project.archived ? ' is-archived' : ''}" type="button" aria-label="${project.archived ? 'Unarchive' : 'Archive'} ${html(project.name || 'Untitled')}">${project.archived ? '&#9733;' : '&#9734;'}</button></div><div class="project-meta"><button class="tier-badge tier-${html((project.bucket || 'B').toLowerCase())} bucket" type="button" aria-label="Change project bucket">${html(project.bucket || 'B')}</button><span class="meta-text">${git}${meta ? html(meta) : ''}</span></div><p class="summary${summary ? '' : ' is-empty'}" role="button" tabindex="0" aria-label="Open project overview"><span class="summary-text">${html(summary)}</span></p><section class="metrics" aria-label="Project status counts">${Object.keys(TYPES).map(type => metricButton(type, counts[type])).join('')}</section></section>`;
  const open = () => openProjectOverview(project);
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
  setDirty(true);
  queueProjectionSave();
}
function queueProjectionSave() {
  clearTimeout(projectionSaveTimer);
  projectionSaveTimer = setTimeout(() => saveProjection().catch(() => {}), 180);
}
function overviewDraft(project) {
  const def = project.definition || {}, stage_dod = definitionDodItems(def.stage_dod);
  const stage_state = STAGE_FLOW.some(item => item.state === def.stage_state) ? def.stage_state : 'stage_to_define';
  return cleanOverviewDraft({ brief: project.brief || '', stage_goal: def.stage_goal || project.current_d || '', stage_state, stage_dod, stage_dod_done: Array.isArray(def.stage_dod_done) ? def.stage_dod_done : [] });
}
function cleanOverviewDraft(draft) {
  draft.brief = String(draft.brief || '').trim();
  draft.stage_goal = String(draft.stage_goal || '').trim();
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
  return base.brief !== draft.brief || base.stage_goal !== draft.stage_goal || base.stage_state !== draft.stage_state || !sameList(base.stage_dod, draft.stage_dod) || !sameList(base.stage_dod_done, draft.stage_dod_done);
}
function overviewProject(project, draft) {
  return { ...project, brief: draft.brief, current_d: draft.stage_goal, definition: { ...(project.definition || {}), stage_goal: draft.stage_goal, stage_state: draft.stage_state, stage_dod: draft.stage_dod.join('；'), stage_dod_done: draft.stage_dod_done } };
}
function overviewDefinitionPatch(project, draft) {
  const updated = overviewProject(project, draft);
  return { id: project.id, brief: updated.brief, current_d: updated.current_d, definition: updated.definition };
}
function openProjectOverview(project, draft = overviewDraft(project)) {
  cleanOverviewDraft(draft);
  const view = overviewProject(project, draft);
  const counts = Object.fromEntries(Object.keys(TYPES).map(type => [type, activeItems(project, type).length]));
  const def = view.definition || {}, dod = draft.stage_dod, done = new Set(draft.stage_dod_done);
  const stageTitle = [def.current_stage_id, def.current_stage_title].filter(Boolean).join(' · ') || def.current_phase || '阶段未设定';
  const goal = draft.stage_goal || def.stage_goal || project.current_d || '';
  showSheet(els.sheet); els.sheet.classList.add('project-overview-sheet'); els.nav.hidden = true; els.goal.hidden = true;
  setDeckMeta(tierBadge(project.bucket)); els.title.textContent = `${project.name || 'Project'} · Overview`;
  const card = document.createElement('article');
  card.className = `project-overview-card overview-bucket-${html(String(project.bucket || 'B').toLowerCase())}`;
  card.innerHTML = `${overviewHero(view, draft.stage_state, overviewDraftChanged(project, draft))}<section class="overview-panel overview-direction"><label class="overview-field"><span>One-line intro</span><textarea name="brief" rows="2">${html(draft.brief)}</textarea></label><label class="overview-field"><span>Stage Goal</span><textarea name="stage_goal" rows="3">${html(goal)}</textarea></label></section><section class="overview-stage"><div class="overview-stage-head"><p>Current Stage</p><strong>${html(stageTitle)}</strong></div>${overviewStageFlow(draft.stage_state)}</section><section class="overview-panel overview-dod"><div class="overview-panel-head"><h4>Definition of Done</h4><div class="overview-dod-tools"><span class="overview-dod-count">${html(overviewDodCount(dod, done))}</span><button class="overview-dod-add" type="button" aria-label="Add DoD">+</button></div></div>${overviewDod(dod, done)}</section>${overviewCompleted(def.completed_stages)}${overviewBoundary(def.stage_out_of_scope)}<section class="metrics overview-metrics" aria-label="Project status counts">${Object.keys(TYPES).map(type => metricButton(type, counts[type])).join('')}</section>`;
  card.addEventListener('click', event => {
    if (!event.target.closest('button, input, textarea, select, form, label, .overview-direction')) closeDeck();
  });
  card.querySelector('.overview-save')?.addEventListener('click', event => { event.stopPropagation(); saveOverviewDraft(project, draft); });
  card.querySelector('.overview-submit')?.addEventListener('click', event => { event.stopPropagation(); submitProject(project.id, event.currentTarget); });
  attachOverviewDirection(card, project, draft);
  attachStageFlow(card, project, draft);
  attachDod(card, project, draft);
  card.querySelectorAll('.metric').forEach(button => button.addEventListener('click', event => { event.stopPropagation(); openDeck(project.id, button.dataset.type); }));
  els.stage.replaceChildren(card);
}
function syncOverviewActions(card, project, draft) {
  const changed = overviewDraftChanged(project, draft), save = card.querySelector('.overview-save'), submit = card.querySelector('.overview-submit');
  const runtime = projectState(project.id), busy = runtime.sync === 'syncing' || runtime.submitting;
  const canSave = changed || ['sync_needed', 'sync_failed'].includes(runtime.sync);
  if (save) {
    setLabel(save, busy ? projectSyncLabel(project.id) : (canSave ? 'Save' : projectSyncLabel(project.id)));
    save.disabled = busy || !canSave;
  }
  if (submit) {
    setLabel(submit, runtime.submitting ? 'Submitting' : (runtime.submitError ? 'Retry' : 'Submit'));
    submit.disabled = changed || busy || (runtime.sync || 'saved') !== 'saved';
  }
}
function attachOverviewDirection(card, project, draft) {
  card.querySelector('.overview-direction')?.addEventListener('input', event => {
    const field = event.target?.name;
    if (field === 'brief' || field === 'stage_goal') {
      draft[field] = event.target.value.trim();
      syncOverviewActions(card, project, draft);
    }
  });
}
function overviewHero(project, stageState, canSave) {
  const runtime = projectState(project.id), busy = runtime.sync === 'syncing' || runtime.submitting;
  const saveReady = canSave || ['sync_needed', 'sync_failed'].includes(runtime.sync);
  const stateLabel = STAGE_FLOW.find(item => item.state === stageState)?.label || 'Stage';
  const meta = [projectGitMeta(project.gitStatus), projectMeta(project) ? html(projectMeta(project)) : ''].filter(Boolean).join('<span class="overview-dot"> · </span>');
  const saveLabel = busy ? projectSyncLabel(project.id) : (saveReady ? 'Save' : projectSyncLabel(project.id));
  const submitLabel = runtime.submitting ? 'Submitting' : (runtime.submitError ? 'Retry' : 'Submit');
  const submitDisabled = canSave || busy || (runtime.sync || 'saved') !== 'saved';
  return `<section class="overview-hero"><div class="overview-title"><h3>${html(project.name || 'Untitled')}</h3><p>${meta || html(project.owner_route || 'project')}<span class="overview-state">Stage · ${html(stateLabel)}</span></p></div><div class="overview-actions"><button class="overview-save" type="button"${busy || !saveReady ? ' disabled' : ''}>${html(saveLabel)}</button><button class="overview-submit" type="button"${submitDisabled ? ' disabled' : ''}>${html(submitLabel)}</button></div></section>`;
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
    openProjectOverview(project, draft);
  }));
}
function showCloseConfirm(card, project, draft) {
  card.querySelector('.overview-confirm')?.remove();
  const box = document.createElement('div');
  box.className = 'overview-confirm';
  box.innerHTML = '<span>确认关闭当前阶段？</span><button class="primary" type="button">Close</button><button type="button" data-cancel>Cancel</button>';
  box.addEventListener('click', event => event.stopPropagation());
  box.querySelector('.primary').addEventListener('click', () => { draft.stage_state = 'closed'; openProjectOverview(project, draft); });
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
      return openProjectOverview(project, draft);
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
    openProjectOverview(project, draft);
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
    openProjectOverview(project, draft);
  });
  form.querySelector('[data-cancel]').addEventListener('click', () => openProjectOverview(project, draft));
  form.elements.stage_dod_item.focus();
}
async function saveOverviewDraft(project, draft) {
  cleanOverviewDraft(draft);
  const base = overviewDraft(project);
  const directionChanged = base.brief !== draft.brief || base.stage_goal !== draft.stage_goal;
  const stageChanged = base.stage_state !== draft.stage_state || !sameList(base.stage_dod, draft.stage_dod) || !sameList(base.stage_dod_done, draft.stage_dod_done);
  if (!directionChanged && !stageChanged && !['sync_needed', 'sync_failed'].includes(projectState(project.id).sync)) return true;
  const button = els.stage.querySelector('.overview-save');
  setProjectState(project.id, { sync: 'syncing', syncLabel: 'Syncing', submitError: '' });
  if (button) { setLabel(button, 'Syncing'); button.disabled = true; }
  try {
    const data = await syncProjectState(project.id, overviewDefinitionPatch(project, draft));
    state = withLocalOverviewMeta(data.workbench);
    hydrateProjectRuntime(projects());
    setProjectState(project.id, { sync: 'saved', syncLabel: '', submitError: '' });
    render();
    const next = projects().find(row => row.id === project.id);
    if (next && !els.sheet.hidden) openProjectOverview(next);
    return true;
  } catch (error) {
    if (error.workbench) {
      state = withLocalOverviewMeta(error.workbench);
      hydrateProjectRuntime(projects());
      render();
    }
    const label = error.projectSync ? 'Sync Failed' : 'Gateway Failed';
    setProjectState(project.id, { sync: 'sync_failed', syncLabel: label });
    const card = els.stage.querySelector('.project-overview-card');
    if (card) syncOverviewActions(card, project, draft);
    return false;
  }
}
async function syncProjectState(projectId, project) {
  const data = await fetchJson('/api/project-workbench/sync-project', { projects: [project], downlink_project_ids: [projectId], downlink_scope: 'definition' });
  if (data.downlink?.status !== 'applied') {
    const error = new Error(data.downlink?.status === 'failed' ? 'Project sync failed' : 'Project sync pending');
    error.projectSync = true;
    error.workbench = data.workbench;
    throw error;
  }
  return data;
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
function decisionKey(project, item) { return `${project.id}:${item.id}`; }
function decisionPrompt(item) {
  const value = item?.decision_prompt;
  if (item?.type !== 'decision' || !value || typeof value !== 'object') return null;
  const mode = String(value.mode || '').trim();
  if (!['choice', 'binary', 'checklist', 'short_note'].includes(mode)) return null;
  const prompt = { mode, label: String(value.label || '').trim(), required: Boolean(value.required), placeholder: String(value.placeholder || '').trim() };
  if (mode === 'choice' || mode === 'binary') {
    const options = (Array.isArray(value.options) ? value.options : []).map(option => ({ id: String(option?.id || '').trim(), label: String(option?.label || '').trim() })).filter(option => option.id && option.label).slice(0, mode === 'binary' ? 2 : 5);
    return options.length >= 2 ? { ...prompt, options } : null;
  }
  if (mode === 'checklist') {
    const items = (Array.isArray(value.items) ? value.items : []).map(text => String(text || '').trim()).filter(Boolean).slice(0, 5);
    return items.length ? { ...prompt, items } : null;
  }
  return prompt;
}
function ownerDecision(project, item) {
  const saved = item?.owner_decision && typeof item.owner_decision === 'object' ? item.owner_decision : {};
  const pending = pendingDecisions.get(decisionKey(project, item)) || {};
  const value = { ...saved, ...pending };
  return {
    selected: String(value.selected || '').trim(),
    checked: Array.isArray(value.checked) ? value.checked.map(text => String(text || '').trim()).filter(Boolean).slice(0, 5) : [],
    note: String(value.note || '').trim()
  };
}
function setOwnerDecision(project, item, patch) {
  pendingDecisions.set(decisionKey(project, item), { ...ownerDecision(project, item), ...patch });
}
function ownerDecisionPayload(project, item) {
  const decision = ownerDecision(project, item), payload = {};
  if (decision.selected) payload.selected = decision.selected;
  if (decision.checked.length) payload.checked = decision.checked;
  if (decision.note) payload.note = decision.note;
  return payload;
}
function decisionReady(project, item) {
  const prompt = decisionPrompt(item), decision = ownerDecision(project, item);
  if (!prompt) return true;
  if (prompt.mode === 'choice' || prompt.mode === 'binary') return Boolean(decision.selected);
  if (prompt.mode === 'checklist') return !prompt.required || decision.checked.length > 0;
  return !prompt.required || Boolean(decision.note);
}
function decisionSummary(decision) {
  return [decision.selected, Array.isArray(decision.checked) ? decision.checked.join('、') : '', decision.note].filter(Boolean).join('；');
}
function decisionControl(project, item) {
  if (item.type !== 'decision') return '';
  const prompt = decisionPrompt(item), decision = ownerDecision(project, item);
  let control = '';
  if (prompt?.mode === 'choice' || prompt?.mode === 'binary') {
    control = `<div class="decision-options">${prompt.options.map(option => `<button class="decision-option${decision.selected === option.id ? ' is-selected' : ''}" type="button" data-decision-choice="${html(option.id)}"><b>${html(option.id)}</b><span>${html(option.label)}</span></button>`).join('')}</div>`;
  } else if (prompt?.mode === 'checklist') {
    control = `<div class="decision-checks">${prompt.items.map(text => `<button class="decision-check${decision.checked.includes(text) ? ' is-selected' : ''}" type="button" data-decision-check="${html(text)}"><span>${html(text)}</span></button>`).join('')}</div>`;
  }
  const noteLabel = prompt?.placeholder || 'Optional short decision note';
  return `<section class="owner-decision"><div class="owner-decision-head"><span>Owner Decision</span>${prompt?.mode ? `<small>${html(prompt.mode.replace('_', ' '))}</small>` : ''}</div>${prompt?.label ? `<p>${html(prompt.label)}</p>` : ''}${control}<textarea class="decision-note" data-decision-note rows="2" placeholder="${html(noteLabel)}">${html(decision.note)}</textarea></section>`;
}
function deckActions(project, item) {
  return TYPES[item.type].actions.map(([action, label, cls]) => {
    const selected = action === 'accept' ? ownerDecision(project, item).selected : '';
    const disabled = item.type === 'decision' && action === 'accept' && !decisionReady(project, item);
    return `<button class="${cls}" data-action="${action}" type="button"${disabled ? ' disabled' : ''}>${html(selected ? `${label} ${selected}` : label)}</button>`;
  }).join('');
}
function deckCard(project, item) {
  const card = document.createElement('article');
  card.className = 'deck-card';
  const runtime = projectState(project.id);
  const cardStatus = runtime.sync && runtime.sync !== 'saved' ? projectSyncLabel(project.id) : (STATUS[item.status] || item.status || 'open');
  card.innerHTML = `<span class="deck-kind ${item.type}">${TYPES[item.type].label}</span><h3>${html(item.title)}</h3><p class="item-body">${html(item.body)}</p>${item.recommendation ? `<p class="recommendation">${html(item.recommendation)}</p>` : ''}${decisionControl(project, item)}<div class="deck-status">${html(cardStatus)}</div><div class="deck-actions">${deckActions(project, item)}</div>`;
  attachDecisionControl(card, project, item);
  card.querySelectorAll('[data-action]').forEach(button => button.addEventListener('click', () => applyItemAction(project, item, button.dataset.action, button)));
  attachSwipe(card, project, item);
  return card;
}
function attachDecisionControl(card, project, item) {
  card.querySelectorAll('[data-decision-choice]').forEach(button => button.addEventListener('click', event => {
    event.stopPropagation();
    setOwnerDecision(project, item, { selected: button.dataset.decisionChoice });
    renderDeck();
  }));
  card.querySelectorAll('[data-decision-check]').forEach(button => button.addEventListener('click', event => {
    event.stopPropagation();
    const current = ownerDecision(project, item).checked, value = button.dataset.decisionCheck;
    setOwnerDecision(project, item, { checked: current.includes(value) ? current.filter(item => item !== value) : [...current, value] });
    renderDeck();
  }));
  card.querySelector('[data-decision-note]')?.addEventListener('input', event => {
    setOwnerDecision(project, item, { note: event.target.value });
    const approve = card.querySelector('[data-action="accept"]');
    if (approve) {
      approve.disabled = !decisionReady(project, item);
      const selected = ownerDecision(project, item).selected;
      setLabel(approve, selected ? `Approve ${selected}` : 'Approve');
    }
  });
}
async function applyItemAction(project, item, action, button = null) {
  if (action === 'revise') return openItemRevision(project, item);
  const eventType = TRANSITIONS[action];
  if (!eventType) return;
  if (item.type === 'decision' && action === 'accept' && !decisionReady(project, item)) return;
  const pendingKey = transitionKey(project, item);
  if (pendingTransitions.has(pendingKey)) return;
  const payload = {
    project_id: project.id,
    item_id: item.id,
    event_type: eventType,
    actor: 'owner',
    source: 'gateway-ui',
    summary: `${action}: ${item.title || item.id}`
  };
  if (item.type === 'decision' && action === 'accept') {
    const decision = ownerDecisionPayload(project, item), summary = decisionSummary(decision);
    if (Object.keys(decision).length) {
      payload.owner_decision = decision;
      payload.summary = `approve${summary ? ` ${summary}` : ''}: ${item.title || item.id}`;
    }
  }
  pendingTransitions.add(pendingKey);
  setProjectState(project.id, { sync: 'syncing', syncLabel: 'Deciding', submitError: '' });
  if (button) { button.closest('.deck-actions')?.querySelectorAll('button').forEach(item => { item.disabled = true; }); setLabel(button, 'Deciding'); }
  render();
  const nextProject = deckProject();
  const hasNextCard = nextProject && activeItems(nextProject, deck.type).length;
  if (hasNextCard) renderDeck(); else closeDeck();
  try {
    const data = await fetchJson('/api/project-workbench/transition', payload);
    state = withLocalOverviewMeta(data.workbench);
    pendingDecisions.delete(decisionKey(project, item));
    pendingTransitions.delete(pendingKey);
    setProjectState(project.id, { sync: 'saved', syncLabel: '' });
    render();
    if (!els.sheet.hidden) renderDeck();
  } catch (_error) {
    pendingTransitions.delete(pendingKey);
    setProjectState(project.id, { sync: 'sync_failed', syncLabel: 'Decision Failed' });
    render();
    if (!hasNextCard) showSheet(els.sheet);
    renderDeck();
  }
}
function openItemRevision(project, item) {
  els.nav.hidden = true;
  const form = document.createElement('form');
  form.className = 'deck-card revise-card';
  form.innerHTML = `<span class="deck-kind ${item.type}">${TYPES[item.type].label} Revision</span><label><span>Card Title</span><input name="title" value="${html(item.title)}"></label><label><span>Body</span><textarea name="body" rows="4">${html(item.body)}</textarea></label><label><span>Recommendation</span><textarea name="recommendation" rows="3">${html(item.recommendation)}</textarea></label><div class="deck-actions revise-actions"><button class="primary" type="submit">Save</button><button type="button" data-cancel>Cancel</button></div>`;
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
async function applyItemUpdate(project, item, fields) {
  setProjectState(project.id, { sync: 'syncing', syncLabel: 'Syncing', submitError: '' });
  try {
    const data = await fetchJson('/api/project-workbench/transition', { project_id: project.id, item_id: item.id, event_type: 'item_updated', actor: 'owner', source: 'gateway-ui', summary: `Revise: ${fields.title || item.title}`, item: fields });
    state = withLocalOverviewMeta(data.workbench); setProjectState(project.id, { sync: 'saved', syncLabel: '' }); render(); if (!els.sheet.hidden) renderDeck();
  } catch (_error) {
    setProjectState(project.id, { sync: 'sync_failed', syncLabel: 'Sync Failed' });
    if (!els.sheet.hidden) renderDeck();
  }
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
    pendingDecisions.clear(); pendingTransitions.clear(); state = data.workbench; hydrateProjectRuntime(projects()); setDirty(false); render();
    refreshProjectGitStatus().catch(() => {});
  } catch (error) { setSaveState('Failed', true); els.list.replaceChildren(empty(error.message || 'Load failed')); }
}
async function refreshProjectGitStatus() {
  if (!state) return;
  const data = await fetchJson('/api/project-workbench/git-status');
  projects().forEach(project => { project.gitStatus = (data.statuses || {})[project.id] || null; });
  render();
}
async function submitProject(projectId, button) {
  if (!state) return;
  if (!projectId) return;
  const runtime = projectState(projectId);
  if ((runtime.sync || 'saved') !== 'saved' || runtime.submitting) return;
  setProjectState(projectId, { submitting: true, submitError: '', syncLabel: 'Submitting' });
  if (button) { setLabel(button, 'Submitting'); button.disabled = true; }
  try {
    const data = await fetchJson('/api/project-workbench/submit-stage', { notify_project_ids: [projectId], submit_scope: 'project' });
    state = withLocalOverviewMeta(data.workbench);
    setProjectState(projectId, { submitting: false, sync: 'saved', syncLabel: '', submitError: '' });
    render();
  } catch (error) {
    setProjectState(projectId, { submitting: false, sync: 'saved', syncLabel: '', submitError: 'Submit Failed' });
    if (button) { setLabel(button, 'Retry'); button.disabled = false; }
  } finally {
    const nextProject = projects().find(project => project.id === projectId);
    if (nextProject && !els.sheet.hidden) openProjectOverview(nextProject);
  }
}
async function submitApprovedWork() {
  const batch = dispatchableProjects();
  if (!batch.length) return;
  batch.forEach(project => setProjectState(project.id, { submitting: true, submitError: '', syncLabel: 'Submitting' }));
  setLabel(els.submit, batch.length > 1 ? `Running ${batch.length}` : 'Running');
  els.submit.disabled = true;
  const results = await Promise.allSettled(batch.map(async project => ({
    project,
    data: await fetchJson('/api/faryo/dispatch', { project_id: project.id, title: `P:${project.name || project.id}`, prompt: '按项目工作台已批准事项创建并执行本轮工单。' })
  })));
  const failed = [];
  let redirect = '';
  results.forEach((result, index) => {
    if (result.status === 'fulfilled') {
      const { project, data } = result.value;
      setProjectState(project.id, { submitting: false, sync: 'saved', syncLabel: '', submitError: '' });
      if (batch.length === 1 && data.redirect) redirect = data.redirect;
    } else {
      const project = batch[index];
      failed.push(project.id);
      setProjectState(project.id, { submitting: false, sync: 'saved', syncLabel: '', submitError: 'Submit Failed' });
    }
  });
  if (redirect) location.href = redirect;
  else {
    await load();
    failed.forEach(projectId => setProjectState(projectId, { submitting: false, sync: 'saved', syncLabel: '', submitError: 'Submit Failed' }));
    render();
    setLabel(els.submit, 'Run');
  }
}
async function fetchJson(url, body = null) {
  const init = body ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : { cache: 'no-store' };
  const data = await (await fetch(url, init)).json();
  if (!data.ok) throw new Error(data.error || 'Request failed');
  return data;
}
function openImport() { showSheet(els.importSheet); els.importStatus.textContent = dirty ? 'Save current draft before importing.' : ''; els.importForm.elements.project_root.focus(); }
function closeImport() { hideSheet(els.importSheet); }
async function importProject(event) {
  event.preventDefault();
  if (dirty) { els.importStatus.textContent = 'Save current draft before importing.'; return; }
  const project_root = els.importForm.elements.project_root.value.trim(), owner_route = els.importForm.elements.owner_route.value;
  if (!project_root) { els.importStatus.textContent = 'Project Root is required.'; return; }
  const button = els.importForm.querySelector('button[type="submit"]');
  button.disabled = true; els.importStatus.textContent = 'Importing'; setGlobalBusy('Saving');
  try { const data = await fetchJson('/api/project-workbench/import', { owner_route, project_root }); pendingDecisions.clear(); state = data.workbench; hydrateProjectRuntime(projects()); setDirty(false); els.importForm.elements.project_root.value = ''; closeImport(); render(); }
  catch (error) { els.importStatus.textContent = error.message || 'Import failed'; setDirty(dirty); }
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
els.submit.addEventListener('click', submitApprovedWork);
els.sync.addEventListener('click', saveProjection);
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
