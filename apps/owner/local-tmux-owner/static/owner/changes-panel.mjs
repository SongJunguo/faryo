const CONTROL_IDS = ["detailsChangesBtn", "changesRefreshBtn", "changesLineBtn", "changesSplitBtn"];

export function workspaceSummaryText(summary = {}) {
  return `${Number(summary.files || 0)} files · ${Number(summary.staged || 0)} staged · ${Number(summary.unstaged || 0)} unstaged · ${Number(summary.untracked || 0)} untracked${summary.diffTruncated ? " · diff truncated" : ""}`;
}

export function diffReviewAssetPath(routeBase, path) {
  return `${routeBase || ""}/vendor/diff-review/${path}`;
}

export function createChangesPanelController(options) {
  const view = options.view;
  const document = view.document;
  const element = (id) => document.getElementById(id);
  const panel = element("changesPanel");
  let payload = null;
  let sideBySide = false;
  let assetsPromise = null;

  function setControlsDisabled(disabled) {
    for (const id of CONTROL_IDS) element(id).disabled = disabled;
  }

  function loadAssets() {
    if (view.FaryoDiffReview?.render) return Promise.resolve(view.FaryoDiffReview);
    if (assetsPromise) return assetsPromise;
    assetsPromise = new Promise((resolve, reject) => {
      let pending = 2;
      const done = () => {
        pending -= 1;
        if (pending > 0) return;
        if (view.FaryoDiffReview?.render) resolve(view.FaryoDiffReview);
        else reject(new Error("Diff review assets did not initialize"));
      };
      let stylesheet = element("faryoDiffReviewCss");
      if (!stylesheet) {
        stylesheet = document.createElement("link");
        stylesheet.id = "faryoDiffReviewCss";
        stylesheet.rel = "stylesheet";
        stylesheet.href = diffReviewAssetPath(options.routeBase, "diff2html.min.css?v=3.4.56");
        stylesheet.addEventListener("load", done, { once: true });
        stylesheet.addEventListener("error", () => reject(new Error("Diff review stylesheet failed to load")), { once: true });
        document.head.appendChild(stylesheet);
      } else {
        done();
      }
      let script = element("faryoDiffReviewScript");
      if (!script) {
        script = document.createElement("script");
        script.id = "faryoDiffReviewScript";
        script.src = diffReviewAssetPath(options.routeBase, "diff-review.min.js?v=3.4.56-3.4.14");
        script.addEventListener("load", done, { once: true });
        script.addEventListener("error", () => reject(new Error("Diff review script failed to load")), { once: true });
        document.head.appendChild(script);
      } else {
        done();
      }
    }).catch((error) => {
      assetsPromise = null;
      throw error;
    });
    return assetsPromise;
  }

  function renderFiles(files) {
    const container = element("changesFiles");
    container.replaceChildren();
    for (const item of files || []) {
      const row = document.createElement("div");
      row.className = "changes-file";
      const status = document.createElement("span");
      status.className = "changes-file-status";
      status.textContent = String(item.status || "").trim() || "·";
      const path = document.createElement("code");
      path.textContent = String(item.path || "unknown");
      path.title = path.textContent;
      row.append(status, path);
      container.appendChild(row);
    }
    if (!container.children.length) {
      const empty = document.createElement("div");
      empty.className = "changes-empty";
      empty.textContent = "No changed files";
      container.appendChild(empty);
    }
  }

  async function render() {
    if (!payload) return;
    const summary = payload.summary || {};
    element("changesRepository").textContent = `${payload.repository?.name || "Repository"} · ${payload.repository?.branch || "detached"}`;
    element("changesSummary").textContent = workspaceSummaryText(summary);
    element("detailsChangesCount").textContent = Number(summary.files || 0) ? String(summary.files) : "Clean";
    element("changesLineBtn").classList.toggle("mode-active", !sideBySide);
    element("changesSplitBtn").classList.toggle("mode-active", sideBySide);
    renderFiles(payload.files);
    const target = element("changesDiff");
    if (!String(payload.diff || "").trim()) {
      target.replaceChildren();
      const empty = document.createElement("div");
      empty.className = "changes-empty";
      empty.textContent = summary.untracked
        ? "Untracked files are listed above; Git has no text diff for them yet."
        : "No uncommitted text changes";
      target.appendChild(empty);
      return;
    }
    const renderer = await loadAssets();
    target.innerHTML = renderer.render(payload.diff, { sideBySide });
  }

  async function load() {
    const session = options.getSelectedSession();
    setControlsDisabled(true);
    element("changesDiff").innerHTML = '<div class="changes-empty">Loading workspace changes…</div>';
    try {
      const result = await options.api(`/api/workspace-changes?session=${encodeURIComponent(session)}`);
      if (options.getSelectedSession() !== session) return;
      payload = result;
      await render();
    } catch (error) {
      payload = null;
      element("changesRepository").textContent = "Changes unavailable";
      element("changesSummary").textContent = "Read-only workspace review could not be loaded";
      element("changesDiff").replaceChildren();
      const empty = document.createElement("div");
      empty.className = "changes-empty";
      empty.textContent = options.userErrorMessage(error);
      element("changesDiff").appendChild(empty);
    } finally {
      setControlsDisabled(false);
    }
  }

  function connect() {
    panel.addEventListener("click", (event) => {
      if (event.target.closest("[data-close-panel]")) options.closeSurfacePanels();
    });
    element("detailsChangesBtn").addEventListener("click", () => {
      options.openSurfacePanel(panel, element("detailsBtn"));
      void load();
    });
    element("changesRefreshBtn").addEventListener("click", () => void load());
    element("changesLineBtn").addEventListener("click", () => {
      sideBySide = false;
      render().catch((error) => options.setError(options.userErrorMessage(error)));
    });
    element("changesSplitBtn").addEventListener("click", () => {
      sideBySide = true;
      render().catch((error) => options.setError(options.userErrorMessage(error)));
    });
  }

  return { connect, load, render };
}
