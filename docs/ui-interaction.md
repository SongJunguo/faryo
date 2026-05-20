# Faryo UI Interaction Model

Faryo is designed as a mobile-first workbench for terminal AI sessions.

The UI should feel closer to a cockpit than a chat app. It gives the user quick
access to route health, sessions, output, input, handoff packages, attachments,
and agent controls while leaving the terminal runtime in `tmux`.

Screenshots below are redacted examples. Session titles and project discussion
content are replaced with representative labels.

<p>
  <img src="assets/screenshots/faryo-gateway-workbench-redacted.png" alt="Faryo Gateway workbench showing route health, handoff package, launch shortcuts, and session history" width="280">
  <img src="assets/screenshots/faryo-owner-session-redacted.png" alt="Faryo Owner session view showing compact output, agent metadata, approval controls, and composer" width="280">
</p>

## Surfaces

### Gateway Workbench

The Gateway workbench is the first authenticated surface.

It shows:

- available routes such as HP, PC, and cloud endpoints
- route health
- active and recent sessions
- pending handoff packages
- new-session entry points
- account and install controls

The workbench is for choosing where work should continue. It should not behave
like a file manager or a general dashboard.

### Owner Session View

The Owner session view is the control surface for one tmux-backed session.

It shows:

- owner/route label
- current topic/session title
- model and context metadata when available
- git status when available
- compact or raw terminal output
- attachment preview
- composer
- agent controls

## Output Modes

### Compact

Compact mode is the default mobile reading mode. It turns noisy terminal output
into readable blocks for common Codex and Claude states.

Compact mode is agent-specific:

- Codex rules are the most mature.
- Claude rules exist but need more tuning across platforms and output states.
- Generic shell output falls back to terminal-oriented rendering.

### Raw

Raw mode keeps the terminal evidence closer to its original form. It is useful
when the user needs exact command output, logs, or terminal formatting.

## Input

The composer sends text into the active tmux pane.

Design expectations:

- mobile keyboard and system dictation should work naturally
- sending one short instruction should be fast
- long prompts should remain possible
- attachments should become explicit file references in the session

Faryo does not own speech-to-text. It accepts the text produced by the user's
preferred input method.

## Session Selection

Session cards represent active or resumable work. A session card is not a copy
of a chat; it is a pointer back to terminal-backed state.

Codex cards converge through Codex history and the active tmux process. Claude
cards converge through Claude history and Faryo tmux metadata.

## Handoff Packages

Handoff packages carry work material into a target session.

A package can include:

- prompt
- notes
- screenshots
- files
- intent
- context

Packages can be created from Gateway, received through the MCP bridge, and
injected into a selected session.

## Control Actions

Faryo exposes common terminal-agent controls directly:

- send
- interrupt
- approve
- page up/down
- resume
- close session
- attach file or image

These controls keep mobile work practical without requiring the user to remember
terminal shortcuts on a phone.

## Platform Maturity

The most refined UI path is Chrome/Android Chrome PWA with a Linux endpoint and
Codex CLI.

Supported but less tuned:

- iOS Safari
- macOS Owner endpoint
- Claude Code compact states
- generic shell TUIs

Future UI work should focus on viewport behavior, background/foreground resume,
keyboard/paste edges, and better Claude-specific compact rendering.
