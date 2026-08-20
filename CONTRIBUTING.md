# Contributing

Faryo values small, readable changes.

## Principles

- Keep runtime dependencies deliberate. A focused mature library is preferred
  when it removes real complexity; pin, license, test and bundle it locally.
- Keep Owner local and loopback-first.
- Keep Gateway responsible for public auth, routing, and policy.
- Do not commit runtime config, tokens, password hashes, binary artifacts, or
  generated caches.

## Checks

Install the locked development tools, then run the source validation check:

```bash
python -m pip install -r requirements-dev.txt
npm ci --ignore-scripts
scripts/check-source.sh
```

## Style

Use direct code over framework layers unless an abstraction removes real
complexity. Documentation should be short, concrete, and tied to how Faryo is
actually deployed.
