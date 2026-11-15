# Workspace operations and release checks

## Delivered in this change

- Live audit search/export, global policy review/publish, gateway connection
  checks and client editing, and administrator-only service logs.
- Local/Google user role management and disable/enable. Access changes revoke
  existing sessions; self-demotion and removal of the last active administrator
  are rejected. Google sign-in continues to create viewers, never auto-admins.
- Server-persisted device groups/tags, inventory filtering and 25-row pages.
- Device heartbeat/token-expiry checks and an enrollment-to-first-task checklist.
- Polling attention counts for stale devices, recent failures and approvals.
  These are not push notifications or a historical notification inbox.
- Searchable recent tasks and opt-in, server-paginated full task history.
- Compact/Comfortable controls; narrow/touch screens keep 44px targets.
- Shareable non-secret inventory filters and device/tab links. Opening a shared
  URL overrides saved browser filters; don't put sensitive labels into shared URLs.
- Idempotency keys on task creation, permission tests, browser checks in CI and
  a read-only deployment smoke check.

## Known boundaries

- No production merge, deployment, credential rotation or external account login
  is performed by these code changes.
- The main workspace still obtains a complete device snapshot for selection and
  device navigation. Local inventory pages reduce rendering, not download size.
  `/api/fleet/inventory` provides server-side search/pagination for a future
  cursor-based fleet client. Do not claim million-device scalability.
- Live logs are host service logs, not automatic remote-agent log collection.
  Connection status is a local TCP check, not proof of a working external gateway.
- Policy editing creates a new global version. Device overrides remain visible
  under device details and may differ from that global policy.
- Real terminal streaming, unattended desktop streaming, scheduling and workflow
  editors are not exposed by these operations panels; their existing previews
  remain explicitly separate from live operations.
- Tier-4/device override semantics and horizontal deployment need a dedicated
  security review. User-to-tenant assignments and API tenant checks are
  implemented, but multi-tenant API validation and security review remain open.
  Emergency-stop and single-use OIDC pending state are database-backed and
  survive restart. Workers refresh emergency-stop
  state from the database at most every 500 ms. This release is not a security
  certification.
- The production container currently uses one API worker because background
  schedulers and several locks remain process-local. PostgreSQL uses a bounded
  connection pool configured with `AI_BRIDGE_PG_POOL_*`; validate it against a
  live PostgreSQL service before production rollout.
- Production Compose requires a Fernet `AI_BRIDGE_DB_ENCRYPTION_KEY` for
  credentials stored in settings and MCP connector records. Back it up outside
PostgreSQL and test encrypted backup restore with the same key; an operator-run
key rotation command is available, but rotation and restore drills remain
release work.
- Set `AI_BRIDGE_TURN_SECRET` to a high-entropy secret before using TURN REST
  credentials. Without it, ICE configuration is STUN-only.
- Core navigation/sign-in translations ship as a 20-locale preview with RTL
  shells. Operational/safety content and the demo remain English pending string
  extraction and native-speaker review. See `docs/localization.md` for exact
  coverage; this is not complete translation or support for every language.

## Idempotent task submissions

`POST /api/tasks` accepts an optional `Idempotency-Key` (1–128 ASCII characters).
Use one random key per reviewed, per-device submission. Keep that key if a client
intentionally reconciles an uncertain outcome; use a new key only for a genuinely
new task. The dashboard does not automatically replay uncertain writes.

The actor, request hash and original task ID are stored atomically with the task
and approval. Concurrent equal requests create one task/approval. A reused key
with different arguments/tenant/device receives 409. Replays report the original
task's current state; deleted original tasks return 409, not a new submission.
Authentication, current emergency stop and device policy checks still apply.
Keep submission records while retries are possible; there is no automatic expiry.

## Release checklist

1. Rotate any admin token or Google client secret previously shared in chat.
   Supply replacements through the host's secret/environment configuration only.
2. Confirm the deployment method and approved branch/commit before landing.
3. Run the Python tests, dashboard build and browser tests in CI. Back up the DB
   **before** starting a release that applies `004_workspace_operations.sql`.
4. Configure the Google web client's authorized redirect URI exactly:
   `https://YOUR_HOST/api/auth/oidc/callback`. Set the dashboard URL to the same
   HTTPS origin. Load the environment through the service/hosting platform:
   the Python entry point does not load `.env` automatically.
5. Deploy the API and the dashboard bundle together. Run:

   ```sh
   python deployment/smoke_check.py https://YOUR_HOST
   ```

   This checks readiness, rejection of anonymous identity requests and the
   branded frontend. It does not prove OAuth login succeeds.
6. In a fresh browser, complete Google sign-in, confirm viewer access, have an
   administrator change a test user's role, confirm old sessions are rejected,
   sign back in and sign out. Never put production tokens into browser tests.
7. Enroll a disposable agent, confirm its heartbeat, submit a read-only system
   information task, inspect its result, then review a sensitive test task through
   the approval flow. Do not run destructive commands as a smoke test.
8. Verify HTTPS/proxy routing, host firewall rules and rate limits. The existing
   rate limiter is per-process memory, not a shared distributed limiter.

## Backup and recovery

Backups contain sensitive identity/session/device data. Restrict permissions,
encrypt off-host copies and agree retention with the operator. Do not commit
backups or write tokens into backup scripts.

SQLite: use the backup API rather than copying a live WAL database file:

```sh
python -m ai_bridge.control.backup /PATH/control.db /PRIVATE/NEW-backup.db
```

The command refuses to overwrite any destination and verifies SQLite integrity.
For a recovery drill, run it again from the backup into a **new**, isolated DB
path. Start an isolated control plane with that DB, no live agents and no exposed
network port; verify users/devices/tasks/audit. Never overwrite the live database
as part of a test. A production restore requires a maintenance window, service
shutdown, preservation of the old DB/WAL files and explicit operator approval.

PostgreSQL: use the hosting provider's encrypted snapshots/PITR, or `pg_dump`
with credentials supplied privately through the process environment. Restore
with `pg_restore` into a new isolated database, verify migrations and record
counts, and run the same application checks. SQLite tests do not validate
PostgreSQL backup, query plans or cross-worker behavior.

Database credential key rotation is available through
`python -m ai_bridge.control.rotate_secrets`. Follow the maintenance-window,
backup and verification steps in `secret-key-rotation.md`; keep the old key
until a rotated-backup restore drill succeeds.
