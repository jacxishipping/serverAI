# Implementation status

**Last reconciled:** 2026-11-14. This file distinguishes code presence from
runtime validation. A module or route existing in the repository does not mean
that platform path has been exercised or production-ready.

## Implemented code paths

- Python control plane (FastAPI), MCP server (stdio and Streamable HTTP), SQLite
  store, migration runner, device enrollment/heartbeat/task polling, approvals,
  policy, audit and dashboard APIs.
- SQLite is the default runtime database. A PostgreSQL adapter and SQL
  migrations are present. Install PostgreSQL support with
  `pip install -r requirements-postgres.txt`; production readiness still
  requires live PostgreSQL migration/API testing and operational backup drills.
- Device tokens have configurable expiry, rotation, hashing at rest and
  revocation checks. Local user login, roles, sessions, policy versions,
  approval expiry and audit export/retention code are present.
- The bounded task runner uses an allowlisted operation set, timeout/output
  bounds and a reduced environment. Optional Linux network-namespace isolation
  applies only to that runner.
- Linux, Windows and macOS Python agent entry points exist and use the shared
  poller. Windows also has a native C++ service/desktop implementation.
- The dashboard has React/TypeScript source and build/test workflows.
- WebRTC streaming/signaling, desktop input, capture and telemetry paths exist;
  Playwright browser tools exist as an optional dependency. Browser session
  isolation and destination policy are described in `browser-security.md`.
- OIDC, custom scheduled agents, agent run history and per-agent memory code
  exist, with configuration/provider requirements.
- Task dependencies, redacted checkpoints, durable task events and restart
  reconciliation are implemented. Interrupted running tasks are marked failed
  for operator review rather than replayed. Project memory APIs record source,
  optional same-tenant task evidence and expiry; custom agents do not yet load
  this shared project memory automatically.
- Heartbeats can persist a bounded device capability list and inventory object;
  the shared Python poller reports basic runtime and resource telemetry. A full
  installed-application inventory and native-agent parity contract remain open.

## Validation boundaries

- Linux-oriented Python unit/integration tests and dashboard checks are defined
  in CI. A green test suite is not evidence for native Windows/macOS behavior,
  production networking, multi-worker coordination, or real provider login.
- Windows C++ service, capture, encoding, IPC, installer and interactive desktop
  paths require execution on supported Windows hosts. macOS agent code requires
  execution on macOS. These paths are not certified by source inspection.
- MCP Streamable HTTP has an app and route implementation; verify a live
  authenticated round trip for every supported deployment configuration.
- PostgreSQL support is code-complete only to the adapter/migration level until
  the PostgreSQL integration suite and connection-pool behavior are verified.
- Reverse-proxy mTLS is optional deployment configuration. The control plane
  does not itself terminate client-certificate authentication.
- Emergency-stop, OIDC pending state and background schedulers include
  process-local state. Use one worker until shared durable coordination and
  restart behavior are implemented and tested.
- Browser sessions require distinct bearer tokens for distinct principals.
  Browser egress policy is defense in depth; production deployments handling
  untrusted pages should also restrict outbound network access at the host or
  container boundary.
- The dashboard's current fleet selection still downloads a device snapshot;
  local pagination does not imply million-device scale. See
  `production-readiness.md`.

## Not claimed

- Meeting the proposed API, dispatch, reconnect, screenshot, concurrency or
  workflow-verification targets. No benchmark result is recorded here.
- A full named-role multi-agent supervisor/planner/researcher/developer/tester/
  security/recovery runtime. Current custom agents are scheduled bounded loops.
- Automatic task resume from checkpoints, cross-agent project memory retrieval,
  or comprehensive device application/capability inventory.
- Production security certification, multi-tenant isolation certification, or
  clean multi-host deployment validation.
- Automatic installation of signed agent updates. The update path verifies
  signed metadata; installation remains an operator action.
