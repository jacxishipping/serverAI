ALTER TABLE tasks ADD COLUMN IF NOT EXISTS checkpoint_json TEXT NOT NULL DEFAULT '{}';

CREATE TABLE IF NOT EXISTS task_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id TEXT NOT NULL,
  tenant TEXT NOT NULL DEFAULT 'default',
  event_type TEXT NOT NULL,
  actor TEXT NOT NULL DEFAULT '',
  event_json TEXT NOT NULL DEFAULT '{}',
  created_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_task_events_task ON task_events(task_id, id);
CREATE INDEX IF NOT EXISTS idx_task_events_tenant ON task_events(tenant, created_at DESC);

CREATE TABLE IF NOT EXISTS task_dependencies (
  task_id TEXT NOT NULL,
  depends_on_task_id TEXT NOT NULL,
  created_at DOUBLE PRECISION NOT NULL,
  PRIMARY KEY (task_id, depends_on_task_id)
);
CREATE INDEX IF NOT EXISTS idx_task_dependencies_parent ON task_dependencies(depends_on_task_id);
