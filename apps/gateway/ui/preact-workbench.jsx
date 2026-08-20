import { Fragment, h, render } from "preact";
import { useState } from "preact/hooks";

import { sessionViewModel } from "./session-model.mjs";

function Empty({ text }) {
  return <div class="empty-state">{text}</div>;
}

function PackageCard({ item, actions }) {
  const pending = item.status === "pending";
  const [dragging, setDragging] = useState(false);
  const assets = (item.assets || []).length;
  return (
    <div
      class={`package-card${dragging ? " dragging" : ""}`}
      draggable={pending}
      data-package-id={item.id}
      onDragStart={(event) => {
        if (!pending || event.target.closest?.("button")) {
          event.preventDefault();
          return;
        }
        setDragging(true);
        actions.packageDragStart(item, event);
      }}
      onDragEnd={() => {
        setDragging(false);
        actions.packageDragEnd(item);
      }}
    >
      <div>
        <strong>{item.title || "Untitled file package"}</strong>
        <span class="package-meta">
          {pending ? "Ready to send" : "Delivered"} · {assets} file
          {assets === 1 ? "" : "s"} · {item.source || "Faryo"}
        </span>
      </div>
      {pending && (
        <div class="package-actions">
          <button
            class="mini-btn add-asset"
            type="button"
            onPointerDown={(event) => event.stopPropagation()}
            onClick={(event) => {
              event.stopPropagation();
              actions.addPackageFiles(item);
            }}
          >
            Add files
          </button>
          <button
            class="mini-btn send-package"
            type="button"
            onPointerDown={(event) => event.stopPropagation()}
            onClick={(event) => {
              event.stopPropagation();
              actions.sendPackage(item);
            }}
          >
            Send to…
          </button>
        </div>
      )}
    </div>
  );
}

function LauncherCard({ item, actions }) {
  const [starting, setStarting] = useState(false);
  return (
    <button
      type="button"
      class="session-card launcher-card"
      disabled={starting}
      onClick={async () => {
        if (starting) return;
        setStarting(true);
        try {
          await actions.startLauncher(item);
        } finally {
          setStarting(false);
        }
      }}
    >
      <div>
        <div class="session-title">
          {starting ? `Starting ${item.label}…` : `Start ${item.label}`}
        </div>
        <div class="session-meta">
          {starting ? "Creating session" : "New CLI session"}
        </div>
      </div>
      <div class="arrow">{starting ? "↗" : "›"}</div>
    </button>
  );
}

function SessionCard({ item, routeLabels, actions }) {
  const view = sessionViewModel(item, routeLabels);
  const [dropTarget, setDropTarget] = useState(false);
  const action =
    view.active && item.managed ? (
      <button class="mini-btn close-session" type="button">
        Close
      </button>
    ) : view.lifecycle === "resumable" ? (
      <button class="mini-btn archive-session" type="button">
        Archive
      </button>
    ) : view.lifecycle === "archived" ? (
      <button class="mini-btn restore-session" type="button">
        Restore
      </button>
    ) : (
      <span class="arrow">
        {view.archived || view.lifecycle === "exited" ? "—" : "›"}
      </span>
    );
  return (
    <div
      class={`${view.className}${dropTarget ? " drop-target" : ""}`}
      data-route={item.route}
      data-session={view.targetSession}
      data-agent-session-id={view.agentSessionId}
      data-source={view.source}
      data-state={view.lifecycle}
      title={view.tooltip}
      onClick={(event) => {
        const target = event.target;
        if (target.closest(".close-session"))
          actions.sessionAction(item, "close", event);
        else if (target.closest(".archive-session"))
          actions.sessionAction(item, "archive", event);
        else if (target.closest(".restore-session"))
          actions.sessionAction(item, "restore", event);
        else actions.sessionAction(item, "open", event);
      }}
      onDragOver={(event) => {
        if (
          !actions.draggedPackage() ||
          !view.agentSessionId ||
          !view.canReceive
        )
          return;
        event.preventDefault();
        setDropTarget(true);
      }}
      onDragLeave={() => setDropTarget(false)}
      onDrop={(event) => {
        event.preventDefault();
        setDropTarget(false);
        if (view.canReceive) actions.dropPackage(item, event);
      }}
    >
      <div>
        <div class="session-title">{view.title}</div>
        <div class="session-meta">{view.meta}</div>
      </div>
      <div>{action}</div>
    </div>
  );
}

function List({ items, emptyText, children }) {
  return items.length ? (
    <Fragment>{items.map(children)}</Fragment>
  ) : (
    <Empty text={emptyText} />
  );
}

export function createWorkbenchRenderer(options) {
  const containers = options.containers;
  const actions = options.actions;
  const claimedContainers = new WeakSet();
  function renderInto(vnode, container) {
    if (!claimedContainers.has(container)) {
      container.replaceChildren();
      claimedContainers.add(container);
    }
    render(vnode, container);
  }
  function renderWorkbenchLists(model) {
    renderInto(
      <List
        items={model.packages}
        emptyText="Choose files, then send them to a session."
      >
        {(item) => (
          <PackageCard key={`pkg-${item.id}`} item={item} actions={actions} />
        )}
      </List>,
      containers.packages,
    );
    renderInto(
      <List items={model.launchers} emptyText="No launchers available">
        {(item) => <LauncherCard key={item.id} item={item} actions={actions} />}
      </List>,
      containers.launchers,
    );
    renderInto(
      <List items={model.activeSessions} emptyText="No active agent sessions">
        {(item) => (
          <SessionCard
            key={`active-${item.route}-${item.tmuxSession || item.id}`}
            item={item}
            routeLabels={model.routeLabels}
            actions={actions}
          />
        )}
      </List>,
      containers.activeSessions,
    );
    renderInto(
      <List items={model.sessions} emptyText={model.historyEmptyText}>
        {(item) => (
          <SessionCard
            key={`session-${item.route}-${item.id}`}
            item={item}
            routeLabels={model.routeLabels}
            actions={actions}
          />
        )}
      </List>,
      containers.sessions,
    );
  }
  function renderSessionFixture(item, container) {
    renderInto(
      <SessionCard
        item={item}
        routeLabels={options.routeLabels || {}}
        actions={actions}
      />,
      container,
    );
    return container.firstElementChild;
  }
  function renderError(text) {
    renderInto(<Empty text={text} />, containers.activeSessions);
    renderInto(<Empty text={text} />, containers.sessions);
  }
  return { render: renderWorkbenchLists, renderSessionFixture, renderError };
}

globalThis.FaryoPreactWorkbench = { createWorkbenchRenderer };
