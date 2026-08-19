# Faryo Owner Runbook

## Configuration

The commands below assume the component directory. The source checkout path
depends on deployment.

```bash
cd /path/to/faryo/apps/owner
```

Real runtime config lives under `~/.faryo/owner/` and is never committed to Git.
Config field names use Faryo naming.

The default product data root is `~/.faryo/owner/data`. Startup scripts ensure
these directories exist:

```text
~/.faryo/owner/data/inbox
~/.faryo/owner/data/artifacts
~/.faryo/owner/data/cache
~/.faryo/owner/data/logs
```

## Start Owner

```bash
./scripts/start-web-owner.sh
```

## Stop Owner

```bash
./scripts/stop-web-owner.sh
```

## Status

```bash
./scripts/status.sh
```

## Deployment Acceptance

Use the read-only diagnostic after configuring or updating the source checkout:

```bash
./scripts/diagnose-owner-gateway.sh
```

Read the result as layers, not one generic online/offline state:

- Owner prepared: source scripts and `~/.faryo/owner/config/faryo.env` exist.
- Owner reachable locally: `/health` on `127.0.0.1` returns OK.
- Owner authenticated: `/api/status` returns `releaseVersion` with the Owner
  token.
- Gateway route prepared: Gateway config contains the route and matching Owner
  token.
- Reverse tunnel prepared: the endpoint has a configured remote loopback port.
- Visible session usable: a real tmux session can be captured through Owner.

For tunneled endpoints, run `scripts/verify-reverse-tunnel.sh` when the
diagnostic shows the tunnel config is present but the Gateway still reports the
route offline.

## Local Smoke Test

```bash
./scripts/smoke-test.sh
```

## Reverse Tunnel Verification

```bash
./scripts/verify-reverse-tunnel.sh
```

This check logs in to the Gateway host over SSH, calls the remote loopback
mapping for this endpoint with the owner token, and validates endpoint identity
through `/api/status`. Endpoints without a reverse tunnel do not need this
check.

## Common States

- `tmux OK`: the target tmux session exists and Owner can control its target
  pane.
- Web opens but cannot send: check the owner token, target tmux session, and
  current pane.
- Gateway shows this endpoint offline: check local Owner health, the reverse
  tunnel, `scripts/verify-reverse-tunnel.sh`, and the Gateway-side loopback
  port.
- Owner is directly visible from the public internet: this is wrong. Bind Owner
  to `127.0.0.1` and expose it only through Gateway.

## Android PWA Orientation

If a WebAPK bypasses the system rotation setting, let the system window policy
control orientation:

```bash
adb shell cmd window set-ignore-orientation-request true
adb shell settings put system accelerometer_rotation 1
adb shell cmd window user-rotation free
```

Temporary portrait lock:

```bash
adb shell settings put system accelerometer_rotation 0
adb shell cmd window user-rotation lock 0
```
