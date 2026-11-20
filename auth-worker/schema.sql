CREATE TABLE IF NOT EXISTS auth_flows (
  state_hash TEXT PRIMARY KEY,
  verifier TEXT NOT NULL,
  return_to TEXT NOT NULL,
  expires_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
  id_hash TEXT PRIMARY KEY,
  github_id TEXT NOT NULL,
  login TEXT NOT NULL,
  encrypted_tokens TEXT NOT NULL,
  csrf_token TEXT NOT NULL,
  expires_at INTEGER NOT NULL,
  refresh_lock_until INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS dispatches (
  fixture_id INTEGER PRIMARY KEY,
  state TEXT NOT NULL,
  run_url TEXT NOT NULL,
  created_at INTEGER NOT NULL
);
