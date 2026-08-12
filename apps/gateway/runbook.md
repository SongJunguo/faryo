# Faryo Gateway Runbook

## Deployment Boundary

The recommended single-machine path is:

```text
phone browser
  -> public HTTPS edge
  -> outbound tunnel
  -> Faryo Gateway 127.0.0.1:8780
  -> Faryo Owner 127.0.0.1:8765
  -> tmux session
```

Neither Owner nor Gateway needs a public listening socket. Gateway login is
mandatory on the public path; the Owner token stays in private Gateway runtime
configuration and is injected server-side.

## Public Entry

```text
https://<your-faryo-domain>/
```

Public access enters the Faryo login page first. After login, the user lands on
the workbench and opens concrete execution sessions through route paths such as
`/hp/?session=...`, `/pc/?session=...`, and `/txy/?session=...`.

Bare `/hp/`, `/pc/`, and `/txy/` paths are not user entry points. Available
routes come from the current user config. Owner tokens are injected only by
Gateway. Route status comes from each route's real `/health`; do not fake a
route as online by bridging another port.

## Prepare Python

```bash
cd /path/to/faryo
conda env list
conda create -n faryo python=3.13 -y
conda run -n faryo python -m pip install -r apps/gateway/requirements.txt
FARYO_PYTHON="$(conda run -n faryo python -c 'import sys; print(sys.executable)')"
"$FARYO_PYTHON" -c 'import bcrypt; print(bcrypt.__version__)'
```

Python 3.13 is supported by the current Gateway dependency set. Reuse an
existing suitable environment instead of recreating it.

## Initialize One Local Route

Owner must already have a private mode-`600` environment file containing
`FARYO_OWNER_TOKEN` and must listen on loopback. Then run from the repository
root:

```bash
FARYO_PYTHON="$FARYO_PYTHON" \
FARYO_GATEWAY_ROUTE=txy \
./apps/gateway/scripts/init-local-gateway.sh

./apps/gateway/scripts/install-user-service.sh
systemctl --user is-active faryo-gateway.service
curl --noproxy '*' -fsS http://127.0.0.1:8780/login >/dev/null
```

Real runtime config lives under `~/.faryo/gateway/` and is never committed to
Git. Config field names use Faryo naming.

The initializer creates only the selected route. Disabled HP or PC routes do
not need placeholder tokens. It also keeps an existing `gateway-auth.json`, so
routine reconfiguration cannot silently restore an old login password. To
perform an intentional credential reset, set `FARYO_GATEWAY_RESET_AUTH=1` and
read the newly generated mode-`600` initial-password file.

The initializer sets `FARYO_TXY_MAX_RUNNING=8` for the local TXY route. This is
the number of live agent TUIs that may remain open, including idle TUIs waiting
for input; it is not the number of history cards. Per-route values must be from
1 through 32. Change the private env value and restart
`faryo-gateway.service` to use another limit.

`FARYO_ICP_RECORD` belongs in the same `faryo.env` as the other route settings.
When set, the sign-in and password pages show that record number in the footer,
linked to the official filing site. Leave it unset outside mainland China
hosting. Mainland hosting also needs the filed apex domain to resolve and serve
real content, or the filing can be treated as a shell record.

Each enabled route needs a matching Owner token, a Gateway loopback port, and
user auth binding before it is considered joined. A live tmux session on the
endpoint does not prove the Gateway route is online.

## Add an Existing Cloudflare Tunnel Route

This path assumes a locally managed named tunnel already exists. A single
tunnel may route multiple hostnames to different local services. Keep the final
`http_status` catch-all in the ingress file.

```bash
cloudflared tunnel route dns <tunnel-name-or-uuid> faryo.example.com

FARYO_PYTHON="$FARYO_PYTHON" \
./apps/gateway/scripts/add-cloudflare-ingress.sh \
  faryo.example.com http://127.0.0.1:8780

cloudflared tunnel --config ~/.cloudflared/config.yml ingress validate
systemctl --user restart <your-cloudflared-service>
```

The ingress helper validates the hostname, accepts only a loopback HTTP target,
writes a timestamped private backup, and validates the candidate config before
installing it. It does not create DNS or restart a tunnel service for you.

