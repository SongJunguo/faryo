# Contributing

Faryo values small, readable changes.

## Principles

- Keep runtime dependencies light.
- Prefer standard library code and existing shell tools.
- Keep Owner local and loopback-first.
- Keep Gateway responsible for public auth, routing, and policy.
- Do not commit runtime config, tokens, password hashes, package artifacts, or
  generated caches.

## Checks

Run the release check before opening a release-facing change:

```bash
scripts/package-client.sh check
```

For endpoint packaging changes, also run:

```bash
scripts/package-client.sh release
```

## Style

Use direct code over framework layers unless an abstraction removes real
complexity. Documentation should be short, concrete, and tied to how Faryo is
actually deployed.
