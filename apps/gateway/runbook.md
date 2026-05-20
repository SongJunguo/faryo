# Faryo Gateway Runbook

## Public Entry

```text
https://<your-faryo-domain>/
```

Public access enters the Faryo login page first. After login, the user lands on
the workbench and opens concrete execution sessions through route paths such as
`/hp/?session=...`, `/pc/?session=...`, and `/gcp/?session=...`.

Bare `/hp/`, `/pc/`, and `/gcp/` paths are not user entry points. Available
routes come from the current user config. Owner tokens are injected only by
Gateway. Route status comes from each route's real `/health`; do not fake a
route as online by bridging another port.

## Configuration

```bash
cd /path/to/faryo/apps/gateway
python3 -m pip install -r requirements.txt
```

Real runtime config lives under `~/.faryo/gateway/` and is never committed to
Git. Config field names use Faryo naming.

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
  HP at `127.0.0.1:18766`.
- PC is offline: check that the real PC/WSL reverse tunnel provides Gateway
  host `127.0.0.1:18765`; do not bridge it to GCP `127.0.0.1:8765`.
- Login works but sending fails: check that the route owner token matches the
  upstream Owner endpoint.
- A user sees a route they should not see: check private route auth bindings.
