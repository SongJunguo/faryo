# Local Installation and Lifecycle

Faryo's maintained production path is Ubuntu/Linux, tmux, and Codex CLI. The
operator uses one `faryo` command; Conda, pip requirements, service templates,
ports, and helper scripts are implementation details.

## Runtime shape

```text
systemd --user
├── faryo-owner.service    local Codex/tmux control API on 127.0.0.1:8765
└── faryo-gateway.service  authenticated browser UI on 127.0.0.1:8780

tmux
└── faryo1, faryo2, ...    the real Codex CLI processes and TUI state
```

Owner is the private workstation-side service that reads Codex history and
controls tmux. Gateway is the browser-facing login, navigation, and reverse
proxy layer. They use two ports so the privileged local control API never needs
to become the public web entry. Both bind only to loopback by default.

Stopping or restarting Owner/Gateway does not stop or resize Codex tmux sessions.

## Requirements

- Python 3.10+ with `venv` and ensurepip
- tmux, curl, systemd user services, and Codex CLI
- a current Chromium-family browser

Python 3.10 is the compatibility floor because current Starlette, Uvicorn,
AnyIO, and Click pins support it and Faryo uses Python 3.10 union type syntax.
Python 3.9 and older would require dependency and source compatibility branches.
Python 3.11+ uses `tomllib`; Python 3.10 receives the exact-pinned `tomli`
backport. Faryo does not use uv and does not modify system Python or Conda base.

## Verified release installation

Download these two assets from the same tagged GitHub Release:

- `install-faryo.sh`
- `install-faryo.sh.sha256`

Review and verify the script before executing it:

```bash
sha256sum --check install-faryo.sh.sha256
less install-faryo.sh
bash install-faryo.sh --version v1.6.3 --workspace /path/to/workspace
```

The script then downloads `faryo-v1.6.3.tar.gz` and its checksum, accepts only a
bounded single-root regular-file archive, and invokes the same `faryo install`
path used by source developers. It does not execute sudo, install apt packages,
create a tunnel, or change Cloudflare settings.

The generated `~/.local/bin/faryo` entry uses the selected private Python in
isolated mode. It ignores ambient `PYTHONPATH`/`PYTHONHOME`, and installation
health requires the CLI to report the exact version being prepared.

When upgrading a pre-v1.5 deployment that still has the dedicated
`local-tmux-owner` service session/keepalive timer, explicitly approve only that
supervisor migration:

```bash
bash install-faryo.sh --version v1.6.3 --workspace /path/to/workspace --migrate-owner
```

The migration records and compares every existing agent tmux geometry. It stops
only the named legacy Owner service session, never `faryo1`, `faryo2`, or other
Codex sessions, and restores the old supervisor if health checks fail.

If `/usr/bin/python3` is not compatible, select another existing interpreter:

```bash
bash install-faryo.sh --python /path/to/python3.13 --workspace /path/to/workspace
```

## Installed state

```text
~/.local/bin/faryo
~/.local/share/faryo/
├── current -> versions/<active-version>
├── versions/<version>/
│   ├── app/
│   ├── .venv/
│   └── install-manifest.json
└── state/

~/.config/systemd/user/
├── faryo-owner.service
└── faryo-gateway.service

~/.faryo/                     persistent private state
├── owner/config + data
└── gateway/config + state
```

Each service unit pins the exact active version directory. Update and rollback
atomically change `current`, rewrite both units, restart them, and pass a health
gate. This avoids a half-written symlink or package update changing a running
service unexpectedly.

Program versions are replaceable. `~/.faryo` is not: it contains tokens, login
state, attachment data, delivery metadata, and other private runtime state.

## Everyday commands

```bash
faryo doctor              # read-only dependency, permission, bind, and health checks
faryo status --json       # privacy-safe machine-readable service summary
faryo start               # start both web services and wait for health
faryo stop                # stop web services only; preserve all tmux sessions
faryo restart             # restart and health-check both services
faryo open                # open the loopback Gateway without exposing Owner token
faryo logs owner          # bounded user journal
faryo logs gateway
```

The diagnostic JSON intentionally excludes paths, email addresses, domains,
tokens, session names, prompts, and conversation content.

## Update and rollback

```bash
faryo update                    # latest stable release
faryo update --version v1.6.3   # exact release
faryo rollback                  # previous healthy installed version
```

Update downloads only approved GitHub HTTPS assets, enforces compressed and
extracted size bounds, verifies the exact asset name and SHA-256, validates
release/package versions, builds an independent private venv, and switches only
after preparation. Service health failure restores config, links, units, and the
previous services. It never rolls back private conversation or attachment data.

For a reviewed offline asset:

```bash
faryo update --version v1.6.3 \
  --archive ./faryo-v1.6.3.tar.gz \
  --checksum ./faryo-v1.6.3.tar.gz.sha256
```

## Uninstall

```bash
faryo uninstall
```

This disables and removes only Faryo's exact user units and versioned program
directory. It leaves `~/.faryo` and all ordinary Codex tmux sessions intact.

Private data deletion is deliberately harder and cannot be inferred from a
normal uninstall:

```bash
faryo uninstall --purge-data --yes
```

This is irreversible. Back up anything needed from `~/.faryo` first.

## First login and remote access

The fresh local username is `faryo`; its generated password is stored in the
mode-`600` file `~/.faryo/gateway/config/initial-password`. Change it from
`/password`, verify the replacement, then remove the stale plaintext file.

Local installation creates no public ingress. Remote access remains a separate,
explicit operation described in the [Gateway runbook](../apps/gateway/runbook.md)
and [security guide](gateway-security-hardening.md). Never expose Owner directly.
