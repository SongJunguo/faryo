#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  scripts/package-client.sh check
  scripts/package-client.sh deb
  scripts/package-client.sh macos-tar
  scripts/package-client.sh release

Builds endpoint-side Faryo packages. The client package is named faryo and
intentionally excludes the gateway server.

Targets:
  check    Run release syntax checks used by CI.
  deb      Build dist/faryo_<version>_<arch>.deb.
  macos-tar Build dist/faryo_<version>_macos.tar.gz.
  release  Run checks, build endpoint packages, and write dist/SHA256SUMS.

Environment:
  FARYO_PACKAGE_VERSION  Override version, defaults to apps/owner/RELEASE.
  FARYO_PACKAGE_OUT      Output directory, defaults to dist/.
  FARYO_DEB_ARCH         Debian architecture, defaults to all.
USAGE
}

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="${1:-}"
PACKAGE="faryo"
VERSION="${FARYO_PACKAGE_VERSION:-$(awk -F= '$1 == "version" {print $2}' "$ROOT/apps/owner/RELEASE" | sed 's/^v//')}"
OUT_DIR="${FARYO_PACKAGE_OUT:-$ROOT/dist}"

[[ "$TARGET" == "-h" || "$TARGET" == "--help" || -z "$TARGET" ]] && { usage; exit 0; }
if [[ -z "$VERSION" || "$VERSION" == *[!0-9A-Za-z.+:~_-]* ]]; then
  echo "invalid package version: $VERSION" >&2
  exit 2
fi

WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/faryo-package.XXXXXX")"
trap 'rm -rf "$WORK_DIR"' EXIT

