# Gateway tests

Run these before changing Gateway security, browser POST handling, or Owner proxy routing.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest apps.gateway.server.tests.test_gateway_csrf_contract
```

`test_gateway_csrf_contract.py` checks the CSRF boundary: Gateway write actions require CSRF, valid CSRF passes, and Owner proxy POST routes are not blocked by Gateway CSRF.
