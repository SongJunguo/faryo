# Faryo Gateway Runbook

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

## Configuration

```bash
cd /path/to/faryo
python3 -m pip install -r apps/gateway/requirements.txt
```

Real runtime config lives under `~/.faryo/gateway/` and is never committed to
Git. Config field names use Faryo naming.

`FARYO_ICP_RECORD` belongs in the same `faryo.env` as the other route settings.
When set, the sign-in and password pages show that record number in the footer,
linked to the official filing site. Leave it unset outside mainland China
hosting. Mainland hosting also needs the filed apex domain to resolve and serve
real content, or the filing can be treated as a shell record.

Each route needs a matching Owner token, a Gateway loopback port, and user auth
binding before it is considered joined. A live tmux session on the endpoint does
not prove the Gateway route is online.

## Start Gateway

```bash
./scripts/run-gcp-gateway.sh
```

Canonical user systemd unit:

```text
faryo-gateway.service
```

## Change Login Password

```text
https://<your-faryo-domain>/password
```

Saving the form updates the Gateway password hash immediately.

## Common States

- Entry page does not open: check Caddy, `faryo-gateway.service`, and
  `127.0.0.1:8780`.
- A route is offline: check that route's upstream Owner `/health`, for example
  the address in `FARYO_HP_OWNER_HOST`.
- PC is offline: check that the real PC/WSL reverse tunnel provides Gateway
  host `127.0.0.1:18765`; do not bridge it to the local Owner port.
- Login works but sending fails: check that the route owner token matches the
  upstream Owner endpoint.
- A user sees a route they should not see: check private route auth bindings.
