-- Bind non-admin user accounts to one tenant for authorization checks.
ALTER TABLE users ADD COLUMN IF NOT EXISTS tenant TEXT NOT NULL DEFAULT 'default';
