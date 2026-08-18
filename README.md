# Faryo

Faryo is a lightweight project and mobile workbench for the same live
`tmux`-backed Codex CLI, Claude Code, or shell session.

Use it to open a project deck, check what an agent is doing, send one
instruction, approve or interrupt work, attach context, and return to the same
desktop terminal session. It is not remote desktop, a hosted IDE, a browser
terminal, or a second AI chat history.

This checkout is a personal fork that tracks the original project while carrying
an unreleased, deployed Codex-focused workbench branch.

- Upstream project: https://github.com/Snailflyer/faryo
- Personal fork: https://github.com/SongJunguo/faryo
- Current fork branch: `main`

## Visual Proof

<p>
  <img src="docs/assets/screenshots/faryo-projects-workbench-redacted.png" alt="Faryo Projects workbench showing project cards, Run, Import, Saved, and Decision Action Watch counts" width="250">
  <img src="docs/assets/screenshots/faryo-project-control-promo.png" alt="Faryo project control surface showing project cards routed to the same tmux session" width="250">
  <img src="docs/assets/screenshots/faryo-project-run-session-main.gif" alt="Faryo project queue Run action opening a live tmux-backed owner session" width="250">
  <img src="docs/assets/screenshots/faryo-same-session-handoff-walkthrough.gif" alt="Faryo same-session handoff walkthrough showing browser workbench and terminal session continuity" width="250">
</p>

The project workbench keeps project state, owner decisions, actions, watch
items, and the live session route in one phone-sized surface. The project-run
walkthrough shows a queued project action opening a live `tmux`-backed owner
session. The same-session handoff walkthrough demonstrates the other half of the
contract: browser actions return to the same live `tmux` session instead of
creating a detached mobile chat or stale terminal copy.

These redacted assets document the core project/session flow. The current fork's
newer Compact Chat, formula rendering, and question-navigation behavior are
described below; the screenshot set has not yet been regenerated for that UI.

## Release and Fork Status

The latest packaged upstream release remains:

