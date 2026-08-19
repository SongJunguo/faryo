# Client Sync

> **Optional inherited workflow:** this document covers multi-endpoint sparse
> checkout synchronization. The current fork is maintained and validated as a
> single Ubuntu/Linux Codex deployment; ordinary users do not need this workflow.

Faryo uses one source repository, but clients do not need full working trees.

## Owner Client

For HP/PC/local execution clients, use sparse checkout with:

```text
apps/owner/
apps/shared/
docs/
scripts/
README.md
```

## Gateway Host

For the TXY/public gateway host, use sparse checkout with:

```text
apps/gateway/
apps/shared/
deploy/
scripts/
docs/
README.md
```

## Full Development Checkout

Use a full checkout only on development machines or source-validation automation where
both components need to be changed together.
