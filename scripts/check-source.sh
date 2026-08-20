#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  scripts/check-source.sh

Runs the maintained source, browser-bundle, and runtime-contract checks. Binary
package builders were removed when this fork became source-deployment only.
USAGE
}

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="${1:-}"
# shellcheck source=runtime-env.sh
source "$ROOT/scripts/runtime-env.sh"

[[ "$TARGET" == "-h" || "$TARGET" == "--help" ]] && { usage; exit 0; }
[[ -z "$TARGET" ]] || { echo "unsupported argument: $TARGET" >&2; usage >&2; exit 2; }

PYTHON_BIN="$(faryo_resolve_python)"
NODE_BIN="$(faryo_resolve_node)"
export FARYO_PYTHON="$PYTHON_BIN" FARYO_NODE_BIN="$NODE_BIN" PYTHONDONTWRITEBYTECODE=1
"$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' || {
  echo "Faryo requires Python 3.11 or newer: $PYTHON_BIN" >&2
  exit 1
}
"$PYTHON_BIN" -c 'import bcrypt, starlette, uvicorn' >/dev/null 2>&1 || {
  echo "Gateway runtime dependencies are missing from: $PYTHON_BIN" >&2
  echo "Install apps/gateway/requirements.txt in the selected environment." >&2
  exit 1
}
"$PYTHON_BIN" - <<'PY'
from importlib.metadata import version

expected = {
    "anyio": "4.14.2",
    "bcrypt": "5.0.0",
    "click": "8.4.2",
    "h11": "0.16.0",
    "idna": "3.19",
    "starlette": "1.6.0",
    "uvicorn": "0.52.4",
}
actual = {name: version(name) for name in expected}
if actual != expected:
    raise SystemExit(f"Gateway runtime dependency drift: {actual}")
PY
"$PYTHON_BIN" -c 'import ruff' >/dev/null 2>&1 || {
  echo "Ruff is missing from: $PYTHON_BIN" >&2
  echo "Install requirements-dev.txt in the selected environment." >&2
  exit 1
}
"$NODE_BIN" -e 'process.exit(Number(process.versions.node.split(".")[0]) >= 20 ? 0 : 1)' || {
  echo "Faryo source checks require Node.js 20 or newer: $NODE_BIN" >&2
  exit 1
}
printf 'runtime: %s · %s\n' \
  "$("$PYTHON_BIN" -c 'import platform; print("Python " + platform.python_version())')" \
  "$("$NODE_BIN" --version)"

