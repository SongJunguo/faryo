# Pre-1.0 Notes

Pre-1.0 Faryo work happened as private/internal development checkpoints. Those
checkpoints are not part of the public release surface, and the public GitHub
repository starts at `v1.0.0`.

These notes are kept only to explain what was folded into the first public
release.

## Included In 1.0.0

- Mobile navigation, route continuity, and session switching.
- Gateway workbench polish for Codex CLI and Claude Code launch entries.
- Explicit Gateway-to-Owner agent session contract.
- Handoff package UI and endpoint package checks.
- Codex history cleanup for internal/subagent branches.
- Claude Code history discovery on its own JSONL/session-id path.
- macOS Owner packaging with a user launchd keepalive installer.
- Public release hygiene for docs, examples, tokens, and local path handling.

## Public Release Surface

The first public release is:

- `v1.0.0`
- `docs/releases/v1.0.0.md`
- https://github.com/Snailflyer/faryo/releases/tag/v1.0.0
