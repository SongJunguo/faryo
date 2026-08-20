const GOAL_STATES = {
  active: { compact: "Goal Active", detail: "Active", tone: "active" },
  blocked: { compact: "Goal Blocked", detail: "Blocked", tone: "blocked" },
  complete: { compact: "Goal Done", detail: "Complete", tone: "complete" },
  paused: { compact: "Goal Paused", detail: "Paused", tone: "paused" },
  usage_limited: { compact: "Goal Limited", detail: "Usage limited", tone: "limited" },
};

function elapsedLabel(value) {
  const seconds = Number(value);
  if (!Number.isFinite(seconds) || seconds < 1) return "";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  const remainder = minutes % 60;
  return remainder ? `${hours}h ${remainder}m` : `${hours}h`;
}

export function goalViewModel(snapshot) {
  const status = String(snapshot?.status || "").trim().toLowerCase();
  const state = GOAL_STATES[status];
  if (!state) {
    return { visible: false, compact: "", detail: "No goal", tone: "none" };
  }
  const elapsed = elapsedLabel(snapshot?.timeUsedSeconds);
  return {
    visible: true,
    compact: state.compact,
    detail: `${state.detail}${elapsed ? ` · ${elapsed}` : ""}`,
    tone: state.tone,
  };
}

export function renderGoalStatus(snapshot, { pill, details } = {}) {
  const model = goalViewModel(snapshot);
  if (details) details.textContent = model.detail;
  if (!pill) return model;
  pill.hidden = !model.visible;
  for (const tone of ["active", "blocked", "complete", "paused", "limited"])
    pill.classList.remove(`goal-${tone}`);
  if (!model.visible) {
    pill.textContent = "";
    pill.removeAttribute("title");
    pill.removeAttribute("aria-label");
    return model;
  }
  pill.classList.add(`goal-${model.tone}`);
  pill.textContent = model.compact;
  pill.title = `Goal status · ${model.detail}`;
  pill.setAttribute("aria-label", pill.title);
  return model;
}
