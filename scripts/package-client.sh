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
    "$ROOT"/apps/gateway/scripts/*.sh
  python3 -m py_compile \
    "$ROOT/apps/shared/pd_state.py" \
    "$ROOT/apps/owner/local-tmux-owner/server.py" \
    "$ROOT/apps/gateway/server/server.py" \
    "$ROOT/apps/gateway/scripts/generate-gateway-auth-config.py"
  for js_file in \
    "$ROOT/apps/owner/local-tmux-owner/static/compact-rules-codex.js" \
    "$ROOT/apps/owner/local-tmux-owner/static/compact-rules-claude.js" \
    "$ROOT/apps/owner/local-tmux-owner/static/math-render.js" \
    "$ROOT/apps/owner/local-tmux-owner/static/markdown-render.js" \
    "$ROOT/apps/owner/local-tmux-owner/static/live-scroll.js" \
    "$ROOT/apps/shared/static/appearance.js" \
    "$ROOT/apps/owner/local-tmux-owner/static/app.js" \
    "$ROOT/apps/gateway/server/static/projects.js"
  do
    node --check "$js_file"
  done
  node "$ROOT/apps/owner/local-tmux-owner/tests/math-render.test.js"
  node "$ROOT/apps/owner/local-tmux-owner/tests/markdown-render.test.js"
  node "$ROOT/apps/owner/local-tmux-owner/tests/live-scroll.test.js"
  node "$ROOT/apps/owner/local-tmux-owner/tests/compact-rules-codex.test.js"
  python3 -m unittest discover -s "$ROOT/apps/owner/local-tmux-owner/tests" -p 'test_*.py'
  python3 - "$ROOT" <<'PY'
from pathlib import Path
import plistlib
import sys
root = Path(sys.argv[1])
index = (root / "apps/owner/local-tmux-owner/static/index.html").read_text(encoding="utf-8")
gateway = (root / "apps/gateway/server/server.py").read_text(encoding="utf-8")
assert "compact-rules-codex.js" in index, "index.html must load compact-rules-codex.js"
assert "compact-rules-claude.js" in index, "index.html must load compact-rules-claude.js"
assert "compact-rules-codex.js" in gateway, "gateway must allow compact-rules-codex.js"
assert "compact-rules-claude.js" in gateway, "gateway must allow compact-rules-claude.js"
assert "math-render.js" in index, "index.html must load math-render.js"
assert "math-render.js" in gateway, "gateway must allow math-render.js"
assert "markdown-render.js" in index, "index.html must load markdown-render.js"
assert "markdown-render.js" in gateway, "gateway must allow markdown-render.js"
assert "live-scroll.js" in index, "index.html must load live-scroll.js"
assert "live-scroll.js" in gateway, "gateway must allow live-scroll.js"
assert "cdn.jsdelivr.net/npm/katex" not in index, "KaTeX must not require an external CDN"
assert 'vendor/katex/katex.min.css?v=0.18.4' in index, "index.html must load local KaTeX CSS"
assert 'vendor/katex/katex.min.js?v=0.18.4' in index, "index.html must load local KaTeX JS"
assert 'vendor/katex/contrib/auto-render.min.js?v=0.18.4' in index, "index.html must load local KaTeX auto-render"
assert '"vendor/katex/"' in gateway, "gateway must proxy local KaTeX assets"
for relative in (
    "katex.min.css",
    "katex.min.js",
    "contrib/auto-render.min.js",
    "fonts/KaTeX_Main-Regular.woff2",
    "LICENSE",
):
    assert (root / "apps/owner/local-tmux-owner/static/vendor/katex" / relative).is_file(), f"missing vendored KaTeX asset: {relative}"
assert "cdn.jsdelivr.net/npm/markdown-it" not in index, "Markdown must not require an external CDN"
assert 'vendor/markdown-it/markdown-it.min.js?v=14.3.0' in index, "index.html must load local markdown-it"
assert '"vendor/markdown-it/"' in gateway, "gateway must proxy local markdown-it assets"
for relative in ("markdown-it.min.js", "LICENSE"):
    assert (root / "apps/owner/local-tmux-owner/static/vendor/markdown-it" / relative).is_file(), f"missing vendored markdown-it asset: {relative}"
app = (root / "apps/owner/local-tmux-owner/static/app.js").read_text(encoding="utf-8")
assert "headers['X-Owner-Token'] = ownerToken" in app, "Owner API calls must include the token header"
assert "next.searchParams.set('token', ownerToken)" in app, "session switches must preserve direct Owner auth"
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
