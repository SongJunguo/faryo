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

## Math Rendering

The compact Chat view renders supported LaTeX delimiters with KaTeX, including
`$...$`, `$$...$$`, `\(...\)`, and `\[...\]`. Raw view and copied output keep
the original terminal text. KaTeX assets are loaded from jsDelivr; if they are
unavailable, Faryo leaves the original LaTeX visible instead of blocking the
session UI.

For a bound Codex session, compact Chat reads the original message text through
Codex App Server instead of reconstructing Markdown from the tmux screen. Raw
view remains the terminal capture. Owner remembers the thread id observed for a
live pane and falls back to tmux if structured history is unavailable.
Because structured capture does not need a wide terminal, Owner also leaves
Codex pane sizing to tmux and its attached client so TUI lines wrap at the
visible terminal width.

The tmux fallback still handles Codex terminal output, which removes the
backslashes from `\(...\)` and `\[...\]`, by recognizing conservative
math-like parenthetical spans and standalone `[ ... ]` display blocks.

Inline-dollar detection is deliberately conservative so shell variables and
code spans are not treated as formulas. KaTeX runs with `trust: false`.

Run the parser test with:

```bash
node tests/math-render.test.js
```

The optional live-browser test requires a running Owner, a tmux session that
already contains inline and display formulas, and Chrome:

```bash
FARYO_SMOKE_URL='http://127.0.0.1:8765/?token=<token>&session=<session>' \
  node tests/browser-katex-smoke.mjs
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