release_checks() {
  bash -n \
    "$ROOT/scripts/package-client.sh" \
    "$ROOT"/scripts/*.sh \
    "$ROOT"/apps/owner/scripts/*.sh \
    "$ROOT"/apps/owner/local-tmux-owner/tests/*.sh \
    "$ROOT"/apps/gateway/scripts/*.sh
  python3 -m py_compile \
    "$ROOT/apps/shared/pd_state.py" \
    "$ROOT/apps/owner/local-tmux-owner/server.py" \
    "$ROOT/apps/gateway/server/server.py" \
    "$ROOT/apps/gateway/scripts/generate-gateway-auth-config.py"
  for js_file in \
    "$ROOT/apps/owner/local-tmux-owner/static/compact-rules-codex.js" \
    "$ROOT/apps/owner/local-tmux-owner/static/compact-rules-claude.js" \
    "$ROOT/apps/owner/local-tmux-owner/static/stable-blocks.js" \
    "$ROOT/apps/owner/local-tmux-owner/static/vendor/markdown-ast/markdown-ast.min.js" \
    "$ROOT/apps/owner/local-tmux-owner/static/live-scroll.js" \
    "$ROOT/apps/shared/static/appearance.js" \
    "$ROOT/apps/owner/local-tmux-owner/static/app.js" \
    "$ROOT/apps/gateway/server/static/projects.js"
  do
    node --check "$js_file"
  done
  while IFS= read -r js_file; do
    node --check "$js_file"
  done < <(find "$ROOT/apps/owner/local-tmux-owner/static/vendor/markdown-ast/highlight" -type f -name '*.js' -print | sort)
  node --check "$ROOT/apps/owner/local-tmux-owner/tests/browser-katex-smoke.mjs"
  node --check "$ROOT/apps/gateway/server/tests/browser-workbench-smoke.mjs"
  node "$ROOT/apps/owner/local-tmux-owner/tests/markdown-ast-bundle.test.js"
  node "$ROOT/apps/owner/local-tmux-owner/tests/stable-blocks.test.js"
  node "$ROOT/apps/owner/local-tmux-owner/tests/live-scroll.test.js"
  node "$ROOT/apps/owner/local-tmux-owner/tests/compact-rules-codex.test.js"
  node --test "$ROOT/apps/owner/local-tmux-owner/tests/terminal-delivery-receiver.test.mjs"
  python3 -m unittest discover -s "$ROOT/apps/owner/local-tmux-owner/tests" -p 'test_*.py'
  python3 - "$ROOT" <<'PY'
from pathlib import Path
import json
import plistlib
import re
import sys
root = Path(sys.argv[1])
index = (root / "apps/owner/local-tmux-owner/static/index.html").read_text(encoding="utf-8")
gateway = (root / "apps/gateway/server/server.py").read_text(encoding="utf-8")
assert "compact-rules-codex.js" in index, "index.html must load compact-rules-codex.js"
assert "compact-rules-claude.js" in index, "index.html must load compact-rules-claude.js"
assert "compact-rules-codex.js" in gateway, "gateway must allow compact-rules-codex.js"
assert "compact-rules-claude.js" in gateway, "gateway must allow compact-rules-claude.js"
assert "stable-blocks.js" in index, "index.html must load stable-blocks.js"
assert "stable-blocks.js" in gateway, "gateway must allow stable-blocks.js"
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
assert "next.searchParams.set('token', ownerToken)" in app, "session switches must preserve direct Owner auth"
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
appearance = (root / "apps/shared/static/appearance.css").read_text(encoding="utf-8")
assert "--bg: #0F1115" in appearance and "--accent: #7188FF" in appearance, "shared dark palette must match Owner"
assert "--bg: #F6F7F9" in appearance and "--accent: #5369E7" in appearance, "shared light palette must match Owner"
assert "Files to session" in gateway and "Send to…" in gateway, "Gateway must expose explicit file-to-session controls"
assert "No handoff package" not in gateway, "Gateway must not expose unexplained handoff copy"
with (root / "deploy/launchd/dev.faryo.owner.keepalive.plist").open("rb") as fh:
    plistlib.load(fh)
PY
  local portal_check="$WORK_DIR/faryo-portal-check.js"
  python3 - "$ROOT" "$portal_check" <<'PY'
from pathlib import Path
import sys
root = Path(sys.argv[1])
out = Path(sys.argv[2])
source = (root / "apps/gateway/server/server.py").read_text(encoding="utf-8")
start = source.index('PORTAL_JS_TEMPLATE = """') + len('PORTAL_JS_TEMPLATE = """')
end = source.index('"""', start)
out.write_text(source[start:end].replace("__LABELS_JS__", "{}"), encoding="utf-8")
PY
  node --check "$portal_check"
}

stage_client_payload() {
  local dest="$1"
  install -d "$dest/opt/faryo/apps"
  rsync -a --exclude='__pycache__/' --exclude='*.pyc' "$ROOT/apps/shared/" "$dest/opt/faryo/apps/shared/"
  install -m 0644 "$ROOT/LICENSE" "$dest/opt/faryo/LICENSE"
  rsync -a \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
    --exclude='.pytest_cache/' \
    --exclude='.agents/' \
    --exclude='.codex/' \
    --exclude='.gitignore' \
    --exclude='config/faryo.env' \
    --exclude='config/.gitignore' \
    --exclude='state/' \
    "$ROOT/apps/owner/" "$dest/opt/faryo/apps/owner/"
}

assert_no_gateway_payload() {
  local path="$1"
  if find "$path" \( -type f -o -type l \) -print | grep -E '/apps/gateway/|faryo-gateway' >/dev/null; then
    echo "client package contains gateway files" >&2
    return 1
  fi
}

build_deb() {
  local arch="${FARYO_DEB_ARCH:-all}"
  local pkg_root="$WORK_DIR/${PACKAGE}_${VERSION}_${arch}"
  install -d "$pkg_root/DEBIAN" "$pkg_root/usr/lib/systemd/user" "$pkg_root/usr/share/doc/faryo" "$OUT_DIR"
  stage_client_payload "$pkg_root"
  install -m 0644 "$ROOT/LICENSE" "$pkg_root/usr/share/doc/faryo/copyright"
  sed \
    -e 's|@FARYO_ROOT@|/opt/faryo|g' \
    -e 's|@FARYO_HOME@|%h/.faryo|g' \
    "$ROOT/deploy/user-systemd/faryo-owner-keepalive.service" \
    > "$pkg_root/usr/lib/systemd/user/faryo-owner-keepalive.service"
  install -m 0644 "$ROOT/deploy/user-systemd/faryo-owner-keepalive.timer" "$pkg_root/usr/lib/systemd/user/faryo-owner-keepalive.timer"
  assert_no_gateway_payload "$pkg_root"

  cat > "$pkg_root/DEBIAN/control" <<CONTROL
Package: $PACKAGE
Version: $VERSION
Section: utils
Priority: optional
Architecture: $arch
Maintainer: Faryo Local <faryo-local@localhost>
Depends: bash, python3, tmux, curl, zsh
Recommends: git, openssh-client
Description: Faryo endpoint runtime
 Local tmux-backed endpoint runtime for Faryo.
 This client package intentionally excludes the gateway server.
CONTROL

  local deb="$OUT_DIR/${PACKAGE}_${VERSION}_${arch}.deb"
  dpkg-deb --root-owner-group --build "$pkg_root" "$deb" >/dev/null
  if dpkg-deb -c "$deb" | grep -E '/apps/gateway/|faryo-gateway' >/dev/null; then
    rm -f "$deb"
    echo "client package contains gateway files" >&2
    return 1
  fi
  printf '%s\n' "$deb"
}

build_macos_tar() {
  local payload="${PACKAGE}_${VERSION}_macos"
  local pkg_root="$WORK_DIR/$payload"
  install -d "$pkg_root/apps" "$pkg_root/scripts" "$pkg_root/deploy/launchd" "$OUT_DIR"
  rsync -a --exclude='__pycache__/' --exclude='*.pyc' "$ROOT/apps/shared/" "$pkg_root/apps/shared/"
  rsync -a \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
    --exclude='.pytest_cache/' \
    --exclude='.agents/' \
    --exclude='.codex/' \
    --exclude='.gitignore' \
    --exclude='config/faryo.env' \
    --exclude='config/.gitignore' \
    --exclude='state/' \
    "$ROOT/apps/owner/" "$pkg_root/apps/owner/"
  install -m 0755 "$ROOT/scripts/install-macos-owner.sh" "$pkg_root/scripts/install-macos-owner.sh"
  install -m 0644 "$ROOT/deploy/launchd/dev.faryo.owner.keepalive.plist" "$pkg_root/deploy/launchd/dev.faryo.owner.keepalive.plist"
  install -m 0644 "$ROOT/README.md" "$pkg_root/README.md"
  install -m 0644 "$ROOT/LICENSE" "$pkg_root/LICENSE"
  install -m 0644 "$ROOT/SECURITY.md" "$pkg_root/SECURITY.md"
  install -m 0644 "$ROOT/CONTRIBUTING.md" "$pkg_root/CONTRIBUTING.md"
  install -m 0644 "$ROOT/RELEASE" "$pkg_root/RELEASE"

  local tarball="$OUT_DIR/${PACKAGE}_${VERSION}_macos.tar.gz"
  tar -C "$WORK_DIR" -czf "$tarball" "$payload"
  printf '%s\n' "$tarball"
}

build_release() {
  release_checks
  local deb
  local macos_tar
  deb="$(build_deb)"
  macos_tar="$(build_macos_tar)"
  dpkg-deb -I "$deb" >/dev/null
  dpkg-deb -c "$deb" >/dev/null
  tar -tzf "$macos_tar" >/dev/null
  (cd "$OUT_DIR" && sha256sum "$(basename "$deb")" "$(basename "$macos_tar")" > SHA256SUMS)
  printf '%s\n%s\n%s\n' "$deb" "$macos_tar" "$OUT_DIR/SHA256SUMS"
}

case "$TARGET" in
  check) release_checks ;;
  deb|linux-deb) build_deb ;;
  macos-tar) build_macos_tar ;;
  release) build_release ;;
  *) echo "unsupported target: $TARGET" >&2; usage >&2; exit 2 ;;
esac
