# Gateway tests

Run these before changing Gateway security, browser POST handling, or Owner proxy routing.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s apps/gateway/server/tests -p 'test_*.py'
```

The suite checks the CSRF boundary, browser security headers, enabled-route
validation, private runtime configuration, and Owner proxy POST behavior.
