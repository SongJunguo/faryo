# Faryo Gateway

Faryo Gateway is the public gateway component. It handles the public web entry,
login, route authorization, the handoff workbench, and proxying to available
local execution surfaces.

## Runtime Boundary

Gateway does not own the local tmux execution surface. It only routes to owner
components through configured loopback ports or reverse tunnels.

For a single-machine deployment, both services stay on loopback:

```text
public HTTPS edge -> 127.0.0.1:8780 Gateway -> 127.0.0.1:8765 Owner
```

Gateway performs browser login and injects the Owner token while proxying. The
Owner token must never be placed in a public URL or browser configuration.

Runtime configuration defaults to:

```text
~/.faryo/gateway/config/faryo.env
~/.faryo/gateway/config/gateway-auth.json
~/.faryo/gateway/state/gateway-cookie-secret
```

## Local Run

```bash
./scripts/run-gateway.sh
```

The user-level service template lives at:

```text
deploy/user-systemd/faryo-gateway.service
```

For a private, single-route installation from the repository root:

```bash
FARYO_PYTHON=/absolute/path/to/python \
FARYO_GATEWAY_ROUTE=txy \
./apps/gateway/scripts/init-local-gateway.sh

./apps/gateway/scripts/install-user-service.sh
curl --noproxy '*' -fsS http://127.0.0.1:8780/login >/dev/null
```

The selected Python must provide `bcrypt`. The initializer reads the existing
private Owner token, writes mode-`600` Gateway files below `~/.faryo`, and only
requires a token for the enabled route. Re-running it preserves an existing
login config. Set `FARYO_GATEWAY_RESET_AUTH=1` only when intentionally rotating
the Gateway login.

Running-session limits are independent from history display. Configure them per
enabled route with `FARYO_TXY_MAX_RUNNING`, `FARYO_HP_MAX_RUNNING`, or
`FARYO_PC_MAX_RUNNING` (valid range `1`–`32`). Defaults are 8 for TXY and 4 for
HP/PC.

The workbench keeps live agents and resumable history separate. `Active
Sessions` includes every tmux pane currently running a recognized Codex or
Claude process, including panes started directly on the endpoint. Only sessions
created and stamped by Faryo expose the remote `Close` action; externally
started desktop tmux sessions remain openable but protected from remote close.
`Session History` excludes those live sessions, scrolls independently, and uses
server-backed pagination with 10 records per page. Use Previous/Next or enter a
page number and press Enter/Go to jump directly through long histories.

See [runbook.md](runbook.md) for Cloudflare Tunnel, first login, verification,
and rollback instructions.
