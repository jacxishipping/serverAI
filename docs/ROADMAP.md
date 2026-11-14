# Engineering roadmap

This roadmap supersedes the pre-0.3 milestone checklist. Capability claims and
open work are tracked in `implementation-status.md`; the source-backed baseline
and detailed file plan are in `engineering-audit-2026-11-14.md`.

## Current phases

| Phase | Goal | Status |
|---|---|---|
| 0. Baseline and truth | Reconcile status docs, deployment profiles, runtime matrix and benchmark instrumentation | In progress |
| 1. Ownership and safety | Isolated browser sessions, destination controls, tool permission review and native-platform validation | In progress |
| 2. Communication and desktop reliability | Measure capture-to-render latency, reconnect, network loss, key release and multi-monitor behavior | In progress: capture/preparation metrics added; end-to-end reconnect and platform failure tests remain open |
| 3. Durable task orchestration | Task state/checkpoint/event contract, restart reconciliation and single-owner/shared scheduler semantics | In progress: task recovery plus database compare-and-set claims for schedules, triggers and custom agents; crash recovery for claimed work and broader lease ownership remain open |
| 4. Agent runtime | Bounded named responsibilities, shared context, dependencies, budgets and recovery | In progress: existing custom-agent step/tool bounds plus task dependencies; a durable supervisor and role handoff contract remain open |
| 5. Browser and coding workflows | Isolated browser workflows and end-to-end repository change/verification lifecycle | In progress: per-principal browser contexts and destination checks; end-to-end coding lifecycle evidence remains open |
| 6. Memory and inventory | Provenance-backed task/project memory and consistent device capabilities/inventory | In progress: project memory API and persistent heartbeat inventory; agent context retrieval and installed-app parity remain open |
| 7. Scale and production security | PostgreSQL pool and integration validation, shared coordination, secret/backup controls and tenant review | In progress: bounded pool, integration gate and single-worker deployment; live database, backup and shared-state validation remain open |
| 8. Acceptance and release | Load, latency, recovery, platform and clean deployment gates | Not started |

## Acceptance principles

- A proposed performance number is a target until measured on a documented
  hardware/network/deployment profile.
- Code presence is not platform validation; CI or host-run evidence must name
  the platform and the paths it covers.
- Approval and policy enforcement remain server-owned at every execution
  boundary, including browser, coding, workflow, and agent tools.
- Keep the modular monolith until benchmarks or coordination requirements show
  a concrete need to split services or add a queue.
- Before multi-worker deployment, all scheduler ownership, emergency-stop,
  OAuth pending state and task recovery must use shared durable coordination or
  deployment must enforce a single worker.

## Historical milestones

Earlier v0.2/v0.3 release milestones are retained in `CHANGELOG.md`. Their
checkmarks describe those release goals and do not certify the broader roadmap
or production readiness.
