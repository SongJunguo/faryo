# Security

Faryo is intended for self-hosted, trusted-operator deployments.

The Gateway can steer terminal-backed coding agents. Treat any Internet-facing
deployment as a remote administration surface: compromise can expose files and
credentials available to the operating-system user running the agents.

## Supported Version

Security fixes target the latest released version.

## Deployment Rules

- Bind Owner endpoints to `127.0.0.1`.
- Expose public traffic through Gateway, not directly through Owner.
- Put an identity-aware access proxy with MFA in front of the entire public
  Gateway hostname. Cloudflare Tunnel alone provides connectivity, not user
  authentication. Avoid broad `Everyone` or `Bypass` policies.
- Keep the Faryo password as an independent application layer behind the access
  proxy. Use a unique password of at least 16 characters.
- Rate-limit public Gateway login at the edge, for example with Caddy,
  Cloudflare, or fail2ban.
- Restrict cloud firewalls to required ports only. Do not leave RDP `3389`
  public; restrict SSH `22` by source or use IAP where available.
- Keep `~/.faryo/**/config`, tokens, password hashes, and cookie secrets out of
  Git.
- Use separate Owner tokens for each route.
- Treat an Owner token as control access to the local tmux session and supported
  local file previews.
- Faryo does not silently override the operator's Codex or Claude permission
  policy. If agents run without approvals or sandboxing, isolate them with a
  dedicated OS account, VM, or container when practical; otherwise a Gateway
  compromise can inherit that authority.
- Do not use query-string Owner tokens as a public entry pattern. Gateway should
  inject Owner tokens server-side.
- Review any public Gateway `/mcp` exposure and protect it with
  an explicit `FARYO_MCP_TOKEN`; only set `FARYO_MCP_CORS_ORIGIN` for trusted
  browser origins.

See [Gateway security hardening](docs/gateway-security-hardening.md) for the
threat model, controls, residual risks, and deployment checklist.

## Reporting

For now, report issues through a private maintainer channel or a GitHub security
advisory once the public repository is enabled.
