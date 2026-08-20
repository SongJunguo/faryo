# Faryo Dependency Ledger

Updated: 2026-08-20

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

## Runtime and bundled assets

- Gateway runtime Python dependencies are exact-pinned in
  `apps/gateway/requirements.txt`. v1.4 adopts Starlette 1.6.0 and Uvicorn
  0.52.4 under BSD-3-Clause, with base-only transitive pins AnyIO 4.14.2
  (MIT), Click 8.4.2 (BSD-3-Clause), h11 0.16.0 (MIT), and idna 3.19
  (BSD-3-Clause). No `full`/`standard` extras, multipart parser, uvloop,
  watchfiles or WebSocket package is installed. bcrypt is now exact-pinned at
  5.0.0 under Apache-2.0.
- The six pure-Python ASGI/base wheels total about 507 KB; bcrypt's platform
  wheel is about 482 KB. These are Gateway runtime dependencies and add no
  browser bytes or background process beyond the Uvicorn process replacing the
  legacy server.
- Removal path before cutover: remove Starlette/Uvicorn and their five base
  transitive pins, then retain the legacy entrypoint. After cutover, formal
  rollback uses the `v1.3.0` requirements and service scripts.
- KaTeX and the Markdown/Shiki bundle remain local, versioned vendor assets with
  their own notices under the Owner static tree.
- Floating UI was evaluated but not adopted: the tested `placeSheet` function is
  656 bytes, so the library would currently add more production code than it
  removes. Preact/Lit and Python Web Push remain conditional future candidates.
- The current root npm dependency audit reports zero known vulnerabilities.
