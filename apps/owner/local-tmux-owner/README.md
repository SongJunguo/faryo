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

## Markdown and Math Rendering

Compact Chat uses one local AST pipeline:

```text
micromark -> mdast -> GFM/math nodes -> safe HTML -> KaTeX
```

It supports CommonMark, GFM tables/task lists/strikethrough/autolinks, CJK
punctuation next to strong emphasis, and `$...$`, `$$...$$`,
`\\(...\\)`, and `\\[...\\]` math. Tables, formulas, and code are parsed as
different node types, so TeX inside code stays literal and long formulas scroll
inside their own container instead of narrowing the page.

Settled fenced code uses a local Shiki JavaScript-regex engine. TypeScript,
shell, and JSON are available at startup; research and systems languages such
as Python, LaTeX, Lean, MATLAB, C/C++, Rust, and SQL load only when used. A
missing grammar or failed chunk keeps the escaped plain-code fallback. The
generated `highlight/manifest.json` is checked by release packaging, so lazy
chunks cannot be silently omitted.

The math delimiter and CJK extensions are adapted from a pinned DeepSeek
Harness commit under MIT. Exact sources, versions, and license texts are under
`static/vendor/markdown-ast`. KaTeX CSS and fonts remain under
`static/vendor/katex`. All runtime assets are local; production needs no Node
process, CDN, or permissive external-resource CSP. Raw HTML is escaped, links
and images pass protocol allowlists, and KaTeX runs with `trust: false`.

For a bound Codex session, Compact Chat reads original finalized message text
through Codex App Server. While a message is incomplete, the streaming grammar
keeps math literal; the finalized structured message switches atomically to the
full GFM/math grammar. Raw remains terminal evidence. If structured history is
unavailable, the tmux fallback deliberately avoids guessing damaged formula
boundaries and displays a warning.

Compact Chat plans stable content keys for top-level conversation blocks and
reconciles those elements instead of replacing the entire output DOM. All but
the changing two-block tail are marked stable, and a 256-entry in-memory LRU
cache avoids reparsing unchanged Markdown. The cache is cleared on session
switches and highlighter revisions; it is never persisted to browser storage.
Live tmux remains outside that frozen history and restores its own scroll
snapshot before the next paint.

Owner does not resize tmux or the Codex/Claude TUI. Browser sends retain the
client message id, confirmed Enter delivery, idempotent retries, draft
preservation on failure, and conflict response when a different desktop draft
already occupies the TUI composer.

Rebuild and test the committed browser bundle from the repository root with:

```bash
cd tools/markdown-engine
npm ci
npm run build
npm test
```

The dependency-free release test is:

```bash
node apps/owner/local-tmux-owner/tests/markdown-ast-bundle.test.js
```

The optional live-browser test requires a running Owner and Chrome:

```bash
FARYO_SMOKE_URL='http://127.0.0.1:8765/?token=<token>&session=<session>' \
  node apps/owner/local-tmux-owner/tests/browser-katex-smoke.mjs
```

The anonymous delivery matrix starts an isolated loopback Owner and temporary
tmux receiver, sends 20 exact-content short/Chinese/multiline/Markdown/TeX
messages, uploads one Markdown attachment, verifies network/background catch-up
without reload, checks failed-draft preservation, and removes all test state:

```bash
FARYO_DELIVERY_PYTHON=/path/to/project/python \
  apps/owner/local-tmux-owner/tests/browser-delivery-matrix.sh
```

Set `FARYO_DELIVERY_URL_TEMPLATE` with a literal `{session}` placeholder to run
the same non-attachment matrix against an already deployed Owner. The URL is
consumed as private runtime input and is never printed.

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
