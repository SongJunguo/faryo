# Faryo Local Tmux Owner

Minimal local web control surface for a tmux-backed Faryo endpoint. Faryo
Gateway reaches this service through path routing or a reverse tunnel. This
service exposes only controlled tmux operations such as `status`, `capture`,
`send`, and `approve`.

## Start

By default, bind only to localhost:

```bash
cd local-tmux-owner
python3 server.py --session tmux --host 127.0.0.1 --port 8765
```

Public access should be exposed through Gateway, not by binding this service to
the public network:

```text
https://<your-faryo-domain>/<route>/
```

Direct local URL printed at startup:

```text
http://<host>:8765/?token=<token>
```

## Security Boundary

- Does not expose arbitrary shell execution.
- Does not provide a general file-write API; uploads are written only to the
  configured Faryo inbox.
- Local file preview is token-protected and limited to supported file suffixes.
- `send` targets the controlled tmux pane and is intended for Codex, Claude,
  shell TUIs, and similar terminal interfaces.
- Should not bind directly to public or LAN addresses.

Codex status reading is optional metadata for model, context, and rate-limit
display. Without it, the service still works as a generic tmux control surface.

## API

- `GET /api/status`
- `GET /api/capture?lines=240`
- `POST /api/send {"text":"..."}`
- `POST /api/approve`
