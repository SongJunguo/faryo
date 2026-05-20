# Security

Faryo is intended for self-hosted, trusted-operator deployments.

## Supported Version

Security fixes target the latest released version.

## Deployment Rules

- Bind Owner endpoints to `127.0.0.1`.
- Expose public traffic through Gateway, not directly through Owner.
- Keep `~/.faryo/**/config`, tokens, password hashes, and cookie secrets out of
  Git.
- Use separate Owner tokens for each route.
- Treat an Owner token as control access to the local tmux session and supported
  local file previews.
- Review any public Gateway `/mcp` exposure and protect it with
  `FARYO_MCP_TOKEN`.

## Reporting

For now, report issues through a private maintainer channel or a GitHub security
advisory once the public repository is enabled.
