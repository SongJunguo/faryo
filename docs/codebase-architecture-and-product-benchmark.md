# Faryo Codebase Architecture and Product Benchmark

Updated: 2026-08-20
Baseline: v1.2.1 before the v1.2.2 immersive-display work

## Executive conclusion

Faryo is not a heavy repository. It has a small tracked footprint and a strong
product boundary: one Gateway, one local Owner, one Codex/tmux execution surface,
local rendering assets and source-only CI. Its maintenance debt is concentrated
inside a few large files rather than spread across too many packages.

The correct response is a staged refactor, not a rewrite. New independent UI
behaviour should move into tested modules now. Gateway's embedded portal assets
and the largest Python responsibility clusters should be extracted over the next
one or two releases. A native app or full React/Expo migration is justified only
after Faryo needs several native-only capabilities such as reliable background
push, camera workflows and OS-level share integration.

## Measured baseline

| Measure | v1.2.1 result | Interpretation |
| --- | ---: | --- |
| Git-tracked files | 237 | Small |
| Tracked bytes | about 5.6 MB | Small for a formula-capable web product |
| Git pack | about 2.5 MB | Clone cost is modest |
| Maintained code/test lines | about 23,241 | Moderate, still reviewable |
| Test and browser-smoke files | 38 | Strong relative to product size |
| Owner `server.py` | 4,052 lines, 202 top-level functions | Main backend hotspot |
| Gateway `server.py` | 2,038 lines, 964-line Handler class | Main routing/UI hotspot |
| Owner `app.js` | 2,554 lines | Main browser-state hotspot |
| Owner `style.css` | 1,401 lines | Large but separated by feature sections |
| Local render vendor assets | about 3.25 MB | Deliberate offline capability, not dead weight |

Local `__pycache__` files account for development-machine clutter but are ignored
by Git and are not part of the source release. KaTeX fonts and lazy Shiki grammar
chunks dominate tracked size. They provide offline formula/code rendering and
carry their provenance and licences, so deleting them merely to reduce a size
number would regress a defining Faryo feature.

## What is structurally sound

- `apps/gateway`, `apps/owner`, `apps/shared`, `tools`, `docs` and `scripts` have
  clear top-level responsibilities.
- Gateway owns public auth/routing; Owner owns local Codex/tmux execution.
- Browser reading state is distinct from durable Codex history and live tmux.
- Independent modules already exist for question navigation, copy fidelity,
  clipboard images, event parsing, stable blocks and Live scroll.
- One canonical source check is shared by local development, pull requests and
  tagged source releases.
- Runtime secrets and conversations live outside Git.

## Where the debt is real

1. Owner `server.py` mixes Codex SQLite metadata, rollout parsing, App Server
   RPC, tmux runtime, delivery confirmation and HTTP routing.
2. Gateway `server.py` mixes authentication/storage, route proxying, bridge
   packages and a minified HTML/CSS/JavaScript workbench.
3. Owner `app.js` owns transport, history paging, DOM reconciliation, panels,
   composer delivery, attachments and terminal controls in one closure.
4. Large browser smoke files repeat Chrome DevTools setup and make focused tests
   harder to author.
5. Dynamic payloads are dictionaries across Python/JavaScript boundaries without
   one versioned schema document.

These are change-coupling problems. Splitting files without stabilizing their
interfaces would only relocate the same coupling.

## Dependency policy

Lightweight does not mean dependency-free. Faryo's best feature already depends
on mature libraries: micromark/mdast for Markdown structure, KaTeX for math and
Shiki for code. The policy should be value-per-complexity:

- accept a library when it materially reduces security, parsing,
  accessibility or cross-browser risk;
- require a clear licence, pinned version, local production asset, provenance
  note and canonical test;
- record bundle/build cost and a removal path;
- never require a runtime CDN.

| Candidate | Decision | Reason |
| --- | --- | --- |
| `screenfull` | Re-evaluate after a unified front-end bundle | Mature and tiny, but current ESM integration creates a new build seam and the platform still does not support iPhone fullscreen; v1.2.2 uses a small tested adapter plus PWA fallback |
| Floating UI | Good next dependency | Replaces hand-written anchored-sheet collision logic and brings focused visual regression value |
| Preact | Gateway pilot after static extraction | Small component/runtime cost and a familiar state model; avoid migrating the structured transcript DOM first |
| Lit | Alternative pilot | Incremental web components fit vanilla pages, but Shadow DOM can complicate shared styling, copy and Markdown interaction |
| Capacitor | Conditional Android path | Reuses the web UI and is lower-risk than an Expo rewrite when native push/camera/share features become a real requirement |
| Expo/React Native | Not now | Excellent for a native-first product such as Happy, but it would duplicate Faryo's tested web surface and release/security matrix today |

