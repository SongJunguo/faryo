# Faryo Owner

Faryo Owner is the local execution component. It exposes a loopback-only web
control surface for tmux-backed work sessions and is reached through Faryo
Gateway or a configured reverse tunnel.

The maintained fork validates Owner against an existing Ubuntu/Linux Codex TUI.
Other inherited terminal profiles are compatibility paths, not current support
claims.

## Runtime Boundary

Owner does not own public login, domain routing, Caddy, or the gateway workbench.
It should bind only to `127.0.0.1`.

Runtime configuration defaults to:

```text
~/.faryo/owner/config/faryo.env
~/.faryo/owner/data/
```

## Local Run

```bash
./scripts/start-web-owner.sh
```

Set `FARYO_PYTHON` in the private Owner env file to pin the service to a
dedicated virtual environment instead of whichever `python3` is first on PATH.

Owner does not resize tmux windows by default, so terminal UIs wrap at the
dimensions selected by real tmux clients. The server's positive
`--pane-width` option is an explicit compatibility opt-in for terminal-only
capture; it is never applied to a running Codex TUI.

The user-level timer template lives at:

```text
deploy/user-systemd/faryo-owner-keepalive.timer
```

Use `/health` for liveness and `/api/status` for authenticated runtime checks.
The status payload includes the source version for deployment acceptance.

## Joining Gateway

Installing Owner only proves local runtime health. Gateway visibility also needs
route config, a matching Owner token, any required reverse tunnel loopback port,
and the workspace/file-inbox roots used by that route.

After configuration, run the read-only `scripts/diagnose-owner-gateway.sh`
endpoint check. See `runbook.md` for the layered acceptance flow.
