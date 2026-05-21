const listEl = document.getElementById('projectList');
const syncEl = document.getElementById('syncStatus');
const sheet = document.getElementById('deckSheet');
const stageEl = document.getElementById('deckStage');
const titleEl = document.getElementById('deckTitle');
const metaEl = document.getElementById('deckMeta');
const deckGoal = document.getElementById('deckGoal');
const deckGoalText = document.getElementById('deckGoalText');
const prevBtn = document.getElementById('prevCard');
const nextBtn = document.getElementById('nextCard');
const deckNav = document.querySelector('.deck-nav');

const TYPES = {
  decision: { label: 'Decision', done: ['accepted', 'paused'] },
  action: { label: 'Action', done: ['done', 'skipped'] },
  watch: { label: 'Watch', done: ['seen'] },
};

let state = null;
let deck = { projectId: '', type: 'decision', index: 0 };

function projects() { return state?.projects || []; }
function setSync(text) { syncEl.textContent = text; }

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
          <span class="bucket">${escapeHtml(project.bucket || 'A1')}</span>
          <span class="project-brief">${escapeHtml(project.brief || '')}</span>
        </div>
      </div>
      <span class="chevron">›</span>
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
  card.querySelectorAll('.pile').forEach(button => button.addEventListener('click', () => openDeck(project.id, button.dataset.type)));
  return card;
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
    persist();
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
  persist();
  renderDeck();
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
    persist();
    renderDeck();
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
    setSync('Saved');
  } catch (error) {
    setSync('Failed');
  }
}

function empty(text) {
  const div = document.createElement('div');
  div.className = 'empty';
  div.textContent = text;
  return div;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
}

prevBtn.addEventListener('click', () => { deck.index -= 1; renderDeck(); });
nextBtn.addEventListener('click', () => { deck.index += 1; renderDeck(); });
document.getElementById('deckClose').addEventListener('click', closeDeck);
sheet.addEventListener('click', event => { if (event.target.matches('[data-close]')) closeDeck(); });

load();