The `screenfull` trade-off is based on its own documented 0.7 kB wrapper,
cross-browser normalisation and lack of iPhone support in the
[screenfull repository](https://github.com/sindresorhus/screenfull). Preact,
Lit and Floating UI are evaluated from their maintained upstream repositories:
[Preact](https://github.com/preactjs/preact), [Lit](https://github.com/lit/lit),
and [Floating UI](https://github.com/floating-ui/floating-ui).

## Similar-project benchmark

| Project | Strong ideas | Faryo decision |
| --- | --- | --- |
| [Happy](https://github.com/slopus/happy) | iOS/Android/Web clients, end-to-end encryption, push notifications, voice and rapid terminal/mobile control handoff | Learn from attention notifications and device handoff. Do not copy its relay/native stack until Faryo needs native-only behaviour |
| [Happier](https://github.com/happier-dev/happier) | Global attention inbox, editable pending queue, steering, session fork/handoff, read-only and write workspace tools, diagnostics and feature flags | Highest-value roadmap source: attention inbox, queue control, safe diff view and redacted diagnostics |
| [Harness Remote](https://github.com/giuliastro/harness-remote) | Capability discovery, one machine endpoint, PWA plus Capacitor APK, adaptive phone/desktop navigation, completion sound and dependency notes | Adopt capability-driven controls and consider Capacitor only after web push/background limits become material |
| [Tether](https://github.com/larsderidder/tether) | Attach-first supervision, explicit human-in-the-loop gates, CLI/API automation and optional messaging bridges | Faryo already shares the attach-first principle. Chat bridges would expand the attack surface and are not a current priority |
| [Codex Remote](https://github.com/RealDyllon/codex-remote) | Codex App Server bridge, trusted QR pairing, live streaming, photos, notification routing, reasoning and permission controls | Continue moving safe lifecycle/metadata work to official App Server APIs; keep current identity layers instead of adding a relay/QR trust system now |

Faryo should not compete by matching the total feature count of these much larger
projects. Its differentiators are exceptionally faithful Markdown/TeX reading,
the same visible tmux session on web and desktop, a small self-hosted deployment,
and explicit privacy/geometry regressions.

## Product roadmap derived from the benchmark

### P0: now

- Installable standalone PWA on every maintained page.
- Explicit user-activated full screen with a persistent exit control.
- Continue extracting new independent browser behaviours into Node-tested files.

### P1: next

- Attention center for sessions that completed, failed or need a TUI decision.
- Opt-in notification/completion sound with no prompt or answer text in the
  notification body; deep links must bind to the exact route/session.
- Visible pending-follow-up queue with edit/reorder/cancel and server-side
  idempotency, instead of relying on terminal text as the only queue view.
- Workspace-scoped read-only changed-files and diff view before any remote Git
  write controls.

### P2: after protocol seams are stable

- Redacted diagnostics export and a safe recovery screen.
- Versioned capability payload so controls appear only when the current Codex
  runtime supports them.
- Extract Gateway portal CSS/JavaScript to static files and dynamic bootstrap
  JSON; then trial Preact or Lit on Gateway session cards/panels.
- Split Owner into Codex history, tmux runtime, delivery and HTTP modules; split
  Gateway into auth/state, proxy, bridge and portal modules.
- Shared Chrome DevTools harness for focused mobile/desktop browser tests.

### Conditional native packaging

Use Capacitor to package the existing PWA for Android only when at least two or
three of background push, camera/share target, biometric local unlock or
app-store distribution are approved requirements. A native shell should reuse
the same Gateway protocol rather than create a second agent backend.

### Deliberately deferred

- multi-provider UI, social collaboration and public session links;
- Telegram/Slack/Discord control bridges;
- voice agent and automatic approval on behalf of the operator;
- full remote IDE/editor and unrestricted Git writes;
- independent encrypted relay while the current loopback Gateway and identity
  edge remain the deployment model.

## Mobile display decision

Faryo v1.2.1 locks `html/body` and scrolls the transcript inside `main`. Mobile
Chromium dynamically retracts its browser bars when the document scrolls, but
that browser behaviour is not an application API and does not follow the old
inner scroll container.

The selected solution uses a small scroll-surface adapter. Narrow normal tabs
reached through Gateway use genuine document-root scrolling; direct Owner,
desktop and installed PWA views retain the bounded inner scroller. History
anchors, question navigation and live-follow consume the same adapter contract.
It then offers two stronger explicit modes:

1. Manifest `display: standalone` for a persistent installed app window without
   the normal URL bar. Microsoft documents that standalone Edge PWAs omit normal
   browser UI in its [PWA guide](https://learn.microsoft.com/en-us/microsoft-edge/progressive-web-apps/how-to/).
2. Fullscreen API after a direct user tap, synchronized through
   `fullscreenchange`, with an always-available in-page exit. The API requires
   transient user activation and browsers retain their own exit mechanism, as
   documented by [MDN](https://developer.mozilla.org/en-US/docs/Web/API/Element/requestFullscreen).

The manifest remains `standalone`, not `fullscreen`: standalone is the safer
default for a multi-page administration surface, while explicit fullscreen is
temporary and easy to leave. Chrome's own Android documentation confirms that
dynamic browser bars and edge-to-edge viewports remain browser-controlled
behaviour: [Chrome edge-to-edge guide](https://developer.chrome.com/docs/css-ui/edge-to-edge).

## Refactor acceptance gates

- No new module may read tokens, conversation bodies or private paths unless its
  documented responsibility requires them.
- Browser modules need pure Node tests before they are wired into `app.js`.
- Backend extraction must preserve route/API contracts and pass the same
  Gateway/Owner suites before old code is deleted.
- A framework pilot must reduce changed lines and duplicated state in its target
  surface; bundle size alone is not a sufficient reason to adopt or reject it.
- Every deployment comparison includes Owner/Gateway health and exact tmux
  window geometry.

## v1.2.2 implementation outcome

The first step follows this roadmap rather than starting a framework migration:

- a 173-line immersive controller owns Fullscreen API compatibility and UI
  state outside `app.js`;
- a 51-line scroll adapter lets history/navigation use either the existing
  conversation element or the mobile document root;
- both have pure Node tests and one trusted-click/touch browser smoke;
- no new production dependency, CDN or duplicate backend was required;
- the remaining Owner/Gateway monolith split stays a deliberate next-phase task,
  not an unbounded change hidden inside the mobile feature.
