# Gateway tests

Run these before changing Gateway security, browser POST handling, or Owner proxy routing.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s apps/gateway/server/tests -p 'test_*.py'
```

The suite checks the CSRF boundary, browser security headers, enabled-route
validation, private runtime configuration, active/history separation,
10-record history pagination, CSP nonces, hardened session-cookie attributes,
trusted-proxy login limiting, and CSRF-protected Owner proxy POST behavior.

For an authenticated real-browser check, set the smoke URL and login inputs and
run:

```bash
FARYO_SMOKE_URL=https://gateway.example/ \
FARYO_SMOKE_LOGIN_USER=tester \
FARYO_SMOKE_LOGIN_PASSWORD_FILE=/private/path/to/password \
node apps/gateway/server/tests/browser-workbench-smoke.mjs
```

The browser smoke checks the two session regions, protected desktop tmux cards,
independent history scrolling, distinct first/second pages, and a direct jump to
page three without printing session titles or identifiers.
