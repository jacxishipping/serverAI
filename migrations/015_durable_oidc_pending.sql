CREATE TABLE IF NOT EXISTS oidc_pending (
  state TEXT PRIMARY KEY,
  nonce TEXT NOT NULL,
  created_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_oidc_pending_created_at ON oidc_pending(created_at);
