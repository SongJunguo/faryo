# Contributing

Faryo values small, readable changes.

## Principles

- Keep runtime dependencies light.
- Prefer standard library code and existing shell tools.
- Keep Owner local and loopback-first.
- Keep Gateway responsible for public auth, routing, and policy.
- Do not commit runtime config, tokens, password hashes, binary artifacts, or
  generated caches.

## Checks

Run the source validation check before opening a change:

```bash
scripts/check-source.sh
```

## Style

Use direct code over framework layers unless an abstraction removes real
complexity. Documentation should be short, concrete, and tied to how Faryo is
actually deployed.
