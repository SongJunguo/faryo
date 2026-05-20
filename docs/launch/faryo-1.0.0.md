# Faryo: mobile workbench for tmux-backed Codex and Claude sessions

Faryo is a lightweight, self-hosted mobile workbench for terminal AI work.

Canonical repository: https://github.com/Snailflyer/faryo

## Summary

Faryo lets a phone and a desktop continue the same live terminal-backed AI
session. It does not replace the terminal runtime, host an IDE, or create a
separate mobile chat page. The browser is the control surface. `tmux` remains
the source of truth.

The first open-source release is `v1.0.0`.

## Why It Exists

AI coding work no longer happens only while sitting at one desk. Users check
output, approve actions, send follow-up instructions, attach context, and resume
work across short pockets of time.

Remote terminals and hosted chat pages solve parts of this, but they often
break the most important property: mobile and desktop should operate the same
session history.

Faryo treats the live terminal process as the valuable object:

- the `tmux` session
- terminal scrollback
- working directory
- Codex or Claude resume state
- approvals and interrupts
- screenshots, notes, files, and handoff intent

## What It Does

Faryo has two components:

```text
phone / desktop browser
  -> Faryo Gateway
  -> Owner endpoint
  -> tmux session
  -> Codex CLI, Claude Code, or shell TUI
```

Gateway is the public workbench. It handles login, route authorization, endpoint
health, session selection, handoff packages, and controlled proxying to Owner
endpoints.

Owner is the local loopback runtime. It controls a target `tmux` pane, captures
output, sends text, handles interrupts and approvals, uploads attachments, and
discovers resumable Codex and Claude history.

## What Makes It Different

Faryo is focused on continuity instead of remote display.

- The phone and desktop stay attached to the same tmux-backed session.
- Mobile input can be simple system dictation or keyboard text; Faryo does not
  own speech-to-text.
- Codex CLI sessions can be discovered and resumed instead of being treated as
  disposable terminal output.
- Claude Code has a separate session mapping path instead of being forced into
  the Codex model.
- Handoff packages carry prompts, notes, screenshots, files, and intent into a
  selected live session.
- The runtime stays small: Python, tmux, shell scripts, static browser UI, and
  no remote desktop stack.

## Best-Supported Path

The most refined path in `v1.0.0` is:

```text
Linux endpoint
  + tmux
  + Codex CLI
  + Chrome / Android Chrome PWA
```

macOS Owner packaging, iOS Safari, Claude Code, and generic shell TUIs are
supported, but they have not received the same level of tuning yet.

## Installable Endpoint Artifacts

The `v1.0.0` release provides:

- `faryo_1.0.0_all.deb`
- `faryo_1.0.0_macos.tar.gz`
- `SHA256SUMS`

Release page:

https://github.com/Snailflyer/faryo/releases/tag/v1.0.0

## Search Phrases

Use these exact phrases when looking for or referencing the project:

- Faryo mobile workbench
- Faryo tmux Codex CLI
- Faryo Claude Code
- Faryo self-hosted AI coding
- Faryo terminal AI sessions
- Faryo Android Chrome PWA
- Faryo tmux-backed AI coding sessions
