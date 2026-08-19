# Gateway Security Hardening

Faryo Gateway is not an ordinary content site. It can send input to terminal
sessions, approve supported actions, upload files, and start or resume coding
agents. Treat it as a remote administration surface.

## Threat model

If an attacker obtains a valid Gateway session, the impact is bounded by the
authority of the agent and operating-system user behind Owner. That may include
source trees, SSH or Git credentials, browser profiles, session cookies, and
other user-readable files. Browser password stores may have additional keyring
protection, but they must not be assumed safe after host-user compromise.

Faryo deliberately does not rewrite an operator's Codex permission policy.
Operators who choose approval-free or unsandboxed Codex sessions keep that
workflow, and must compensate with stronger identity and host isolation.

## Required layers for public access

1. Bind Owner and Gateway only to loopback or a private interface. Never expose
   Owner directly.
2. Publish Gateway through an outbound tunnel or hardened reverse proxy without
   opening the local service port to the Internet.
3. Protect the complete public hostname, including API and static paths, with an
   identity-aware proxy such as Cloudflare Access. Allow only exact identities
   or a small managed group, choose the Access session lifetime and MFA posture
   explicitly, and configure no broad bypass. WebAuthn/passkeys remain the
   preferred higher-assurance option, but independent MFA is an operator choice
   rather than a Faryo runtime requirement. A lower-friction deployment may use
   a longer Access session with independent MFA disabled only while retaining
   the exact identity allowlist and the separate Faryo password layer.
4. Keep Faryo's password login as a separate inner layer. Use a unique password
   of at least 16 characters and remove any stale generated plaintext password
   file after a successful password change.
5. Apply login rate limiting at the edge. Gateway's local limiter is a fallback,
   not protection against distributed attempts or process restarts.
6. For the strongest blast-radius reduction, run Owner and its agents under a
   dedicated OS account, VM, or container that cannot read personal browser and
   SSH profiles.

A Cloudflare Tunnel only carries traffic; it does not create an Access policy.
A fresh public browser should encounter the identity-aware proxy before it can
reach Faryo's sign-in form.

## Application controls

Gateway implements the following inner controls:

- bcrypt password hashes and generic login failures;
- an HMAC-signed `__Host-` session cookie with `Secure`, `HttpOnly`,
  `SameSite=Strict`, no `Domain`, and a server-enforced absolute limit; the
  default is 12 hours and private `FARYO_GATEWAY_SESSION_HOURS` configuration is
  bounded to `1`–`168`;
- password-change session invalidation;
- session-bound CSRF headers for every browser state-changing API, including
  requests proxied to Owner; the CSRF header is removed before proxying;
- client-IP login limiting based on Cloudflare's single-value
  `CF-Connecting-IP` only when Gateway's direct peer is loopback, never on the
  user-controlled first entry of `X-Forwarded-For`;
- a nonce-based Content Security Policy, framing denial, no referrer leakage,
  restricted browser permissions, HSTS, and MIME sniffing protection;
- server-side Owner-token injection, so public browser URLs do not contain Owner
  tokens.
- a best-effort control audit at private Gateway state: mode `600`, seven-day or
  5000-row retention, per-user/route read scope, HMAC-pseudonymous targets, and
  no prompt, answer, title, cwd, raw session ID, token, Cookie, CSRF value, or IP
  history;
- separate sign-out and revoke-all-inner-sessions actions. Revocation advances
  the account auth epoch and does not close Codex or tmux.

## Residual risks

- The built-in login limiter is in memory and resets with the Gateway process.
- The Faryo cookie has an absolute timeout but no separate idle timeout.
- CSP is defense in depth, not a substitute for output encoding and safe
  Markdown handling.
- A valid high-privilege session can intentionally perform high-impact actions.
- Identity-aware access, its allowlist, session lifetime, and MFA posture are
  external deployment controls and cannot be inferred merely from a running
  tunnel.
- Disabling independent MFA reduces login friction but makes the exact Access
  allowlist, protected identity-provider account, inner Faryo password, and
  host isolation more important.
- Deployment checks must verify the operator-selected MFA posture; they must not
  silently enable independent MFA or treat an explicitly disabled posture as a
  configuration drift failure.
- Running agents as the same desktop user leaves personal data within their
  potential read authority. Network authentication reduces likelihood; only OS
  or VM/container isolation reduces that blast radius.

## Verification checklist

- Owner and Gateway listeners are loopback-only.
- Public TLS certificate verification succeeds.
- A fresh public browser receives the identity-aware proxy challenge before the
  Faryo login form.
- `apps/gateway/scripts/verify-public-access.sh https://faryo.example.com/`
  reports `access=PASS origin-login=BLOCKED`; it never accepts an unknown
  response as proof of Access.
- Access allows only intended identities, uses the deliberately selected
  session lifetime and MFA posture, and has no `Everyone` or `Bypass` rule.
- Faryo login produces a `__Host-` Secure/HttpOnly/Strict cookie and old sessions
  stop working after a password change.
- Browser write operations work, while the same authenticated POST without a
  valid CSRF header returns `403`.
- Private control audit is mode `600`; a denied fixture appears with an empty or
  HMAC target, while its request body and raw identifier do not appear in the
  file or Security activity API.
- `Sign out this device` and `Revoke signed-in devices` remain distinct, and a
  revoke test invalidates inner cookies without changing tmux sessions.
- Content Security Policy is present and the browser console shows no blocked
  first-party application assets.
- Runtime config, password hashes, tunnel credentials, tokens, domains, session
  identifiers, and private conversations are absent from Git and logs.
