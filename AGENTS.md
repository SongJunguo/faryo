# Faryo Dependency Principle

- Lightweight does not mean dependency-free. Prefer a focused, mature library
  when it clearly improves quality or avoids reimplementing difficult behaviour.
- Keep dependencies deliberate: use compatible licences, pin versions, bundle
  production assets locally, and cover them in the normal tests.
- Prefer incremental adoption over a framework rewrite. A small local solution
  is still appropriate when it is simpler, independently testable, and cheaper
  to maintain than the dependency it would replace.
- Browser updates must work after an ordinary reload or a newly opened tab:
  version every mutable asset automatically, mark missing/rejected assets
  `no-store`, and never require users to discover or perform a hard refresh.
