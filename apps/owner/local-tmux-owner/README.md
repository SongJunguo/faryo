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
the original terminal text. KaTeX 0.18.4, its fonts, and its MIT license are
vendored under `static/vendor/katex`, so formula rendering does not depend on a
CDN or a permissive external-resource CSP. If the local renderer is unavailable,
Faryo still leaves the original LaTeX visible instead of blocking the session UI.

For a bound Codex session, compact Chat reads the original message text through
Codex App Server instead of reconstructing Markdown from the tmux screen. Raw
view remains the terminal capture. Owner remembers the thread id observed for a
live pane and falls back to tmux if structured history is unavailable.
Because structured capture does not need a wide terminal, Owner also leaves
Codex pane sizing to tmux and its attached client so TUI lines wrap at the
visible terminal width.

Compact Chat renders structured messages with the locally vendored
`markdown-it` 14.3.0 library. Raw HTML and `data:` URLs are disabled, unsafe
link protocols retain markdown-it's default rejection, and external links open
with `noopener noreferrer`. Math spans are protected before Markdown parsing
and rendered by KaTeX afterwards, while fenced and inline code stays literal.

For Codex sessions, finalized chat remains sourced from structured App Server
thread data. A separately running Codex TUI does not publish its in-progress
item deltas to this Owner process, so while a turn is active Compact Chat adds
a short, transient, redacted tmux tail. The live tail disappears when the turn
finishes and the structured Markdown/KaTeX message takes over.

Browser sends use a client-generated message id. Owner confirms that tmux
accepted the paste and that the Codex composer consumed Enter before returning
success. A delayed second Enter is attempted only while the same draft is
still present. Network retries are idempotent, and a failed/unconfirmed send
keeps the browser draft instead of clearing it. If the TUI already contains a
different desktop draft, Owner returns `409` rather than overwriting it.

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
- `GET /api/events?lines=320` (SSE structured capture plus transient live tail)
- `POST /api/send` with `text`, `session`, and optional `clientMessageId`
- `POST /api/approve`
