# Task lifecycle

The control plane owns task state transitions. Device agents claim work with a
queued-to-running compare-and-set. The agent result endpoint records completed,
failed, cancelled, or timed-out outcomes; operator cancellation and restart
reconciliation can also end a running task. Approval decisions
move a task from needs-approval to queued or cancelled in the same transaction
as the approval state change. Cancellation is compare-and-set against active
states and fails waiting dependents in the same transaction.

| Current state | Allowed transition | Owner |
|---|---|---|
| queued | running, cancelled, failed | agent claim, operator cancel, dependency failure |
| needs_approval | queued, cancelled, failed | approval decision, cancel, dependency failure |
| running | completed, failed, cancelled, timed_out | agent result, operator cancel, restart reconciliation |
| failed, cancelled, timed_out | queued | explicit administrator retry |
| completed | none | terminal; create a new task to execute again |

The task update API cannot set running or terminal states directly. It permits
payload edits only while queued or terminal except completed, and limits retries
to failed/cancelled/timed-out work. A retry clears the current result and
checkpoint, records the previous result's byte length and SHA-256 in the task
event, and reevaluates policy and approval requirements. It does not replay a
task automatically after a process restart because external side effects may
already have occurred.

Task updates, claims, results, cancellation and approval decisions use
compare-and-set or transactional state checks so concurrent requests cannot
silently overwrite a newer state. This contract does not provide cooperative
interruption of an already-running agent tool; cancellation prevents the result
from being accepted and records the task as cancelled, but a tool already
executing on the device may finish its side effect.
