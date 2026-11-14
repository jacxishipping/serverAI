CREATE TABLE IF NOT EXISTS project_memories (
  id TEXT PRIMARY KEY,
  tenant TEXT NOT NULL DEFAULT 'default',
  project_id TEXT NOT NULL,
  title TEXT NOT NULL,
  content TEXT NOT NULL,
  source TEXT NOT NULL,
  source_task_id TEXT,
  created_by TEXT NOT NULL,
  created_at DOUBLE PRECISION NOT NULL,
  expires_at DOUBLE PRECISION
);
CREATE INDEX IF NOT EXISTS idx_project_memories_lookup
  ON project_memories(tenant, project_id, created_at DESC);
