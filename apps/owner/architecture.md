# Faryo Owner Architecture

Faryo Owner is the local execution layer. It owns only the local `tmux` control
surface. It does not own the public entry point, account login, path routing, or
Caddy.

`Owner` is an internal component name. It is not the Faryo product name or a
public brand surface.

## 1. Local Execution Flow

```text
Faryo Gateway
  -> route port or SSH reverse tunnel
  -> local execution endpoint 127.0.0.1:8765
  -> local-tmux-owner web server
  -> tmux target session
  -> terminal TUI
```

The phone should not access Owner directly. Owner tokens should be injected by
Gateway or used only for local smoke/status checks.

## 2. Local Runtime

- `local-tmux-owner`: local execution backend, bound to `127.0.0.1`.
- An optional SSH reverse tunnel from a local endpoint to the Gateway host, run
  as a user service on that endpoint. When enabled, verify from the Gateway side
  with the owner token and expected endpoint identity.
- `faryo-owner-keepalive.timer`: user-level keepalive timer.
- `tmux:<target>`: the controlled target session.
- `tmux:local-tmux-owner`: the Owner service session.

## 3. Required Dependencies

- `tmux`: terminal TUI and session foundation.
- `curl`: health, smoke, and status checks.
- `openssh-client`: required only when this endpoint establishes a reverse
  tunnel to the Gateway host.

Owner does not require inbound SSH and should not bind directly to public or
LAN addresses.

## 4. Product Data Directory

Default product data root:

```text
~/.faryo/owner/data/
  inbox/
  artifacts/
  cache/
  logs/
```

The workspace is the terminal command working directory. It is not the Faryo
product data root. Gateway may inject user/route-specific upload destinations,
but the default upload destination should come from the Faryo data directory.

## 5. Governance Parameters

- Owner bind: `127.0.0.1:8765`.
- Web capture: compact/full requests use 320/800-line soft targets. Structured
  Codex history may exceed them to retain complete recent turns, while separate
  tail and character ceilings keep the payload bounded.
- tmux history limit: default 500 lines.
- Token: private runtime config, never committed to Git.
- Product data root: default `~/.faryo/owner/data`.
- Workspace Changes is a separate read-only module: Git root resolution is
  scoped, commands are fixed/bounded, and returned paths are relative.
- Attachment storage is a separate bounded module: magic/MIME/suffix policy,
  upload size, generated names and dated retention do not depend on the HTTP
  handler.
- Local-file and start-directory policy is a separate module: configured roots,
  suffix allowlists, symlink resolution, directory limits and selection tokens
  are tested without tmux or HTTP globals.
- The read-only Changes browser controller is a native ES module with injected
  API/session/panel dependencies; `app.js` remains the composition root and the
  diff renderer stays a lazy local asset.
- Low-level command execution and tmux/process-tree/identifier primitives are
  isolated in `tmux_runtime.py`; higher services keep policy and translate
  failures rather than rebuilding subprocess defaults.
- Reliable-send durable checkpoints are isolated in `delivery_store.py`; it
  enforces ID bounds, privacy-minimal records, atomic fsync, 0700/0600 modes,
  TTL cleanup and corrupt/symlink rejection. `delivery_service.py` owns the
  reference-counted session/message locks, in-memory checkpoints, paste,
  Tab/Enter confirmation, retry and ambiguity policy through an explicit
  runtime adapter; HTTP only translates its bounded result or error.
- Pure Codex message extraction, complete-turn budgeting, previews and
  revision-bound cursors are isolated in `codex_history.py`; incremental file
  indexing and caches remain higher services until their state boundary is
  explicit.
- Capability and diagnostics payloads use an explicit allowlist and counts; they
  never expose private runtime configuration.
- Upstream control headers: use Faryo header names.

## 6. Verification

```bash
./scripts/status.sh
./scripts/smoke-test.sh
./scripts/verify-reverse-tunnel.sh
ss -ltnp | grep ':22 ' || true
```

Expected:

- Owner health is OK.
- Smoke test passes.
- Owner listens only on loopback.
- If this endpoint uses a reverse tunnel, its tunnel service is active.
- If this endpoint uses a reverse tunnel, `verify-reverse-tunnel.sh` can
  read Owner `/api/status` from the Gateway side and validate owner label and
  session.
- No unauthorized inbound `:22` listener is present.

## 7. Non-Goals

- Owner does not host Faryo Gateway.
- Owner does not provide a public login page.
- Owner does not commit tokens, password hashes, or runtime secrets.
- Owner does not expose arbitrary launch commands; the maintained launcher is
  the explicitly configured Codex runtime.
