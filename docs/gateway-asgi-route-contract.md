# Gateway ASGI Route Contract

Updated: 2026-08-20  
Target: Faryo v1.4.0

Production cutover status: Uvicorn is active on the loopback Gateway port. The
legacy engine is retained only as a temporary rollback switch until the v1.4.0
release-removal gate.

This inventory is the cutover checklist between the temporary legacy
`BaseHTTPRequestHandler` Gateway and the Starlette/Uvicorn Gateway. It records
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
| Owner page and allowlisted resources | GET, HEAD | signed session and route allow | `asgi_owner_proxy.py` | login redirect, HTML/JS bytes and unknown-resource denial |
| Owner control API | POST | signed session, route allow and CSRF | `asgi_control.py` | arbitrary Owner API proxy plus action-only body-free audit |
| Archive/Restore and revoke | POST | signed session and CSRF | `asgi_control.py` | status/error, idempotency and body-free audit |
| Codex start/resume | POST | Codex-only, route/cwd policy and CSRF | `asgi_agents.py` | launch ID retry, fallback, redirect and audit |
| Bridge package create/append/inject | POST | signed session, CSRF, bounded files and route scope | `asgi_bridge.py` | JSON bounds, multipart upload, send and audit |
| MCP | OPTIONS, GET, DELETE, POST | dedicated bearer token and exact CORS origin | `asgi_mcp.py` | denial, 405, initialize, batch, notification and handoff |
| Unknown direct API | GET, HEAD, POST | JSON 401; POST also requires CSRF before 404 | read/control fallback | legacy-equivalent status and JSON |
| Unknown page | GET, HEAD | inner login redirect before authenticated 404 | read fallback | redirect, body and security headers |
| Generic preflight | OPTIONS | public 204; MCP keeps its own CORS contract | `asgi_read.py` | legacy-equivalent status and headers |

The executable contract is
`apps/gateway/server/tests/test_asgi_read_contract.py`. It runs legacy and
Uvicorn on separate loopback ports and compares status, selected headers,
cookies, normalized HTML/JSON, streaming bytes, uploads, Owner-injected headers,
CSRF denials and body-free audit records.

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
The remaining release gate is to remove the legacy HTTP implementation and its
temporary engine switch after the rollback tag is confirmed.
