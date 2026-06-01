# Security

Faryo is intended for self-hosted, trusted-operator deployments.

## Supported Version

Security fixes target the latest released version.

## Deployment Rules

- Bind Owner endpoints to `127.0.0.1`.
- Expose public traffic through Gateway, not directly through Owner.
- Rate-limit public Gateway login at the edge, for example with Caddy,
  Cloudflare, or fail2ban.
- Restrict cloud firewalls to required ports only. Do not leave RDP `3389`
  public; restrict SSH `22` by source or use IAP where available.
- Keep `~/.faryo/**/config`, tokens, password hashes, and cookie secrets out of
  Git.
- Use separate Owner tokens for each route.
- Treat an Owner token as control access to the local tmux session and supported
  local file previews.
- Do not use query-string Owner tokens as a public entry pattern. Gateway should
  inject Owner tokens server-side.
- Review any public Gateway `/mcp` exposure and protect it with
  `FARYO_MCP_TOKEN`.

## Reporting

For now, report issues through a private maintainer channel or a GitHub security
advisory once the public repository is enabled.
