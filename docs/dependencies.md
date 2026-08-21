# Faryo Dependency Ledger

Updated: 2026-08-22

Faryo keeps production dependencies deliberate, not artificially zero. Every
entry below is pinned, locally resolved and covered by the canonical source
check. Production never loads these assets from a CDN.

## Development-only dependencies

### playwright-core 1.62.1

- Upstream: [microsoft/playwright](https://github.com/microsoft/playwright)
- License: Apache-2.0
- Lock: root `package-lock.json`
- Classification: development/test only
- Installed unpacked size: about 13.4 MB under ignored `node_modules`
- Shipped browser/runtime bytes: 0; it launches an already installed Chrome or
  Edge executable and does not download browser binaries in this repository
- Security check: `npm audit` reported zero known vulnerabilities at adoption
- Initial measurable result: the immersive smoke fell from 283 to 151 lines and
  the Gateway workbench smoke from 546 to 461 lines. The shared fixture and its
  test are 93 lines, for a net reduction of 124 lines after the first two
  migrations, while centralizing launch, profile cleanup, auth headers and touch
  input.
- Removal path: restore the two tests' direct CDP bootstrap and remove the root
  npm manifest/lock plus `tools/browser-harness`.

### Ruff 0.16.3

- Upstream: [astral-sh/ruff](https://github.com/astral-sh/ruff)
- License: MIT
- Pin: root `requirements-dev.txt`
- Classification: development/CI only
- Shipped runtime bytes: 0; Owner and Gateway do not import Ruff
- Initial rule set: Python fatal syntax/runtime-name checks and Pyflakes (`E9`,
  `F`) only; no repository-wide formatting rewrite
- Initial measurable result: removed two stale Gateway imports and one unused
  Owner tmux capture that had run on every status request.
- Removal path: remove the Ruff pin/config/check; no runtime state migration.

### esbuild 0.28.2

- Upstream: [evanw/esbuild](https://github.com/evanw/esbuild)
- License: MIT
- Lock: root `package-lock.json`
- Classification: development/build only
- Purpose: deterministic local diff-review bundle; `--check` rebuilds in a
  temporary directory and byte-compares every committed asset
- Shipped runtime bytes: 0 from esbuild itself

### Prettier 3.9.6

- Upstream: [prettier/prettier](https://github.com/prettier/prettier)
- License: MIT
- Lock: root `package-lock.json`
- Classification: development/format only
- Shipped runtime bytes: 0; Gateway serves the formatted source assets, not
  Prettier
- Purpose: keep the externalized Gateway workbench CSS/JavaScript reviewable and
  deterministic after removing the former Python string template
- Enforcement: `npm run check:format` is part of `scripts/check-source.sh`
- Removal path: remove the formatter script/pin/check; runtime behavior and
  static-asset loading do not depend on the formatter

### ESLint 10.8.1

- Upstream: [eslint/eslint](https://github.com/eslint/eslint)
- License: MIT
- Lock: root `package-lock.json`
- Classification: development/lint only
- Installed dependency tree: 69 packages under ignored `node_modules`
- Shipped runtime bytes: 0; browser and server processes do not import ESLint
- Initial rules: duplicate bindings/keys, assignment hazards, unreachable and
  unsafe-finally control flow, valid `typeof`, and unused first-party bindings;
  vendored and generated assets are excluded
- Initial measurable result: the high-confidence control-flow dry run found no
  defects, while `no-unused-vars` removed four stale Owner browser bindings
- Enforcement: `npm run check:lint` is part of `scripts/check-source.sh`
- Removal path: remove the exact pin, flat config and canonical check; no runtime
  state migration is required

## Locally bundled runtime libraries

### diff2html 3.4.56 + DOMPurify 3.4.14

- Upstreams: [diff2html](https://github.com/rtfpessoa/diff2html) and
  [DOMPurify](https://github.com/cure53/DOMPurify)
- Licenses: MIT; DOMPurify is available under MPL-2.0 or Apache-2.0
- Lock/build: root `package-lock.json` and `tools/diff-review/build.mjs`
- Shipped assets: about 74 KB JavaScript and 17 KB CSS, loaded only after the
  operator opens read-only Workspace Changes
- Transitive runtime notices: `diff` and Hogan licences are copied beside the
  bundle; the manifest records package versions, bytes and SHA-256 for every
  asset
- Security evidence: a real-browser fixture injects script/event-handler text
  into a unified diff and verifies that no executable element or handler reaches
  the rendered DOM
- Removal path: remove the Changes renderer/panel and the local vendor directory;
  Owner's bounded JSON status/diff endpoint remains independently removable.

### Preact 10.29.8

- Upstream: [preactjs/preact](https://github.com/preactjs/preact)
- License: MIT
- Lock/build: exact root `package-lock.json` pin with
  `tools/gateway-preact/build.mjs` and `tools/owner-ui/build.mjs`
- Classification: two focused local browser bundles; no CDN or runtime Node
  process
- Scope: Gateway keyed file-package/launcher/active/history lists, plus Owner
  composer, command palette, structured interaction sheet and dynamic status
  shell. Owner also uses a framework-neutral conversation store and Preact
  lifecycle shell for loading/startup/empty/fallback/error states; rich
  Markdown/TeX bodies, Raw formatting, Live tmux and paged history remain
  isolated adapters.
- Production transitive dependencies: none
- Gateway bundle: 18,429 bytes raw / 7,438 gzip; SHA-256
  `b5d545f4078df73d70036196c861077cbc4443a144674411466a1bcaa90c7d05`;
  12 KiB gzip limit.
- Owner bundle: 28,053 bytes raw / 10,245 gzip; SHA-256
  `c89831e0fc63b2b74f9f9ddf3ef4ed6ed314c907156bf673906522eb8fc2d429`;
  24 KiB gzip limit.
- Each bundle has a generated adjacent license notice recording exact version,
  hash, byte counts, transitive count and full MIT text.
- Measured result: removed the hand-written JSON-signature/DOM replacement
  renderer and string-built dynamic card HTML. Browser regressions require
  keyed node/focus/transient state to survive refresh and markup-looking server
  strings to remain inert text.
- Removal path remains source-only and needs no server/private-data migration;
  each focused surface can be reverted independently through Git history.
- Evidence: [Gateway pilot evaluation](preact-pilot-evaluation.md) and
  [v1.6 structured interaction plan](plans/v1.6-structured-interactions-and-owner-ui-plan.md),
  plus the [v1.7 transcript migration plan](plans/v1.7-preact-transcript-migration-plan.md).

## Runtime and bundled assets

- Codex auto-update adds no third-party Faryo dependency. Its preflight uses
  Python standard-library JSON, subprocess and Linux `flock`, then delegates
  npm-based installations to the npm paired with the dynamically discovered
  Codex runtime. The only accepted package target is `@openai/codex`; update
  state is mode 600 and contains versions, timestamps and a bounded result only.

- Owner and Gateway runtime Python dependencies are exact-pinned in
  `pyproject.toml` and the source-installer requirements mirror. Starlette 1.6.0
  and Uvicorn 0.52.4 are BSD-3-Clause; the shared base pins are AnyIO 4.14.2
  (MIT), Click 8.4.2 (BSD-3-Clause), h11 0.16.0 (MIT), and idna 3.19
  (BSD-3-Clause). Python 3.10 additionally installs the exact MIT-licensed
  `tomli` 2.4.1 backport; Python 3.11+ uses standard-library `tomllib`.
  `websockets` 16.1.1 (BSD-3-Clause) provides the Owner-to-App-Server Unix
  WebSocket transport. No `full`/`standard` extras, multipart parser, uvloop or
  watchfiles package is installed. bcrypt remains exact-pinned at 5.0.0 under
  Apache-2.0.
- Starlette/Uvicorn now serve both Web processes; the separate App Server user
  service is the official Codex executable, not another Python Web server.
  These packages add no browser bytes and production still requires no Node
  process beyond the Node runtime already required by an npm-installed Codex.
- Removal path is a formal release rollback. The old Owner
  `ThreadingHTTPServer` entry has been deleted after ASGI contract and browser
  cutover, so current releases do not carry two same-purpose HTTP stacks.
- KaTeX and the Markdown/Shiki bundle remain local, versioned vendor assets with
  their own notices under the Owner static tree.
- Floating UI was evaluated but not adopted: the tested `placeSheet` function is
  656 bytes, so the library would currently add more production code than it
  removes. TanStack Virtual 3.17.8 reduced a synthetic 600-row outer DOM but its
  first Preact/core adapter failed the history-prepend anchor gate; its temporary
  dependency and adapter were removed. Lit and Python Web Push remain conditional
  future candidates.
- The current root npm dependency audit reports zero known vulnerabilities.
