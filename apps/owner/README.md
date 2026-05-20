# Faryo Owner

Faryo Owner is the local execution component. It exposes a loopback-only web
control surface for tmux-backed work sessions and is reached through Faryo
Gateway or a configured reverse tunnel.

## Runtime Boundary

Owner does not own public login, domain routing, Caddy, or the gateway workbench.
It should bind only to `127.0.0.1`.

Runtime configuration defaults to:

```text
~/.faryo/owner/config/faryo.env
~/.faryo/owner/data/
```

## Local Run

```bash
./scripts/start-web-owner.sh
```

The user-level timer template lives at:

```text
deploy/user-systemd/faryo-owner-keepalive.timer
```

## Package Install

Linux endpoint packages install Owner under `/opt/faryo` and provide the user
systemd keepalive timer:

```bash
sudo dpkg -i faryo_<version>_all.deb
systemctl --user daemon-reload
systemctl --user enable --now faryo-owner-keepalive.timer
```

Use `/health` for liveness and `/api/status` for authenticated runtime checks.
The status payload includes `releaseVersion` for endpoint upgrade acceptance.
