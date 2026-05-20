# Faryo Gateway

Faryo Gateway is the public gateway component. It handles the GCP-facing web
gateway, login, route authorization, the handoff workbench, and proxying to
available local execution surfaces.

## Runtime Boundary

Gateway does not own the local tmux execution surface. It only routes to owner
components through configured loopback ports or reverse tunnels.

Runtime configuration defaults to:

```text
~/.faryo/gateway/config/faryo.env
~/.faryo/gateway/config/gateway-auth.json
~/.faryo/gateway/state/gateway-cookie-secret
```

## Local Run

```bash
./scripts/run-gcp-gateway.sh
```

The user-level service template lives at:

```text
deploy/user-systemd/faryo-gateway.service
```
