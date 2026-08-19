# Faryo UI Interaction Model

This document describes the maintained Ubuntu/Linux Codex UI in the current
personal fork. It is an interaction contract, not a record of inherited platform
or package capabilities.

## Product Shape

Faryo has two browser surfaces:

1. **Gateway workbench** selects an active or resumable Codex session and applies
   the public authentication/routing boundary.
2. **Owner session view** reads and controls one existing tmux-backed Codex
   session without changing its terminal dimensions.

The browser is a thin control surface. Durable conversation history belongs to
Codex, live terminal state belongs to tmux, and runtime secrets stay below
`~/.faryo/`.

## Gateway Workbench

The authenticated Gateway home page keeps two session regions separate:

- **Active Sessions** lists every recognized live Codex tmux pane, including
  sessions started directly on the desktop.
- **Session History** lists inactive resumable threads, uses server-backed pages
  of 10 records, and supports Previous/Next plus direct page-number jumps.

Only sessions created and stamped by Faryo expose remote Close. Desktop-created
tmux sessions can be opened but are not remotely destroyed.

`Start Codex` is successful only after Owner observes a live Codex process in
the new managed tmux. A missing CLI, invalid configured path, unavailable shell,
or readiness timeout returns an explicit error and removes the partial session.
Managed sessions use the first free `faryoN` name. The start flow asks for the
workstation, then opens a directory-only browser at the most recent cwd. It
shows the current path, parent, configured roots, recent locations and child
folders; the selected canonical path is signed and revalidated by Owner.

Gateway route labels come from runtime configuration. Public browser requests
never receive raw Owner tokens; Gateway injects them while proxying.

## Owner Session View

The Owner page contains:

- a Faryo logo link back to the Gateway home page;
- workstation/session title and session switcher;
- agent-reported context used/window and weekly quota when available;
- git status and structured-source/connection details;
- Compact Chat and Raw output modes;
- attachments and a stable multiline composer;
- approve, interrupt, terminal navigation, refresh, and return-to-latest
  controls.

Opening menus, details, Raw mode, or the question rail must never resize tmux or
the Codex TUI.

Header actions remain deliberately separate: the logo returns home, the title
folds/unfolds the header, the folder switches sessions, and the sliders open
session details. Returning home uses same-origin `/` without carrying the Owner
token or selected-session query.

## Compact Chat

Compact Chat is the default reading mode. It renders finalized Codex rollout
messages as stable user/assistant blocks through the local Markdown AST, GFM,
KaTeX, and Shiki pipeline.

Rules:

- raw HTML is escaped;
- dangerous URL protocols are rejected;
- TeX inside code stays literal;
- wide formulas, tables, and code scroll inside their own containers;
- a failed rich-render block falls back to safe plain text without stopping later
  updates;
- stable finalized blocks retain their DOM identity while the changing tail is
  reconciled.

Raw mode remains available for terminal evidence. If structured Codex history is
unavailable, Compact Chat must show an explicit fallback warning rather than
pretend that damaged tmux text is complete Markdown.

## Long Conversations

The initial structured transcript contains at most 12 recent complete turns.
Owner maintains a revision-bound index for all user turns and serves older
content through authenticated cursor pages. Tool events and rollout paths never
enter that index response.

When at least two user turns are indexed, Faryo prepares a right-edge question
rail:

- hidden and non-interactive during normal reading;
- revealed temporarily by a fast user wheel/swipe;
- auto-hidden after scrolling stops;
- held open while hovered or keyboard-focused;
- click, Arrow keys, Home, and End jump between questions;
- unloaded markers use a distinct dashed state and fetch their page before jump;
- deliberate top scrolling loads one older page while preserving the visible
  block anchor;
- the active marker follows the reading anchor and selects the final question at
  the bottom;
- mobile display overlays the extreme edge and never reserves permanent content
  width;
- live appends reuse existing marker nodes and preserve the main scroll position.

Question previews are truncated DOM-only labels. They are not written to local
or session storage.

## Main Scroll Contract

- A reader at the bottom follows the latest content.
- A reader who scrolls into history stays at that position during refreshes.
- The return-to-latest control is visible when needed and must not cover a table,
  formula, code block, or composer.
- Programmatic refresh or initial scroll-to-bottom does not reveal the question
  rail; only user scroll intent does.

## Live from tmux

While Codex is working, Compact Chat may include a separate collapsible
`Live from tmux` panel for transient execution evidence.

- It is outside stable structured history.
- A new/at-bottom panel follows terminal output.
- A manually scrolled panel preserves its inner position across refreshes.
- Its expansion preference is isolated per session.
- Clicking the live card does not send interrupt; the explicit animated stop
  control retains that action.

## Composer and Delivery

The composer keeps the same large base geometry across focus, blur, and mobile
keyboard state, growing only with real multiline text.

Submission rules:

- one browser action creates one client message ID and immutable target-session
  snapshot;
- retry and late response handling never switch to a newly selected session;
- a conflicting desktop TUI draft is not overwritten;
- failed or ambiguous sends retain the browser draft;
- Owner confirms Codex acceptance before clearing the draft;
- a working Codex uses Tab for a queued follow-up, while an idle Codex uses Enter;
- no-evidence recovery remains an explicit failure rather than a false success.

Attachments remain associated with the submission that included them; a late
response cannot clear a later session's independent draft or attachments.

## Responsive Layout

### Phone (360–430 px)

- single reading column;
- 10–12 px normal side padding;
- stable large composer above the bottom safe area;
- question rail overlays the extreme edge only while active;
- tables, code, and display math use internal horizontal scrolling;
- session/details panels cover the page instead of shrinking the conversation.

### Tablet/Desktop

- centered conversation axis around 748 px;
- question rail appears outside that reading axis when space permits;
- session/details panels remain overlays;
- composer stays centered and does not expand to the full monitor width.

## Accessibility and Privacy

- Interactive controls use semantic buttons and visible focus states.
- The question rail uses roving tabindex and accessible question labels.
- Reduced-motion preference disables smooth/animated transitions.
- Owner tokens are removed from the visible URL and are not written into resource
  DOM attributes.
- File/image previews use authenticated requests and temporary Blob URLs.
- Internal memory annotations render as bounded cards and do not enter copied
  answer text.

## Acceptance Matrix

The maintained matrix includes:

- 390x844 mobile Chrome;
- 1440x900 desktop Microsoft Edge;
- structured Markdown/GFM/KaTeX/Shiki;
- 40-question complete index, bounded first page, cursor preload, lazy jump,
  eventual full DOM loading, auto-hide, stable append, and unchanged width;
- isolated no-zsh startup, invalid executable, readiness timeout cleanup, and a
  real Gateway-to-Owner Codex start;
- mobile directory-picker containment, default recent cwd, HMAC tamper rejection,
  `faryoN` naming and exact test-session cleanup;
- offline/background recovery and 20-message exact delivery;
- cross-session retry/delayed-response isolation;
- protected files/images, CSP, and safe render fallback;
- unchanged Codex tmux dimensions before and after browser/deployment tests.

Detailed evidence is maintained in
[`plans/deepseek-inspired-ui-plan.md`](plans/deepseek-inspired-ui-plan.md) and
[`plans/codex-reliability-hardening-plan.md`](plans/codex-reliability-hardening-plan.md),
plus [`plans/full-history-navigation-plan.md`](plans/full-history-navigation-plan.md).
