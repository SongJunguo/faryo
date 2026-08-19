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
"$PYTHON_BIN" -c 'import bcrypt' >/dev/null 2>&1 || {
  echo "Gateway dependency bcrypt is missing from: $PYTHON_BIN" >&2
  echo "Install apps/gateway/requirements.txt in the selected environment." >&2
  exit 1
}
"$NODE_BIN" -e 'process.exit(Number(process.versions.node.split(".")[0]) >= 20 ? 0 : 1)' || {
  echo "Faryo source checks require Node.js 20 or newer: $NODE_BIN" >&2
  exit 1
}
printf 'runtime: %s · %s\n' \
  "$("$PYTHON_BIN" -c 'import platform; print("Python " + platform.python_version())')" \
  "$("$NODE_BIN" --version)"

WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/faryo-check.XXXXXX")"
trap 'rm -rf "$WORK_DIR"' EXIT

release_checks() {
  bash -n \
    "$ROOT/scripts/check-source.sh" \
    "$ROOT"/scripts/*.sh \
    "$ROOT"/apps/owner/scripts/*.sh \
    "$ROOT"/apps/owner/local-tmux-owner/tests/*.sh \
    "$ROOT"/apps/gateway/scripts/*.sh
  bash "$ROOT/scripts/runtime-env.test.sh"
  "$PYTHON_BIN" -m py_compile \
    "$ROOT/apps/shared/pd_state.py" \
    "$ROOT/apps/owner/local-tmux-owner/server.py" \
    "$ROOT/apps/gateway/server/server.py" \
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
    "$ROOT/apps/owner/local-tmux-owner/static/vendor/markdown-ast/markdown-ast.min.js" \
    "$ROOT/apps/owner/local-tmux-owner/static/live-scroll.js" \
    "$ROOT/apps/shared/static/appearance.js" \
    "$ROOT/apps/owner/local-tmux-owner/static/app.js" \
    "$ROOT/apps/gateway/server/static/projects.js"
  do
    "$NODE_BIN" --check "$js_file"
  done
  while IFS= read -r js_file; do
    "$NODE_BIN" --check "$js_file"
  done < <(find "$ROOT/apps/owner/local-tmux-owner/static/vendor/markdown-ast/highlight" -type f -name '*.js' -print | sort)
  "$NODE_BIN" --check "$ROOT/apps/owner/local-tmux-owner/tests/browser-katex-smoke.mjs"
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
  "$NODE_BIN" --test "$ROOT/apps/owner/local-tmux-owner/tests/terminal-delivery-receiver.test.mjs"
  "$PYTHON_BIN" -m unittest discover -s "$ROOT/apps/owner/local-tmux-owner/tests" -p 'test_*.py'
  "$PYTHON_BIN" -m unittest discover -s "$ROOT/apps/gateway/server/tests" -p 'test_*.py'
  "$PYTHON_BIN" - "$ROOT" <<'PY'
from pathlib import Path
import json
import re
import sys
root = Path(sys.argv[1])
index = (root / "apps/owner/local-tmux-owner/static/index.html").read_text(encoding="utf-8")
owner_server = (root / "apps/owner/local-tmux-owner/server.py").read_text(encoding="utf-8")
gateway = (root / "apps/gateway/server/server.py").read_text(encoding="utf-8")
ci_workflow = (root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
release_workflow = (root / ".github/workflows/release.yml").read_text(encoding="utf-8")
check_script = (root / "scripts/check-source.sh").read_text(encoding="utf-8")
assert "pull_request:" in ci_workflow and "branches: [main]" in ci_workflow, "source CI must cover PR and main"
assert "scripts/check-source.sh" in ci_workflow and "scripts/check-source.sh" in release_workflow, "CI and release must share source checks"
assert "package-client.sh" not in release_workflow, "retired package workflow must not return"
assert "faryo_${version}_all.deb" not in release_workflow and "macos.tar.gz" not in release_workflow, "release must remain source-only"
assert "apps/gateway/server/tests" in check_script, "canonical checks must include Gateway tests"
assert "faryo_resolve_python" in check_script and "faryo_resolve_node" in check_script, "canonical checks must resolve runtimes"
assert 'id="historySearchInput"' in gateway and 'data-history-period="7d"' in gateway, "Gateway must expose metadata history search"
assert "agent_history_text_matches" in owner_server and "codex_conversation_history_page" not in owner_server[owner_server.index("def codex_history_page("):owner_server.index("def codex_history_items(")], "session search must not scan conversation history"
assert "safe_path = urlparse(self.path).path" in owner_server, "Owner logs must omit private query strings"
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
assert "compactOutputSources" not in app and "dataset.sourceIndex" not in app, "retired copy source indexing must not return"
appearance = (root / "apps/shared/static/appearance.css").read_text(encoding="utf-8")
assert "--bg: #0F1115" in appearance and "--accent: #7188FF" in appearance, "shared dark palette must match Owner"
assert "--bg: #F6F7F9" in appearance and "--accent: #5369E7" in appearance, "shared light palette must match Owner"
assert "Files to session" in gateway and "Send to…" in gateway, "Gateway must expose explicit file-to-session controls"
assert "No handoff package" not in gateway, "Gateway must not expose unexplained handoff copy"
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
):
    assert not (root / retired).exists(), f"retired source returned: {retired}"
PY
  local portal_check="$WORK_DIR/faryo-portal-check.js"
  "$PYTHON_BIN" - "$ROOT" "$portal_check" <<'PY'
from pathlib import Path
import sys
root = Path(sys.argv[1])
out = Path(sys.argv[2])
source = (root / "apps/gateway/server/server.py").read_text(encoding="utf-8")
start = source.index('PORTAL_JS_TEMPLATE = """') + len('PORTAL_JS_TEMPLATE = """')
end = source.index('"""', start)
out.write_text(source[start:end].replace("__LABELS_JS__", "{}"), encoding="utf-8")
PY
  "$NODE_BIN" --check "$portal_check"
}

release_checks