- Linux endpoint package: `faryo_1.1.4_all.deb`
- macOS endpoint package: `faryo_1.1.4_macos.tar.gz`
- Release page: https://github.com/Snailflyer/faryo/releases/tag/v1.1.4
- Launch guide: [docs/launch/faryo-1.0.0.md](docs/launch/faryo-1.0.0.md)
- Troubleshooting:
  [docs/launch/faryo-1.0.0.md#troubleshooting--deployment-verification](docs/launch/faryo-1.0.0.md#troubleshooting--deployment-verification)

The personal fork's current branch is deployed from source and is newer than
that package. As of 2026-08-19 it adds:

- Workbench v2 with a stable large composer and responsive Owner/Gateway UI.
- Local CommonMark/GFM/KaTeX/Shiki rendering with no production CDN dependency.
- Incremental Codex rollout history with bounded long-session memory use.
- A fast-scroll question rail for jumping between user turns without reserving
  permanent mobile layout space.
- Confirmed, idempotent web-to-Codex delivery across timeout, restart, and
  session-switch races.
- Agent-reported context use, actual context window, and weekly quota status.

These fork enhancements do not yet have a separate package tag. Installing the
upstream v1.1.4 package alone will not install the unreleased branch features.

## Use It For

- check a long-running terminal AI task from a phone
- send a short follow-up without opening a raw terminal
- approve, interrupt, attach files, or hand off notes
- keep phone and desktop on the same `tmux` session history
- read long Markdown/TeX answers and jump quickly between prior questions
- keep project decisions, action items, and watch items close to the live agent
  session that will execute them

Best-supported path:

```text
Linux endpoint
  + tmux
  + Codex CLI
  + current Chrome or Microsoft Edge on desktop/mobile
```

Current Chrome and Edge have both passed phone and desktop viewport regression.
macOS Owner packaging, iOS Safari, Claude Code session discovery, and generic
shell TUIs remain supported but less polished.

## Quickstart

```bash
curl -LO https://github.com/Snailflyer/faryo/releases/download/v1.1.4/faryo_1.1.4_all.deb
sudo dpkg -i faryo_1.1.4_all.deb
systemctl --user daemon-reload
systemctl --user enable --now faryo-owner-keepalive.timer
mkdir -p ~/.faryo/owner/config
cp /opt/faryo/apps/owner/config/faryo.env.example ~/.faryo/owner/config/faryo.env
$EDITOR ~/.faryo/owner/config/faryo.env
curl --noproxy '*' http://127.0.0.1:8765/health
```

Those package commands install the upstream release. To use the current fork
features, deploy the personal fork's `main` source branch and follow the
[Owner](apps/owner/README.md) and [Gateway](apps/gateway/README.md) component
guides.

- [Troubleshooting & Deployment Verification](docs/launch/faryo-1.0.0.md#troubleshooting--deployment-verification)

Owner should bind to `127.0.0.1`. Public access should go through Gateway, which
injects Owner tokens server-side so browsers do not receive raw Owner tokens.
For a locally managed Cloudflare Tunnel deployment, see the
[Gateway runbook](apps/gateway/runbook.md).

## How It Works

Faryo has two small components:

```text
phone / desktop browser
  -> Faryo Gateway
  -> Owner endpoint
  -> tmux session
  -> Codex, Claude, or shell TUI
```

`apps/gateway` is the public workbench. It owns login, route authorization,
endpoint health, session selection, handoff packages, and proxying to Owner
endpoints. It also renders the project deck, owner decisions, action queues,
watch items, and run handoffs that route approved work back to the selected
live session. Owner tokens are injected server-side and are not exposed to the
browser.

`apps/owner` is the local execution surface. It binds to loopback, controls a
target `tmux` pane, captures terminal output, sends text, uploads attachments to
a configured inbox, and discovers resumable Codex/Claude history. For Codex it
prefers the durable rollout JSONL as the structured Markdown/TeX source, while
keeping tmux capture as live execution evidence and a conservative fallback.

The browser UI stays thin. It renders the workbench, sends commands, uploads
attachments, and switches sessions; it does not replace the terminal runtime.

The endpoint package intentionally includes only Owner. Gateway is source
deployed because it is the public routing and policy layer.

## Endpoint Fit

Faryo is built around a lightweight browser workbench, but endpoints and
browsers do not behave identically.

The most refined path today is:

```text
Linux endpoint
  + tmux
  + Codex CLI
  + current Chrome or Microsoft Edge on desktop/mobile
```

That path has received the most tuning for mobile viewport behavior, PWA use,
structured Markdown/TeX, compact output, command input, attachment handling,
session switching, reliable delivery, and Codex history convergence.

Supported but less heavily polished paths:

- macOS Owner packaging through the launchd installer.
- iOS Safari as a browser surface.
- Claude Code session discovery and compact rendering.
- Generic shell TUIs controlled through tmux capture/send.

These paths are usable, but they may need additional refinement around browser
viewport behavior, backgrounding, paste/input edge cases, compact rendering, and
agent-specific session history mapping.

## Agent Convergence

Faryo treats "session convergence" as the process of making four things line up:

```text
active tmux session
  + visible terminal process
  + agent history record
  + workbench session card
```

Different agents expose different state, so Faryo uses different convergence
rules.

Codex is the most mature integration:

- reads the Codex local session database
- incrementally reads finalized user/assistant messages from rollout JSONL
- filters internal and subagent branches from normal history
- maps every active Codex tmux process, including desktop-started panes, back to
  the current Codex thread
- resumes sessions through `codex resume`
- applies Codex-specific compact output rules
- exposes agent-reported context use/window and provider weekly quota when
  available

Claude is supported with a different path:

- reads Claude project JSONL history
- combines Faryo tmux metadata with live-process/transcript discovery so
  desktop-started Claude panes can also appear as active
- resumes sessions through Claude session IDs
- applies Claude-specific compact output rules

Claude convergence is intentionally separate from Codex convergence. It is not
as heavily tuned yet, especially across macOS, iOS Safari, and less common
Claude output states.

Generic shell sessions are controlled through tmux only. They can be captured,
viewed, and sent input, but they do not have Codex/Claude-style semantic history
convergence.

## UI Interaction Model

Faryo's UI is a workbench, not a document editor or chat clone. The main screen
is optimized for repeated mobile checks and short control actions. Screenshots
near the top are redacted examples.

Core interactions:

- Workbench first: Gateway opens to route status, project cards, all recognized
  active agent tmux panes, a separate 10-record paginated history, and pending
  handoff packages.
- Project deck: project cards keep decisions, action items, watch items,
  stage goals, and owner review close to the session that can execute them.
- Run queue: approved project actions can be dispatched back to the live Faryo
  session instead of becoming a disconnected task list.
- Session cards: each card represents a resumable agent session or active tmux
  session. Opening a card routes the browser to that endpoint and session.
- Compact Chat: the default view renders stable user/assistant blocks through a
  local AST pipeline with CommonMark, GFM tables, KaTeX math, and lazy Shiki
  highlighting. Raw terminal evidence remains separately available.
- Long history: formula-heavy answers do not hide all prior turns. The recent
  window targets 12 complete turns within bounded rollout-tail and character
  budgets.
- Question navigation: a right-edge marker rail appears only after a fast
  wheel/swipe, then auto-hides. It jumps between visible user questions without
  changing the mobile content width.
- Raw output: full terminal capture is available when exact terminal evidence is
  needed.
- Latest control: when the user scrolls up, live refreshes preserve the reading
  position; the latest control returns to the newest output on demand.
- Live tmux: transient execution output is kept in a separate collapsible panel
  whose inner scroll position survives refreshes.
- Composer: the bottom input sends text into the active tmux pane. It works well
  with mobile keyboards and system dictation, keeps its expanded geometry after
  blur, and preserves drafts on ambiguous or failed sends.
- Delivery confirmation: browser retries keep the original session and message
  identity. Owner confirms paste/submit evidence, persists minimal idempotency
  state without message bodies, and does not turn an ambiguous 504 into a false
  success.
- Attachments: images and files can be uploaded into the configured inbox and
  referenced in the active session.
- Handoff packages: prompts, notes, screenshots, and files can be picked up and
  injected into a selected session.
- Agent controls: interrupt, approve, page up/down, resume, and close actions
  are exposed as direct controls instead of hidden terminal shortcuts.
- Thin state: the browser remembers display preferences, but the work session
  itself remains in tmux and the agent history store.
- Runtime status: context used/window and weekly quota are shown when Codex
  reports them; missing metadata does not disable the control surface.

The UI intentionally avoids heavyweight panels and IDE-style layout. It should
feel fast enough to open, inspect, dictate a command, attach context, and leave.

## Core Features

- Project workbench with project cards, owner decisions, action items, watch
  items, stage goals, and run queue handoff.
- Mobile-first PWA workbench with compact and raw terminal views.
- Local CommonMark/GFM/KaTeX/Shiki rendering with safe fallbacks.
- Incremental, bounded Codex rollout history and fast-scroll question navigation.
- Shared session history across phone and desktop through the same `tmux`
  session.
- Confirmed, idempotent delivery with draft protection and cross-session
  isolation.
- Codex and Claude session discovery, resume, interrupt, and approval controls.
- Multi-endpoint routing for local machines and cloud endpoints.
- Handoff packages for prompts, notes, images, and files.
- Lightweight attachment handling with local inbox paths.
- No browser automation, no remote desktop stack, and no database server in the
  runtime path.

## Current Fork Validation

The deployed personal-fork `main` branch was revalidated on
2026-08-19 with privacy-safe fixtures:

- Release checks plus 56 Owner and 44 Gateway Python tests pass.
- A 20-message browser delivery matrix covers short, Chinese, multiline,
  Markdown, TeX, attachment, offline/background recovery, and failed-draft
  behavior.
- A separate two-session browser test proves retry and delayed responses stay
  bound to the original target session.
- 390x844 mobile Chrome and 1440x900 desktop Edge pass the 13-question rail,
  keyboard navigation, fast-scroll reveal, auto-hide, stable live append, local
  Markdown/KaTeX/Shiki, and no-horizontal-overflow checks.
- A real structured Codex session exposes 12 question markers in both mobile and
  desktop browser checks without printing or saving conversation text.
- Cold initialization of a 263.3 MiB rollout remains bounded at about 0.0025 s
  and 41.5 MiB process peak RSS on the validated Linux host.
- Owner/Gateway health, public Access redirection, and before/after dimensions
  for five active Codex tmux sessions pass after deployment.

The detailed, continuously updated evidence lives in the
[UI plan](docs/plans/deepseek-inspired-ui-plan.md) and
[Codex reliability plan](docs/plans/codex-reliability-hardening-plan.md).

## Current Fork Documentation

- [Owner runtime and Compact Chat](apps/owner/local-tmux-owner/README.md)
- [Gateway setup](apps/gateway/README.md) and [runbook](apps/gateway/runbook.md)
- [Gateway security hardening](docs/gateway-security-hardening.md)
- [Personal fork roadmap](docs/plans/personal-fork-roadmap.md)
- [All implementation plans](docs/plans/README.md)

## Runtime State

Source code lives in this repository. Runtime configuration and secrets do not.

```text
~/.faryo/
  gateway/
    config/faryo.env
    config/gateway-auth.json
    state/
    logs/
  owner/
    config/faryo.env
    data/
```

Example configuration files live under:

```text
apps/gateway/config/faryo.env.example
apps/owner/config/faryo.env.example
```

## Requirements

Owner endpoint:

- Python 3.11 or newer
- `tmux`
- `curl`
- `zsh`
- optional: `git`, `openssh-client`, Codex CLI, Claude Code

Gateway:

- Python 3.11 or newer
- `bcrypt`
- a public HTTPS edge such as Cloudflare Tunnel, Caddy, or nginx

## Packaging

Endpoint releases are built from `apps/owner/RELEASE`.

```bash
scripts/package-client.sh check
scripts/package-client.sh release
```

The release target builds:

```text
dist/faryo_<version>_all.deb
dist/faryo_<version>_macos.tar.gz
dist/SHA256SUMS
```

Install the Linux endpoint package on an Owner machine:

```bash
sudo dpkg -i dist/faryo_<version>_all.deb
systemctl --user daemon-reload
systemctl --user enable --now faryo-owner-keepalive.timer
```

After configuration, the Owner health and status endpoints should answer on
loopback. `releaseVersion` in `/api/status` is the endpoint version to use for
upgrade acceptance.

## Repository Layout

```text
apps/gateway/       Public gateway, login, routing, and handoff workbench
apps/owner/         Local tmux-backed execution endpoint
apps/shared/        Shared state and browser appearance helpers
docs/               Product, launch, release, UI, and client sync notes
deploy/             Runtime unit templates
scripts/            Packaging, endpoint install, and verification tools
tools/              Development-only bundle builders and checks
```

## Security Model

Faryo is designed for a trusted operator running their own endpoints.

- Owner should bind only to `127.0.0.1`.
- Public access should go through Gateway.
- Gateway itself should also bind to loopback when reached through a local
  reverse proxy or outbound tunnel.
- Tokens, password hashes, cookie secrets, and runtime env files are private
  runtime state.
- File preview and attachment APIs are token-protected and constrained by
  supported file types.
- Gateway bridge URL attachments reject private, loopback, link-local,
  multicast, reserved, and unresolved hosts.
- Internet-facing deployments should place an identity-aware layer such as
  Cloudflare Access in front of the complete Gateway hostname, use exact
  identities or a small managed group, and configure no broad bypass.
- Access session duration/MFA and the inner Faryo cookie are independent,
  operator-selected controls. A tunnel by itself is transport, not
  authentication.
- Faryo can steer an agent running with the permissions of the Owner OS user;
  treat it as a remote administration surface, not an ordinary content site.

See `SECURITY.md` and
[Gateway Security Hardening](docs/gateway-security-hardening.md) for disclosure
and deployment guidance.

## License

Faryo is released under the MIT License. See `LICENSE`.
