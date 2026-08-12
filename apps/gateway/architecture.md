# Faryo Gateway Architecture

Faryo Gateway is the public entry layer. It owns public web access, login
state, user-to-route authorization, path routing, the handoff workbench, and
controlled headers injected into local execution endpoints.

## 1. Entry Flow

```text
phone browser
  -> https://<your-faryo-domain>/
  -> HTTPS edge (for example Cloudflare Tunnel or a reverse proxy)
  -> Faryo Gateway 127.0.0.1:8780
  -> Faryo workbench
  -> /txy/?session=... /hp/?session=... /pc/?session=...
  -> Faryo local execution endpoint
```

The phone talks only to Gateway. Owner tokens are not exposed to the browser;
Gateway injects them by route when proxying upstream requests. HP, PC, and TXY
endpoints should use independent owner tokens.

## 2. Gateway Host Responsibilities

Gateway host: the machine reached by the public HTTPS edge.

- A reverse proxy may listen on public 80/443, or an outbound Cloudflare Tunnel
  may route a hostname directly to `127.0.0.1:8780`.
- Gateway provides form login, auth cookies, the unified workbench, account
  tools, and restricted path proxying.
- Gateway private route config controls visible endpoints, workspace roots,
  and attachment inbox roots.
- Gateway probes each route through its real `/health` endpoint. Offline
  routes affect session resume and new-session selection only.
- `/txy/?session=...`, `/txy/api/...`, and required owner static assets proxy
  to the Owner running on the Gateway host itself at `127.0.0.1:8765`.
- `/hp/?session=...`, `/hp/api/...`, and required owner static assets proxy to
  the HP reverse tunnel on `127.0.0.1:18766`. This port must be provided by the
  real HP reverse tunnel; do not bridge it to the local Owner port.
- `/pc/?session=...`, `/pc/api/...`, and required owner static assets proxy to
  the PC reverse tunnel on `127.0.0.1:18765`. This port must be provided by the
  real PC/WSL reverse tunnel; do not bridge it to the local Owner port.
- Bare `/txy/`, `/hp/`, and `/pc/` paths are not user entry points.

The Gateway host SSH service must remain available when HP/PC endpoints need to
establish reverse tunnels to it.

## 3. Governance Parameters

- Gateway bind: `127.0.0.1:8780`.
- Only routes listed in `FARYO_GATEWAY_ROUTES` are loaded; only those routes
  require Owner tokens.
- Login cookie: uses the Faryo cookie name.
- Owner tokens: private runtime config, never committed to Git.
- Route auth: private runtime config, never committed to Git.
- Upstream control headers: use Faryo header names.
- Browser responses deny framing and unnecessary camera, microphone, and
  geolocation permissions, disable referrer leakage, and advertise HSTS on the
  public HTTPS path.
- Cloudflare Access is optional defense in depth. A tunnel by itself is routing,
  not identity policy; Gateway login remains the application boundary.

## 4. Verification

```bash
curl -fsS http://127.0.0.1:8780/login
curl -sS -o /dev/null -w '%{http_code} %{ssl_verify_result}\n' https://<your-faryo-domain>/
```

Expected:

- `faryo-gateway.service` is active.
- Public unauthenticated access returns the login page or a login redirect.
- TLS verification result is `0`.
- After login, `/` shows the workbench, route status, and recent sessions.
- Bare `/hp/`, `/txy/`, and `/pc/` are not shown as direct user entry points.
- HP and PC are online only when their real reverse tunnels exist and each
  Owner `/health` endpoint is reachable.

## 5. Non-Goals

- Gateway does not implement the local tmux execution surface.
- Gateway does not commit tokens, password hashes, cookie secrets, or runtime
  config.
- Gateway does not merge one HP/PC local execution layer into the Gateway
  runtime directory.
