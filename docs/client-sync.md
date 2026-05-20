# Client Sync

Faryo uses one source repository, but clients do not need full working trees.

## Owner Client

For HP/PC/local execution clients, use sparse checkout with:

```text
apps/owner/
packages/shared/
docs/
scripts/
README.md
RELEASE
```

## Gateway Host

For the GCP/public gateway host, use sparse checkout with:

```text
apps/gateway/
packages/shared/
deploy/
scripts/
docs/
README.md
RELEASE
```

## Full Development Checkout

Use a full checkout only on development machines or release automation where
both components need to be changed together.
