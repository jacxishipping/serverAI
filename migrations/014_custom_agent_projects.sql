ALTER TABLE custom_agents ADD COLUMN IF NOT EXISTS project_id TEXT;
CREATE INDEX IF NOT EXISTS idx_custom_agents_project
  ON custom_agents(tenant, project_id);
