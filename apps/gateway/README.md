# Faryo Gateway

Faryo Gateway is the public gateway component. It handles the public web entry,
login, route authorization, the handoff workbench, and proxying to available
local execution surfaces.

The maintained fork validates one Ubuntu/Linux Codex route. Multi-route support
remains available in the implementation, but additional endpoint types are not
part of the current acceptance matrix.

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

The inner Faryo login defaults to a 12-hour absolute session. Set
`FARYO_GATEWAY_SESSION_HOURS` in the private Gateway environment to an integer
from 1 through 168 when a different operator-selected lifetime is required.
Changing it does not alter Cloudflare Access sessions; the two layers are
configured independently.

Running-session limits are independent from history display. Configure them per
enabled route with `FARYO_TXY_MAX_RUNNING`, `FARYO_HP_MAX_RUNNING`, or
`FARYO_PC_MAX_RUNNING` (valid range `1`–`32`). Defaults are 8 for TXY and 4 for
HP/PC.

The workbench keeps live agents and resumable history separate. `Active
Sessions` includes every tmux pane currently running a recognized Codex process,
including panes started directly on the endpoint. Only sessions
created and stamped by Faryo expose the remote `Close` action; externally
started desktop tmux sessions remain openable but protected from remote close.
`Session History` excludes those live sessions, scrolls independently, and uses
server-backed pagination with 10 records per page. Use Previous/Next or enter a
page number and press Enter/Go to jump directly through long histories. Search
matches only normalized session titles, explicit Codex rename metadata, and the
working-folder basename. Date and archive chips filter on Codex metadata; they
do not read conversation messages or rollout files. Filters are reflected in
the current URL for refresh/navigation but are not written to browser storage.

`Start Codex` opens a dedicated working-directory picker. The picker defaults to
the latest eligible cwd, deduplicates shortcuts within Recent while keeping the
complete canonical child list in Folders,
uses `..` as the first Folders row for parent navigation, collapses long
breadcrumbs, filters the current page without recursive search, and keeps
`Start Codex here` fixed outside the scrolling list. Directory choices
still come from Owner, carry its HMAC selection token, and are revalidated by
Owner before tmux starts.

See [runbook.md](runbook.md) for Cloudflare Tunnel, first login, verification,
and rollback instructions. Internet-facing deployments that can steer agents
must also follow the [Gateway security hardening](../../docs/gateway-security-hardening.md)
checklist; a tunnel alone is not an authentication layer.
