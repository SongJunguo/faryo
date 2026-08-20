# Future Go Gateway v2 Boundary

Status: design boundary only; not a Faryo v1.4.0 implementation commitment

Faryo v1.4 keeps the production Gateway on Python 3.13, Starlette and Uvicorn.
That stack is now modular, contract-tested and small enough to maintain. A Go
rewrite would be justified only by a concrete distribution or operating-cost
need, not by language preference.

## Why a future Go Gateway may be useful

- one cross-compiled Gateway executable for hosts that should not manage a
  Python environment;
- lower idle memory or faster cold start proven on the same workload;
- simpler deployment of the public proxy/session layer while Owner remains a
  workstation-local Python service;
- sustained proxy/SSE concurrency that is measured to exceed the current ASGI
  deployment's practical limits.

None of those is currently a blocker. v1.4 therefore does not run two Gateway
implementations or add a Go toolchain to CI.

## Frozen boundary

A future implementation may replace only the Gateway process on the public
loopback port. It must not absorb or reimplement:

- tmux process detection, terminal input or geometry;
- Codex rollout/history extraction or Codex App Server lifecycle calls;
- reliable composer delivery and idempotency checkpoints;
- Markdown/TeX rendering, Live tmux or Owner browser state;
- workspace Changes, attachments stored by Owner, or local path policy.

Those remain Owner responsibilities behind the current authenticated Owner
HTTP contract.

The candidate Go Gateway must preserve these Gateway responsibilities:

```text
external identity-aware HTTPS edge
  -> loopback Gateway
     -> signed inner login cookie / epoch revoke / CSRF
     -> route and user authorization
     -> workbench aggregation and metadata-only history search
     -> body-free control audit and private bridge-package storage
     -> bounded Owner JSON, multipart and SSE proxy
     -> optional MCP handoff endpoint
  -> existing Owner route(s)
```

## Contracts that must not drift

- only configured routes load, and only enabled routes require Owner tokens;
- Owner identity/scope headers are generated server-side and forwarded browser
  headers cannot override them;
- cookies retain host-only Secure/HttpOnly/SameSite, absolute lifetime and epoch
  revocation semantics;
- every browser write retains the existing CSRF boundary;
- CSP, HSTS, `nosniff`, frame denial, referrer and Permissions Policy remain
  equivalent;
- Owner SSE stays streaming, cancellation-safe and prompt on service shutdown;
- upload, request, response, path, filename and retention bounds remain equal or
  stricter;
- audit records remain body-free and HMAC-pseudonymous;
- unknown route/API/method behavior remains covered by the explicit ASGI route
  inventory;
- private config, password hashes, cookie secrets, bridge assets and audit logs
  are never migrated through a public API or committed to source.

## Migration shape

1. Define language-neutral fixtures from the existing explicit ASGI contracts;
   do not make the Python implementation an opaque oracle.
2. Implement a Go configuration/Owner-client/security core with no production
   listener switch.
3. Run Python and Go candidates only on separate loopback test ports against an
   anonymous Owner fixture and copied private config schema.
4. Compare status, selected headers, cookies, redirects, HTML/JSON, SSE events,
   uploads, cancellation, shutdown and body-free audit output.
5. Run the real 1440x900 and 390x844 browser matrices against the candidate.
6. Record process memory, cold start, request latency, SSE concurrency and
   source/maintenance cost. Adopt only if the measured benefit exceeds the cost
   of a second language/toolchain.
7. Switch the user service once, remove the Python Gateway production runner in
   the same release, and keep Owner/private data untouched.

Permanent dual production Gateways, a compatibility proxy between them, or a
second copy of auth/audit/package state is not acceptable.

## Go module candidates

| Current boundary | Future Go package |
| --- | --- |
| `gateway_security.py` | `internal/security` |
| `gateway_config.py` | `internal/config` |
| `owner_client.py` | `internal/ownerclient` |
| `workbench_service.py` | `internal/workbench` |
| `control_audit.py` | `internal/audit` |
| `bridge_packages.py` | `internal/bridge` |
| ASGI route modules | `internal/httpapi` |
| `run_asgi.py` | `cmd/faryo-gateway` |

The browser assets should remain the same versioned local files during such a
migration. A backend-language change is not permission for a simultaneous UI
rewrite.

## Adoption gate

Open a Gateway v2 implementation plan only when at least one measured trigger is
present: Python-free distribution is required, current memory/startup violates a
stated deployment budget, or tested concurrency/stream cancellation cannot be
fixed economically in ASGI. Until then, Starlette/Uvicorn is the maintained
production path and Go remains a documented option rather than dormant code.