release_checks() {
  "$PYTHON_BIN" -m ruff check \
    "$ROOT/apps" \
    "$ROOT/scripts"
  (cd "$ROOT" && PATH="$(dirname "$NODE_BIN"):$PATH" npm run --silent check:lint)
  (cd "$ROOT" && PATH="$(dirname "$NODE_BIN"):$PATH" npm run --silent check:format)
  (cd "$ROOT" && PATH="$(dirname "$NODE_BIN"):$PATH" npm run --silent test:browser-harness)
  (cd "$ROOT" && PATH="$(dirname "$NODE_BIN"):$PATH" npm run --silent check:diff-review)
  (cd "$ROOT" && PATH="$(dirname "$NODE_BIN"):$PATH" npm run --silent test:diff-review)
  bash -n \
    "$ROOT/scripts/check-source.sh" \
    "$ROOT"/scripts/*.sh \
    "$ROOT"/apps/owner/scripts/*.sh \
    "$ROOT"/apps/owner/local-tmux-owner/tests/*.sh \
    "$ROOT"/apps/gateway/scripts/*.sh
  bash "$ROOT/scripts/runtime-env.test.sh"
  "$PYTHON_BIN" -m py_compile \
    "$ROOT/apps/owner/local-tmux-owner/server.py" \
    "$ROOT/apps/owner/local-tmux-owner/attachment_storage.py" \
    "$ROOT/apps/owner/local-tmux-owner/path_policy.py" \
    "$ROOT/apps/owner/local-tmux-owner/tmux_runtime.py" \
    "$ROOT/apps/owner/local-tmux-owner/delivery_store.py" \
    "$ROOT/apps/owner/local-tmux-owner/codex_history.py" \
    "$ROOT/apps/owner/local-tmux-owner/workspace_changes.py" \
    "$ROOT/apps/owner/local-tmux-owner/runtime_diagnostics.py" \
    "$ROOT/apps/owner/local-tmux-owner/tests/owner-archive-roundtrip.py" \
    "$ROOT/apps/gateway/server/server.py" \
    "$ROOT/apps/gateway/server/gateway_security.py" \
    "$ROOT/apps/gateway/server/asgi_app.py" \
    "$ROOT/apps/gateway/scripts/generate-gateway-auth-config.py"
  for js_file in \
    "$ROOT/apps/owner/local-tmux-owner/static/compact-rules-codex.js" \
    "$ROOT/apps/owner/local-tmux-owner/static/event-stream.js" \
    "$ROOT/apps/owner/local-tmux-owner/static/internal-annotations.js" \
    "$ROOT/apps/owner/local-tmux-owner/static/local-file-view.js" \
    "$ROOT/apps/owner/local-tmux-owner/static/stable-blocks.js" \
    "$ROOT/apps/owner/local-tmux-owner/static/question-navigator.js" \
    "$ROOT/apps/owner/local-tmux-owner/static/codex-commands.js" \
    "$ROOT/apps/owner/local-tmux-owner/static/copy-fidelity.js" \
    "$ROOT/apps/owner/local-tmux-owner/static/clipboard-images.js" \
    "$ROOT/apps/owner/local-tmux-owner/static/immersive-mode.js" \
    "$ROOT/apps/owner/local-tmux-owner/static/scroll-surface.js" \
    "$ROOT/apps/owner/local-tmux-owner/static/owner/changes-panel.mjs" \
    "$ROOT/apps/owner/local-tmux-owner/static/vendor/markdown-ast/markdown-ast.min.js" \
    "$ROOT/apps/owner/local-tmux-owner/static/live-scroll.js" \
    "$ROOT/apps/shared/static/appearance.js" \
    "$ROOT/apps/owner/local-tmux-owner/static/app.js" \
    "$ROOT/apps/gateway/server/static/workbench.js"
  do
    "$NODE_BIN" --check "$js_file"
  done
  while IFS= read -r js_file; do
    "$NODE_BIN" --check "$js_file"
  done < <(find "$ROOT/apps/owner/local-tmux-owner/static/vendor/markdown-ast/highlight" -type f -name '*.js' -print | sort)
  "$NODE_BIN" --check "$ROOT/apps/owner/local-tmux-owner/tests/browser-katex-smoke.mjs"
  "$NODE_BIN" --check "$ROOT/apps/owner/local-tmux-owner/tests/browser-immersive-smoke.mjs"
  "$NODE_BIN" --check "$ROOT/apps/owner/local-tmux-owner/tests/browser-workspace-changes-smoke.mjs"
  "$NODE_BIN" --check "$ROOT/apps/gateway/server/tests/browser-workbench-smoke.mjs"
  "$NODE_BIN" "$ROOT/apps/owner/local-tmux-owner/tests/markdown-ast-bundle.test.js"
  "$NODE_BIN" "$ROOT/apps/owner/local-tmux-owner/tests/internal-annotations.test.js"
  "$NODE_BIN" "$ROOT/apps/owner/local-tmux-owner/tests/event-stream.test.js"
  "$NODE_BIN" "$ROOT/apps/owner/local-tmux-owner/tests/stable-blocks.test.js"
  "$NODE_BIN" "$ROOT/apps/owner/local-tmux-owner/tests/question-navigator.test.js"
  "$NODE_BIN" "$ROOT/apps/owner/local-tmux-owner/tests/live-scroll.test.js"
  "$NODE_BIN" "$ROOT/apps/owner/local-tmux-owner/tests/compact-rules-codex.test.js"
  "$NODE_BIN" "$ROOT/apps/owner/local-tmux-owner/tests/codex-commands.test.js"
  "$NODE_BIN" "$ROOT/apps/owner/local-tmux-owner/tests/copy-fidelity.test.js"
  "$NODE_BIN" "$ROOT/apps/owner/local-tmux-owner/tests/clipboard-images.test.js"
  "$NODE_BIN" "$ROOT/apps/owner/local-tmux-owner/tests/immersive-mode.test.js"
  "$NODE_BIN" "$ROOT/apps/owner/local-tmux-owner/tests/scroll-surface.test.js"
  "$NODE_BIN" --test "$ROOT/apps/owner/local-tmux-owner/tests/changes-panel.test.mjs"
  "$NODE_BIN" --test "$ROOT/apps/owner/local-tmux-owner/tests/terminal-delivery-receiver.test.mjs"
  "$PYTHON_BIN" -m unittest discover -s "$ROOT/apps/owner/local-tmux-owner/tests" -p 'test_*.py'
  "$PYTHON_BIN" -m unittest discover -s "$ROOT/apps/gateway/server/tests" -p 'test_*.py'
  "$PYTHON_BIN" - "$ROOT" <<'PY'
from pathlib import Path
import json
import re
import sys
root = Path(sys.argv[1])

def reject_duplicate_json_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise AssertionError(f"duplicate JSON key: {key}")
        result[key] = value
    return result

json.loads(
    (root / "package.json").read_text(encoding="utf-8"),
    object_pairs_hook=reject_duplicate_json_keys,
)
index = (root / "apps/owner/local-tmux-owner/static/index.html").read_text(encoding="utf-8")
owner_server = (root / "apps/owner/local-tmux-owner/server.py").read_text(encoding="utf-8")
workspace_changes_source = (root / "apps/owner/local-tmux-owner/workspace_changes.py").read_text(encoding="utf-8")
runtime_diagnostics_source = (root / "apps/owner/local-tmux-owner/runtime_diagnostics.py").read_text(encoding="utf-8")
gateway = (root / "apps/gateway/server/server.py").read_text(encoding="utf-8")
gateway_workbench = (root / "apps/gateway/server/static/workbench.js").read_text(encoding="utf-8")
gateway_ui = gateway + "\n" + gateway_workbench
ci_workflow = (root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
release_workflow = (root / ".github/workflows/release.yml").read_text(encoding="utf-8")
check_script = (root / "scripts/check-source.sh").read_text(encoding="utf-8")
assert "pull_request:" in ci_workflow and "branches: [main]" in ci_workflow, "source CI must cover PR and main"
assert "scripts/check-source.sh" in ci_workflow and "scripts/check-source.sh" in release_workflow, "CI and release must share source checks"
assert "package-client.sh" not in release_workflow, "retired package workflow must not return"
assert "faryo_${version}_all.deb" not in release_workflow and "macos.tar.gz" not in release_workflow, "release must remain source-only"
assert "apps/gateway/server/tests" in check_script, "canonical checks must include Gateway tests"
assert (root / "package-lock.json").is_file(), "development JavaScript dependencies must be locked"
assert (root / "requirements-dev.txt").is_file(), "development Python dependencies must be pinned"
assert "faryo_resolve_python" in check_script and "faryo_resolve_node" in check_script, "canonical checks must resolve runtimes"
python_runtime_tests = (
    "start-codex-runtime.sh",
    "browser-workspace-changes.sh",
    "browser-session-send-isolation.sh",
    "browser-live-selection.sh",
    "browser-full-history.sh",
    "browser-protected-resources.sh",
    "browser-delivery-matrix.sh",
    "send-restart-idempotency.sh",
)
test_script_root = root / "apps/owner/local-tmux-owner/tests"
for name in python_runtime_tests:
    source = (test_script_root / name).read_text(encoding="utf-8")
    assert "scripts/runtime-env.sh" in source and "faryo_resolve_python" in source, f"{name} bypasses shared Python discovery"
for name in (
    "browser-workspace-changes.sh",
    "browser-session-send-isolation.sh",
    "browser-live-selection.sh",
    "browser-full-history.sh",
    "browser-protected-resources.sh",
    "browser-delivery-matrix.sh",
    "send-restart-idempotency.sh",
):
    assert "faryo_resolve_node" in (test_script_root / name).read_text(encoding="utf-8"), f"{name} bypasses shared Node discovery"
command_inventory_source = (test_script_root / "codex-command-inventory.sh").read_text(encoding="utf-8")
assert "faryo_resolve_codex" in command_inventory_source and "faryo_resolve_node" in command_inventory_source, "Codex inventory must use shared runtime discovery"
assert 'id="historySearchInput"' in gateway and 'data-history-period="7d"' in gateway, "Gateway must expose metadata history search"
assert "agent_history_text_matches" in owner_server and "codex_conversation_history_page" not in owner_server[owner_server.index("def codex_history_page("):owner_server.index("def codex_history_items(")], "session search must not scan conversation history"
assert "safe_path = urlparse(self.path).path" in owner_server, "Owner logs must omit private query strings"
assert "append_control_audit" in gateway and 'id="securityActivity"' in gateway, "Gateway must expose body-free control auditing"
assert "/api/session-history/archive" in gateway and "/api/session-history/unarchive" in gateway, "Gateway must expose reversible history lifecycle controls"
assert "/api/session-history/delete" not in gateway_ui and '"thread/delete"' not in owner_server, "Faryo must not expose hard thread deletion"
assert 'class="brand" href="/" aria-label="Faryo home"' in gateway, "Gateway brand must remain on the session home"
for retired_marker in ("/projects", "/api/project-workbench", "/api/faryo/start", "/api/faryo/dispatch", "/api/workorder"):
    assert retired_marker not in gateway_ui and retired_marker not in owner_server, f"retired project orchestration route returned: {retired_marker}"
assert "PORTAL_CSS" not in gateway and "PORTAL_JS_TEMPLATE" not in gateway, "Gateway portal assets must stay external"
assert 'href="/workbench.css?v=faryo-gateway-2"' in gateway and 'src="/workbench.js?v=faryo-gateway-2"' in gateway, "Gateway must load versioned external workbench assets"
assert 'id="faryoRouteLabels" type="application/json"' in gateway, "Gateway route labels must use the nonce-protected JSON bootstrap"
assert 'id="attentionCenter"' in gateway and 'id="notificationControl"' in gateway, "Gateway must expose body-free attention controls"
assert "processAttention" in gateway_workbench and "A session completed or needs input." in gateway_workbench, "Gateway attention must use generic notification text"
assert '"starting", "running", "waiting", "exited", "desktop", "resumable"' in gateway, "Gateway must expose explicit session lifecycle states"
assert "compact-rules-codex.js" in index, "index.html must load compact-rules-codex.js"
assert "compact-rules-codex.js" in gateway, "gateway must allow compact-rules-codex.js"
assert "compact-rules-claude.js" not in index, "retired Claude rules must not return to the production page"
assert "compact-rules-claude.js" not in gateway, "Gateway must not proxy retired Claude rules"
assert 'NEW_SESSION_COMMANDS = {"codex"}' in gateway, "Gateway must expose only the maintained Codex launcher"
assert "stable-blocks.js" in index, "index.html must load stable-blocks.js"
assert "stable-blocks.js" in gateway, "gateway must allow stable-blocks.js"
assert "question-navigator.js" in index, "index.html must load question-navigator.js"
assert "question-navigator.js" in gateway, "gateway must allow question-navigator.js"
assert "codex-commands.js" in index and "codex-commands.js" in gateway, "Codex command inventory must be loaded and proxied"
assert "copy-fidelity.js" in index and "copy-fidelity.js" in gateway, "copy fidelity must be loaded and proxied"
assert "clipboard-images.js" in index and "clipboard-images.js" in gateway, "clipboard image paste must be loaded and proxied"
assert "immersive-mode.js" in index and "immersive-mode.js" in gateway, "immersive display controller must be loaded and proxied"
assert "scroll-surface.js" in index and "scroll-surface.js" in gateway, "mobile document scroll adapter must be loaded and proxied"
assert 'rel="manifest" href="/manifest.json"' in index, "every maintained PWA page must reference the root manifest"
assert 'id="immersiveExitBtn"' in index and 'id="detailsFullscreenBtn"' in index, "fullscreen must expose explicit enter and exit controls"
assert 'id="changesPanel"' in index and 'id="detailsChangesBtn"' in index, "Owner must expose read-only workspace changes"
assert "internal-annotations.js" in index, "index.html must load internal annotation formatting"
assert "internal-annotations.js" in gateway, "gateway must proxy internal annotation formatting"
assert "event-stream.js" in index, "index.html must load the authenticated event-stream parser"
assert "event-stream.js" in gateway, "gateway must proxy the authenticated event-stream parser"
assert "local-file-view.js" in gateway, "gateway must proxy the CSP-safe local file controls"
assert "vendor/markdown-ast/markdown-ast.min.js" in index, "index.html must load the AST Markdown bundle"
assert re.search(r'<script\s+type="module"\s+src="vendor/markdown-ast/highlight/highlight\.js\?', index), "index.html must load the Shiki module locally"
assert '"vendor/markdown-ast/"' in gateway, "gateway must proxy AST Markdown assets"
assert "live-scroll.js" in index, "index.html must load live-scroll.js"
assert "live-scroll.js" in gateway, "gateway must allow live-scroll.js"
assert "cdn.jsdelivr.net/npm/katex" not in index, "KaTeX must not require an external CDN"
assert 'vendor/katex/katex.min.css?v=0.18.4' in index, "index.html must load local KaTeX CSS"
assert '"vendor/katex/"' in gateway, "gateway must proxy local KaTeX assets"
for relative in (
    "katex.min.css",
    "fonts/KaTeX_Main-Regular.woff2",
    "LICENSE",
):
    assert (root / "apps/owner/local-tmux-owner/static/vendor/katex" / relative).is_file(), f"missing vendored KaTeX asset: {relative}"
assert "cdn.jsdelivr.net" not in index, "Markdown and math must not require an external CDN"
assert '"vendor/diff-review/"' in gateway, "Gateway must proxy local diff-review assets"
assert '"owner/"' in gateway, "Gateway must proxy Owner native ES modules"
diff_review_root = root / "apps/owner/local-tmux-owner/static/vendor/diff-review"
diff_review_manifest = json.loads((diff_review_root / "manifest.json").read_text(encoding="utf-8"))
assert diff_review_manifest.get("schemaVersion") == 1, "unsupported diff-review manifest"
assert diff_review_manifest.get("packages") == {"diff2html": "3.4.56", "dompurify": "3.4.14"}, "diff-review versions drifted"
for relative in diff_review_manifest.get("assets", {}):
    assert (diff_review_root / relative).is_file(), f"missing diff-review asset: {relative}"
assert "vendor/markdown-it/" not in index, "legacy markdown-it must not remain in the production page"
assert "math-render.js" not in index, "legacy math DOM post-processing must not remain in the production page"
for relative in ("markdown-ast.min.js", "THIRD_PARTY_NOTICES.md", "THIRD_PARTY_LICENSES.txt", "highlight/highlight.js", "highlight/manifest.json"):
    assert (root / "apps/owner/local-tmux-owner/static/vendor/markdown-ast" / relative).is_file(), f"missing AST Markdown asset: {relative}"
asset_root = root / "apps/owner/local-tmux-owner/static/vendor/markdown-ast"
manifest = json.loads((asset_root / "highlight/manifest.json").read_text(encoding="utf-8"))
assert manifest.get("schemaVersion") == 1, "unsupported Shiki asset manifest"
assert manifest.get("entry") == "highlight/highlight.js", "unexpected Shiki entry"
manifest_paths = [item.get("path", "") for item in manifest.get("files", [])]
assert len(manifest_paths) == len(set(manifest_paths)) and manifest_paths, "Shiki manifest paths must be non-empty and unique"
for relative in manifest_paths:
    path = Path(relative)
    assert path.parts and path.parts[0] == "highlight" and ".." not in path.parts and not path.is_absolute(), f"unsafe Shiki manifest path: {relative}"
    assert (asset_root / path).is_file(), f"missing Shiki chunk: {relative}"
for grammar in ("python", "latex", "lean", "matlab", "markdown", "yaml", "html", "css", "cpp", "c", "rust", "go", "java", "sql"):
    assert any(Path(relative).name.startswith(grammar + "-") for relative in manifest_paths), f"missing lazy Shiki grammar: {grammar}"
assert (root / "tools/markdown-engine/package-lock.json").is_file(), "AST Markdown build must have a lockfile"
app = (root / "apps/owner/local-tmux-owner/static/app.js").read_text(encoding="utf-8")
changes_panel_source = (root / "apps/owner/local-tmux-owner/static/owner/changes-panel.mjs").read_text(encoding="utf-8")
assert 'import("./owner/changes-panel.mjs?v=faryo-owner-changes-1")' in app, "Owner Changes must use its native ES module"
assert "/api/workspace-changes" in owner_server and "/api/workspace-changes" in changes_panel_source, "workspace changes must use the scoped read-only Owner API"
assert "/api/capabilities" in owner_server and "/api/diagnostics" in owner_server and "loadOwnerCapabilities" in app, "Owner must expose versioned redacted diagnostics"
assert '"pendingQueueManagement": False' in runtime_diagnostics_source and '"pendingQueue": "unsupported"' in runtime_diagnostics_source, "Faryo must not overclaim editable Codex queues"
assert "shell=True" not in workspace_changes_source and "--no-ext-diff" in workspace_changes_source and "--no-textconv" in workspace_changes_source, "workspace diff must remain fixed and read-only"
stable_blocks_source = (root / "apps/owner/local-tmux-owner/static/stable-blocks.js").read_text(encoding="utf-8")
assert "stableBlocks.reconcile(output, models, createNode)" in app, "Compact Chat must reconcile stable DOM blocks"
assert "headers['X-Owner-Token'] = ownerToken" in app, "Owner API calls must include the token header"
assert "sessionStorage.setItem(OWNER_TOKEN_STORAGE_KEY" in app, "direct Owner auth must survive same-tab refresh without URL persistence"
assert "new EventSource" not in app, "Owner streaming must support the authentication header"
assert "token=${encodeURIComponent(ownerToken)}" not in app, "Owner streaming must not place the token in request URLs"
assert "authenticatedApiPath" not in app, "local resource DOM URLs must not append the Owner token"
assert "fetchProtectedResource" in app, "direct Owner resources must use authenticated fetches"
assert "data-faryo-fetch-href" in app, "protected file links must use deferred authenticated fetches"
assert "data-faryo-fetch-src" in app, "protected images must use deferred authenticated fetches"
assert "target.searchParams.delete('token')" in app, "protected resource fetches must strip query tokens"
assert 'id="quotaText"' in index and 'id="detailsQuota"' in index, "Owner must expose weekly quota in header and details"
assert "Week ${remaining}% left" in app, "Owner must label weekly quota as remaining allowance"
assert "contextWindowSource === 'agent-reported'" in app, "Owner must distinguish reported context windows from fallbacks"
assert "usedTokens" in app and "contextWindow" in app, "Owner must show actual context token counts"
assert "sendWithDeliveryRecovery" in app, "Owner must reconcile ambiguous send responses idempotently"
assert "button.textContent = '⧉'" in app, "confirmed output copy button must remain unchanged"
assert "copyFidelity?.handleCopy(event)" in app, "Compact Chat selections must use source-faithful copy"
assert "promptInput.addEventListener('paste'" in app, "Owner composer must handle user-triggered image paste"
assert "navigator.clipboard.read(" not in app, "Owner must not read the clipboard outside a paste event"
assert "lastCompactCapture" in app and "lastFullCapture" in app and "renderModeLoading" in app, "Chat and Raw must keep isolated capture caches"
assert "renderOutput(lastCapture)" not in app, "compact callbacks must not replay a Raw capture"
assert 'id="approveSmallBtn"' in index and '>Enter Choose</button>' in index and 'Codex menu' in index, "terminal selection controls must explain their TUI scope"
assert "CODEX_LIVE_TAIL_LINES = 180" in owner_server, "Live tmux must keep the bounded long tail"
assert "faryoTransient" in stable_blocks_source and "selectionInsideLivePanel" in app and "compact-live-copy" in app, "Live tmux DOM, selection, and copy must remain stable"
assert "compactOutputSources" not in app and "dataset.sourceIndex" not in app, "retired copy source indexing must not return"
appearance = (root / "apps/shared/static/appearance.css").read_text(encoding="utf-8")
assert "--bg: #0F1115" in appearance and "--accent: #7188FF" in appearance, "shared dark palette must match Owner"
assert "--bg: #F6F7F9" in appearance and "--accent: #5369E7" in appearance, "shared light palette must match Owner"
assert "Files to session" in gateway and "Send to…" in gateway_workbench, "Gateway must expose explicit file-to-session controls"
assert "No handoff package" not in gateway_ui, "Gateway must not expose unexplained handoff copy"
for retired in (
    "apps/owner/local-tmux-owner/static/compact-rules-claude.js",
    "apps/owner/scripts/claude-session-stamp.sh",
    "scripts/package-client.sh",
    "scripts/install-macos-owner.sh",
    "scripts/status-runtime.sh",
    "deploy/launchd/dev.faryo.owner.keepalive.plist",
    "docs/assets/ui-targets",
    "docs/launch/faryo-1.0.0.md",
    "RELEASE",
    "apps/gateway/RELEASE",
    "apps/owner/local-tmux-owner/static/pet/pet-carrying.png",
    "apps/owner/local-tmux-owner/static/pet/pet-idle.png",
    "apps/owner/local-tmux-owner/static/pet/pet-offline.png",
    "apps/owner/local-tmux-owner/static/pet/pet-resting.png",
    "apps/owner/local-tmux-owner/static/pet/pet-working.png",
    "apps/gateway/server/static/projects.html",
    "apps/gateway/server/static/projects.css",
    "apps/gateway/server/static/projects.js",
    "apps/gateway/server/faryo_profile.md",
    "apps/gateway/server/templates/workorder.md",
    "apps/owner/local-tmux-owner/workbench_state.py",
    "apps/owner/scripts/sync-project-workbench.sh",
    "apps/shared/pd_state.py",
):
    assert not (root / retired).exists(), f"retired source returned: {retired}"
PY
}

release_checks