Cloudflare Tunnel and Cloudflare Access are separate controls. The tunnel makes
the service reachable; it does not automatically add an Access policy. Because
Gateway can steer terminal-backed agents, an Internet-facing deployment must
protect the entire hostname with an Access application (or equivalent), an
exact identity or group allow rule, and MFA. Do not use a broad `Everyone` or
`Bypass` policy. Keep Faryo's own form login as the independent application
layer behind Access.

## First Login

Read the generated password locally without copying it into shell history:

```bash
sed -n '1p' ~/.faryo/gateway/config/initial-password
```

Open `https://faryo.example.com/`, sign in as `faryo`, then change the password
at `/password`. After confirming the new password works in a private browser
window, delete the now-stale initial-password file. Gateway runtime uses the
password hash in `gateway-auth.json`, not the plaintext file.

Changing the password invalidates older Faryo sessions. Browser sessions are
host-only, strict same-site cookies with a 12-hour absolute lifetime.

## Verification

Check the two local boundaries and the public unauthenticated boundary:

```bash
systemctl --user is-active faryo-gateway.service
curl --noproxy '*' -fsS http://127.0.0.1:8765/health
curl --noproxy '*' -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8780/login
curl -sS -o /dev/null -w '%{http_code} %{ssl_verify_result}\n' https://faryo.example.com/
ss -ltn | grep -E '127\.0\.0\.1:(8765|8780)'

./apps/gateway/scripts/verify-public-access.sh \
  https://faryo.example.com/
```

The public verifier sends no password, Cookie, Owner token, or Gateway token. It
does not print the hostname. `access=PASS origin-login=BLOCKED` means a fresh
request was redirected to Cloudflare Access before reaching Faryo. An
`access=MISSING origin-login=EXPOSED` result exits with status `3` and means the
public request reached Faryo's own login boundary directly. An inconclusive
response is never treated as a pass.

This check proves the unauthenticated outer gate is present. It cannot prove
which identities are allowed, that MFA is required, or that no `Bypass` policy
exists; verify those policy settings in the dashboard and complete one real
private-browser login before declaring the Access layer ready.

Expected results:

- Owner health succeeds and both local services listen only on `127.0.0.1`.
- Gateway login returns `200`.
- Public TLS verification is `0`, and an unauthenticated browser receives the
  Access identity challenge before the Faryo login page. Seeing Faryo's login
  page directly from a fresh public client means Access is not protecting the
  hostname.
- A logged-in route can render Markdown and KaTeX without CDN access, updates
  without a manual refresh, and submits each prompt exactly once.
- Existing tunnel hostnames still route to their original services.
- Public state-changing Owner requests without the Gateway CSRF header return
  `403`, while the authenticated web client can still send, upload, interrupt,
  and approve normally.

If local DNS briefly reports that a newly created hostname does not exist,
compare an external resolver before changing the tunnel. A local proxy or DNS
cache may retain the pre-creation negative answer until its TTL expires.

## Service Operation

Canonical user systemd unit:

```text
faryo-gateway.service
```

Useful commands:

```bash
systemctl --user status faryo-gateway.service
journalctl --user -u faryo-gateway.service --since today
systemctl --user restart faryo-gateway.service
```

Logs must not contain login passwords, Owner tokens, query-string tokens, or
private conversation text.

## Change Login Password

```text
https://<your-faryo-domain>/password
```

Saving the form updates the Gateway password hash immediately.

## Rollback

To remove public Faryo access without affecting Owner:

1. Restore the timestamped `~/.cloudflared/config.yml.backup-*` created by the
   ingress helper, or remove only the Faryo hostname block.
2. Validate the resulting ingress config and restart the existing cloudflared
   user service.
3. Remove the Faryo DNS route when it is no longer needed.
4. Optionally stop Gateway with
   `systemctl --user disable --now faryo-gateway.service`.

Do not stop Owner or delete `~/.faryo/owner` as part of Gateway rollback.

## Common States

- Entry page does not open: check the HTTPS edge or tunnel,
  `faryo-gateway.service`, and `127.0.0.1:8780`.
- A route is offline: check that route's upstream Owner `/health`, for example
  the address in `FARYO_HP_OWNER_HOST`.
- HP or PC is offline: check that the endpoint's real reverse tunnel provides
  its Gateway host loopback port (`127.0.0.1:18766` for HP, `127.0.0.1:18765`
  for PC); do not bridge either to the local Owner port.
- Login works but sending fails: check that the route owner token matches the
  upstream Owner endpoint.
- A user sees a route they should not see: check private route auth bindings.
