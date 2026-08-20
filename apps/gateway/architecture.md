# Faryo Gateway Architecture

> **Scope note:** the maintained fork currently validates one local Ubuntu/Linux
> Codex route. The HP/PC and multi-endpoint sections below document inherited
> implementation capability; they are not current deployment acceptance claims.

Faryo Gateway is the public entry layer. It owns public web access, login
state, user-to-route authorization, path routing, the handoff workbench, and
controlled headers injected into local execution endpoints.

Cookie signing/validation, CSRF derivation, trusted login-rate identity,
redirect allowlisting and browser security headers are shared pure policy in
`server/gateway_security.py`. The legacy handler and the migrating ASGI app
must consume the same module rather than reproduce these boundaries.

`server/asgi_app.py` is currently a non-production Starlette adapter used for
dual-stack contract comparison. It covers public manifest/service-worker/static
assets, login/logout, CSRF, the authenticated home page, tmux control POST,
ordinary Owner API GET/SSE, session pages and allowlisted Owner assets. MCP,
most direct Gateway writes and uploads remain on the legacy stack until their
contracts match; Archive/Restore is already covered by the dual-stack adapter.

`server/owner_client.py` is the shared authenticated Owner client for scoped
internal headers, JSON/raw calls and bounded multipart forwarding. Forwarded
browser headers cannot replace internal identity/scope fields. Both HTTP stacks
use it so Owner tokens and workspace/inbox scopes cannot drift.

`server/mcp_service.py` is the HTTP-independent MCP JSON-RPC/tool service used
by both stacks. Token/CORS remain adapter concerns, while protocol methods,
batch/notification behavior and handoff creation have one implementation.

`server/asgi_support.py` owns Starlette security middleware, signed-session
lookup, HTML/JSON responses, bounded JSON input, proxy header filtering and
body-free audit writes. Route modules should not recreate those helpers.

## 1. Entry Flow

```text
phone browser
  -> https://<your-faryo-domain>/
  -> identity-aware HTTPS edge
  -> outbound tunnel or hardened reverse proxy
  -> Faryo Gateway 127.0.0.1:8780
  -> Faryo workbench
  -> /txy/?session=... /hp/?session=... /pc/?session=...
  -> Faryo local execution endpoint
```

The phone talks only to Gateway after the external identity check. Owner tokens
are not exposed to the browser; Gateway injects them by route when proxying
upstream requests. HP, PC, and TXY
endpoints should use independent owner tokens.

## 2. Gateway Host Responsibilities

Gateway host: the machine reached by the public HTTPS edge.

- A reverse proxy may listen on public 80/443, or an outbound Cloudflare Tunnel
  may route a hostname directly to `127.0.0.1:8780`.
- Gateway provides form login, auth cookies, the unified workbench, account
  tools, and restricted path proxying.
- The authenticated portal shell remains server-rendered, while its versioned
  CSS/JavaScript are static files. The only dynamic script-adjacent data is a
  nonce-protected JSON map of routes the current user may access.
- Gateway owns the root-scoped `standalone` PWA manifest and service worker.
  Owner session pages reference that same manifest so installed navigation stays
  within one authenticated app identity.
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
- Live agent limits are configured per route and are independent from the
  merged Session History display budget.
- Login cookie: uses the Faryo cookie name.
- Browser sessions use a host-only `__Host-` cookie with `Secure`, `HttpOnly`,
  `SameSite=Strict`, and a server-enforced absolute lifetime. The default is 12
  hours; private `FARYO_GATEWAY_SESSION_HOURS` configuration accepts `1`–`168`.
- Owner tokens: private runtime config, never committed to Git.
- Route auth: private runtime config, never committed to Git.
- Upstream control headers: use Faryo header names.
- Browser responses deny framing and unnecessary camera, microphone, and
  geolocation permissions, disable referrer leakage, and advertise HSTS on the
  public HTTPS path.
- Fullscreen permission is limited to the same origin. Entering it remains an
  explicit browser user gesture and is independent from the PWA display mode.
- Attention is derived in-memory from lifecycle states. Page-open notifications
  require browser permission and contain only generic body text.
- A tunnel by itself is routing, not identity policy. For an Internet-facing
  Gateway that can steer coding agents, protect the complete hostname with
  Cloudflare Access (or an equivalent identity-aware proxy), an exact identity
  allowlist, an explicit session lifetime, and no broad bypass. Independent MFA
  is a risk-based deployment choice; Gateway login remains a separate
  application boundary behind it.

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
