# Gateway Preact Pilot Evaluation

Date: 2026-08-20
Decision: adopt the focused keyed-list pilot for Faryo v1.4.0

## Scope decision

The initial candidate scope included every authenticated Gateway home control.
The measured pilot deliberately narrows production adoption to the four
frequently reconciled list roots:

- file packages;
- the Codex launcher;
- active session cards;
- paginated history session cards.

The generic sheet, Attention state, history filter controls and directory
picker remain in the existing controller. They do not retain a second vanilla
card renderer. Migrating those one-shot controls now would add a second modal
state boundary without removing the card defects that motivated the pilot.
Owner, Compact Chat, Markdown/TeX and live tmux rendering remain framework-free.

> Historical scope note: this document records the v1.4 Gateway-only pilot.
> Faryo v1.6 later adopted a separate focused Owner bundle for composer,
> command, interaction and status shells. Faryo v1.7 adds a framework-neutral
> conversation store and a Preact transcript lifecycle shell; Markdown/TeX
> bodies, Raw formatting, Live tmux and history paging remain isolated adapters.
> See the v1.6 structured-interaction and v1.7 transcript-migration plans.

This is an application of the repository dependency principle: use a focused
library where it removes a difficult repeated behavior, but do not turn a
successful component pilot into a framework rewrite.

## Dependency and build record

| Item | Result |
| --- | --- |
| Package | Preact 10.29.8, exact-pinned |
| License | MIT |
| Runtime loading | local bundle only; no CDN |
| Production transitive dependencies | none |
| Bundle | `apps/gateway/server/static/workbench-preact.js` |
| Raw bytes | 17,753 |
| gzip level-9 bytes | 7,211 |
| SHA-256 | `795ad3cc48e8610ed105cb68a936567bb7c97ab156ed656a5557958582c33f3d` |
| Limit | 12,288 gzip bytes; build fails above it |
| Notice | local version, hash, byte counts and full MIT text |
| Security audit | root npm audit: 0 known vulnerabilities |

`npm run build:gateway-preact` writes the bundle and notice. `npm run
check:gateway-preact` rebuilds both in memory and byte-compares the committed
artifacts. The build also rejects a changed Preact version/license or an
oversized gzip result.

## Measured source result

The controller asset changed from 57,344 to 50,582 bytes, a reduction of 6,762
bytes (11.79%). The new readable JSX and pure session model total 9,401 bytes,
so total first-party source for this area grows by 2,639 bytes (4.60%). The
pilot is therefore **not** accepted by claiming a misleading total-source
reduction. It is accepted by removing two tested defect classes:

1. The old JSON-signature reconciler replaced a whole card when server data
   changed. That could discard focus, drag state and other transient DOM state.
   A real-browser regression refreshes server data and requires the keyed card
   to remain the same node with focus and transient state intact.
2. The old renderer assembled dynamic card content with `innerHTML`, requiring
   every future interpolation to remember manual escaping. Preact now creates
   text children for server-provided title, route, folder and status values. A
   browser injection fixture requires markup-looking title text to remain text,
   with no element or handler created.

The old `syncChildren`, `cardSig`, `childByKey`, `packageCard`, `sessionCard` and
`newAgentCard` implementations are removed. There is no runtime flag or second
vanilla implementation of the same lists.

## Verification

- exact bundle/notice reproducibility: pass;
- ESLint, including JSX source, and Prettier: pass;
- session-model unit tests: pass;
- Gateway Python/ASGI suite: 111 tests pass after the deployment shutdown
  regression was added;
- isolated real Gateway at `127.0.0.1:8781`: pass;
- Chrome 1440x900 workbench/history/directory/security interactions: pass;
- mobile Chromium 390x844 equivalent matrix: pass;
- deployed loopback Gateway repeats both viewport matrices: pass;
- three distinct 10-item history pages and direct jump: pass;
- keyed node/focus/transient-state retention: pass;
- dynamic card text injection fixture: pass;
- no page-wide horizontal overflow: pass.

The fixtures use anonymous labels and never print session titles, directories,
tokens, cookies or message content.

## Rollback

Before release, remove `preact` from the root manifest/lock, delete
`apps/gateway/ui/`, `tools/gateway-preact/` and the two generated static assets,
and restore the list renderer from the last behavior-closed pre-pilot commit.
After v1.4.0, the formal rollback is the repository's v1.3.0 source-only tag;
runtime auth, history, tmux and private data do not need migration.
