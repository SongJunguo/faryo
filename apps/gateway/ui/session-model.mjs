export const SESSION_LABELS = {
  starting: "Starting",
  running: "Running",
  waiting: "Waiting",
  exited: "Exited",
  desktop: "Desktop",
  resumable: "Resume",
  archived: "Archived",
};

export function localSessionTime(item, now = new Date()) {
  const timestamp = Number(item?.updatedTs || 0);
  if (!Number.isFinite(timestamp) || timestamp <= 0)
    return item?.updatedAt || "";
  const date = new Date(timestamp * 1000);
  const sameDay = date.toDateString() === now.toDateString();
  return new Intl.DateTimeFormat(
    undefined,
    sameDay
      ? { hour: "2-digit", minute: "2-digit" }
      : {
          month: "2-digit",
          day: "2-digit",
          hour: "2-digit",
          minute: "2-digit",
        },
  ).format(date);
}

export function sessionViewModel(item, routeLabels = {}) {
  const targetSession = item?.tmuxSession || "";
  const active = Boolean(targetSession);
  const archived = !active && Boolean(item?.archived);
  const lifecycle = String(
    item?.state ||
      (active
        ? item?.agentRunning
          ? "running"
          : "waiting"
        : archived
          ? "archived"
          : "resumable"),
  );
  const blocked = Boolean(item?.limitReached);
  const canChooseFolder = !active && lifecycle === "resumable";
  const title = [
    item?.title || item?.id || "Untitled session",
    item?.gitLabel || "",
  ]
    .filter(Boolean)
    .join(" ");
  const ownership =
    active && !item?.managed && lifecycle !== "desktop"
      ? " · Desktop tmux"
      : "";
  const where = item?.cwdLabel || item?.cwd || "";
  const updatedAt = localSessionTime(item);
  const state =
    blocked && lifecycle === "resumable"
      ? "Limit reached"
      : SESSION_LABELS[lifecycle] || "Unknown";
  const routeLabel =
    item?.routeLabel || routeLabels[item?.route] || item?.route || "";
  const agent = item?.source === "codex-cli" ? "Codex" : "Runtime";
  return {
    targetSession,
    agentSessionId: item?.id || "",
    source: item?.source || "",
    active,
    archived,
    blocked,
    lifecycle,
    canChooseFolder,
    chooseFolderDisabled: canChooseFolder && blocked,
    canReceive: !["archived", "exited", "starting"].includes(lifecycle),
    title,
    state,
    updatedAt,
    meta: `${routeLabel} · ${agent}${ownership}${where ? ` · ${where}` : ""} · ${updatedAt} · ${state}`,
    tooltip: [title, item?.cwd || "", updatedAt, state]
      .filter(Boolean)
      .join(" · "),
    className: `session-card state-${lifecycle}${active ? "" : " inactive"}${lifecycle === "running" ? " running" : lifecycle === "waiting" ? " waiting" : ""}`,
  };
}
