# Gateway ASGI Route Contract

Updated: 2026-08-21
Target: Faryo v1.6.0

Production cutover status: Uvicorn is active on the loopback Gateway port. The
legacy engine and rollback switch have been removed; rollback uses the signed
previous release tag.

This inventory records the completed migration from the former
`BaseHTTPRequestHandler` Gateway to Starlette/Uvicorn. It records
public route families rather than any private deployment hostname, identity,
token, path, or session data.

## Route inventory

| Family | Methods | Authentication and policy | Starlette adapter | Contract evidence |
|---|---|---|---|---|
| Manifest and service worker | GET, HEAD | Public; no-store | `asgi_read.py` | bytes, type, cache and security headers |
| Gateway CSS/JS and shared appearance assets | GET, HEAD | Public allowlist only | `asgi_read.py` | bytes, type, cache and unknown-path fallback |
| PWA icons and favicon | GET, HEAD | Public filename allowlist only | `asgi_read.py` | PNG/ICO bytes, type and cache |
| Login and logout | GET, HEAD, POST | rate-limited bcrypt; signed host cookie | `asgi_auth.py` | success/failure HTML, redirect and cookies |
| CSRF and password rotation | GET, HEAD, POST | signed session; epoch-bound CSRF | `asgi_auth.py` | denial, validation, bcrypt offload and cookie rotation |
| Security activity, status and workbench | GET, HEAD | signed session and route scope | `asgi_read.py` | JSON, filtering/paging and bounded audit read |
| Bridge package list/private asset | GET, HEAD | signed session and package owner | `asgi_read.py` | path allowlist, MIME, bytes and private no-store |
| Owner API and SSE | GET, HEAD | signed session, route allow, injected Owner scope | `asgi_owner_proxy.py` | status, bytes, query, proxy headers and streaming SSE |
| Owner page and allowlisted resources | GET, HEAD | signed session and route allow | `asgi_owner_proxy.py` | login redirect, HTML/JS bytes, script/allowlist completeness and no-store denial |
| Owner control API | POST | signed session, route allow and CSRF | `asgi_control.py` | arbitrary Owner API proxy plus action-only body-free audit |
| Archive/Restore and revoke | POST | signed session and CSRF | `asgi_control.py` | status/error, idempotency and body-free audit |
| Codex start/resume | POST | Codex-only, route/cwd policy and CSRF | `asgi_agents.py` | fast Starting receipt, launch ID retry, cwd fallback, redirect and audit |
| Bridge package create/append/inject | POST | signed session, CSRF, bounded files and route scope | `asgi_bridge.py` | JSON bounds, multipart upload, send and audit |
| MCP | OPTIONS, GET, DELETE, POST | dedicated bearer token and exact CORS origin | `asgi_mcp.py` | denial, 405, initialize, batch, notification and handoff |
| Unknown direct API | GET, HEAD, POST | JSON 401; POST also requires CSRF before 404 | read/control fallback | legacy-equivalent status and JSON |
| Unknown page | GET, HEAD | inner login redirect before authenticated 404 | read fallback | redirect, body and security headers |
| Generic preflight | OPTIONS | public 204; MCP keeps its own CORS contract | `asgi_read.py` | legacy-equivalent status and headers |

The executable contract is
`apps/gateway/server/tests/test_asgi_read_contract.py`. It runs Uvicorn on an
isolated loopback port and explicitly asserts status, selected headers, cookies,
HTML/JSON, streaming bytes, uploads, Owner-injected headers, CSRF denials and
body-free audit records.

The canonical source gate also parses every script referenced by the Owner HTML
and requires either an exact Gateway asset allowlist entry or an allowed local
prefix. Unknown Owner resources return `Cache-Control: no-store`; the mutable
style, Preact and app entries use the rendered Faryo release version as their
query key. This prevents a previously cached 404 from requiring hard refresh.
Gateway-owned home/auth/PWA JavaScript, CSS and icon URLs use one SHA-256-derived
revision of the shipped asset bytes, so a changed workbench cannot retain an old
manual query version.

`apps/gateway/server/tests/test_asgi_shutdown.py` keeps a real Owner SSE response
open, requests Gateway shutdown and requires the server to exit before the
graceful timeout. `FaryoServer` closes registered Gateway-to-Owner streams before
Uvicorn waits for HTTP tasks. `OwnerStream` retains the response-owned socket and
uses `shutdown(SHUT_RDWR)` before close, so an already blocked `readline` ends
normally instead of producing a ten-second timeout and forced-cancellation log.

## Deliberate HTTP-server differences

Starlette automatically provides `HEAD` for read routes. The legacy Gateway
returned `501` because it never implemented `HEAD`; the ASGI behavior is a
standards-compliant, read-only extension. Dedicated checks prove that `HEAD`
returns no body, cannot bypass login, and still receives HSTS, CSP-related
security policy and `nosniff` headers.

Unsupported state-changing methods return Starlette `405` rather than legacy
`501`. They do not reach a write handler. MCP `DELETE` is explicitly mapped to
the same authenticated `405` response in both stacks because Faryo uses no MCP
server session to terminate. MCP CORS advertises only `POST, OPTIONS`.

## Cutover gate

The production move from the legacy server to Uvicorn was accepted after:

1. this inventory and the full source gate pass from a clean checkout;
2. authenticated desktop and mobile browser smoke tests pass against the ASGI
   port, including SSE reconnect and a non-destructive CSRF write fixture;
3. the service unit, health check and rollback command have been tested without
   changing any tmux pane geometry;
4. an active SSE client cannot hold a service restart open until the graceful
   shutdown timeout.

The HTTP migration gate is complete. The source and deployment suites continue
to prove that only `run_asgi.py` is a valid production Gateway entrypoint.
