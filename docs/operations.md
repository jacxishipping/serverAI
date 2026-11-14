# Operations
- Health: `GET /health` on the plane; `GET /api/devices` shows online/offline.
- Logs: `journalctl -u ai-bridge-*`; audit via `GET /api/audit`.
- Emergency stop: dashboard button or `POST /api/emergency-stop` (admin
  token). Clears with `POST /api/emergency-stop/clear`. While active,
  new tasks are rejected (403) and agents report `emergency_stop: true`. The
  value is stored in the control database and remains active after restart.
- Upgrades: `git fetch --tags && git checkout vX.Y.Z`, reinstall the venv,
  restart services, re-run `pytest -q`. Roll back the same way to the
  previous tag; the SQLite/Postgres schema is additive in v0.2.
- Backups: workspace backups live in `<workspace>/.ai-bridge-backups/`
  (timestamped ZIPs). Copy them off-device; also back up `control.db`
  (or `pg_dump ai_bridge`) nightly.
- Rate limiting: 1200 req/min for authenticated tokens and 300 req/min for
  anonymous IPs on general API paths; authentication flows have separate limits.
  Redis can share limits between processes. Keep proxy-level limiting and
  per-tenant quotas in front of public deployments.
- Scheduled jobs, trigger cooldowns and custom-agent runs use atomic database
  claims so only one worker claims a due occurrence. The runner loops and other
  locks remain process-local; a crash after a claim can defer that occurrence
  until its next interval. Emergency-stop and single-use OIDC state are
  database-backed, but emergency-stop changes are not broadcast to concurrent
  workers. Keep the one-worker deployment until these remaining boundaries
  have shared coordination and recovery tests.
- PostgreSQL deployments install `requirements-postgres.txt`. Tune
  `AI_BRIDGE_PG_POOL_MIN_SIZE`, `AI_BRIDGE_PG_POOL_MAX_SIZE` and
  `AI_BRIDGE_PG_POOL_WAIT_S` for the deployment; execute the PostgreSQL
  integration check with `AI_BRIDGE_TEST_POSTGRES_URL` in a disposable test
  database before release.
- Browser outbound destinations default to public HTTPS; configure exact
  internal host exceptions through `AI_BRIDGE_BROWSER_ALLOWED_HOSTS` and keep
  host/container egress controls enabled. See `browser-security.md`.
- Tasks can depend on earlier tasks submitted for the same device and tenant.
  The agent claims a dependent task only after every parent completes. Agents
  may save up to 1 MB of redacted checkpoint JSON while a task is running with
  `PUT /api/agent/tasks/{task_id}/checkpoint`; operators can inspect the event
  history at `GET /api/tasks/{task_id}/events`.
- On control-plane startup, tasks left `running` are marked failed and receive
  an `interrupted` event. Their side effects are uncertain, so inspect before
  retrying. Queued tasks remain queued and will be available to agents.
- Heartbeats may report `capabilities` and `inventory`; reports are persisted
  in the device record, capped to 200 capabilities and 32 KB of inventory.
- Project memory is stored by tenant and project. `POST /api/projects/{id}/memory`
  accepts a source label, optional same-tenant task evidence, and a retention
  period of 1–365 days; viewers can list unexpired entries and admins can delete
  them. Memory content is redacted before storage. Set `project_id` on a custom
  agent to include up to 20 unexpired entries (bounded to 12 KB) in its next
  run's system context.
