-- ── EXISTING TABLE (from your auth plugin — already in your DB) ────────────
-- CREATE TABLE users (
--     id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
--     email TEXT UNIQUE NOT NULL,
--     hashed_password TEXT NOT NULL,
--     username TEXT UNIQUE,
--     profile_pic_url TEXT,
--     is_onboarded BOOLEAN DEFAULT FALSE,
--     created_at TIMESTAMPTZ DEFAULT NOW()
-- );

-- ── NEW TABLE: user_progress ─────────────────────────────────────────────
-- Run this in your Supabase SQL editor

CREATE TABLE IF NOT EXISTS user_progress (
    id                  UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    topic               TEXT,
    current_level       INT DEFAULT 1 CHECK (current_level BETWEEN 1 AND 5),
    diagnostic_attempts INT DEFAULT 0 CHECK (diagnostic_attempts BETWEEN 0 AND 3),
    diagnostic_passed   BOOLEAN DEFAULT FALSE,
    hint_stage          INT DEFAULT 0 CHECK (hint_stage BETWEEN 0 AND 2),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

-- Auto-update the updated_at timestamp on every row change
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_user_progress_updated_at
    BEFORE UPDATE ON user_progress
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ══════════════════════════════════════════════════════════════════════════
-- PANDORA'S VAULT — COMPLETE RLS POLICY SETUP
-- Run this entire file in your Supabase SQL Editor after unpausing.
-- ══════════════════════════════════════════════════════════════════════════
--
-- HOW THE BACKEND AUTHENTICATES:
--   Your backend uses a custom JWT (not Supabase Auth).
--   It queries Supabase via the SERVICE ROLE key (SUPABASE_KEY in .env).
--   The service role key BYPASSES RLS entirely — so your Python backend
--   will always work regardless of these policies.
--
--   RLS policies here protect against:
--   1. Direct API access from malicious clients using the anon key
--   2. Future frontend-direct queries if you ever add those
--
-- ══════════════════════════════════════════════════════════════════════════

-- ── STEP 1: Drop any old/partial policies first (safe to run multiple times)

DROP POLICY IF EXISTS "Users can read own progress"        ON user_progress;
DROP POLICY IF EXISTS "Users can insert own progress"      ON user_progress;
DROP POLICY IF EXISTS "Users can update own progress"      ON user_progress;
DROP POLICY IF EXISTS "Users can delete own progress"      ON user_progress;
DROP POLICY IF EXISTS "Users can read own profile"         ON users;
DROP POLICY IF EXISTS "Users can update own profile"       ON users;
DROP POLICY IF EXISTS "Users can insert own profile"       ON users;
DROP POLICY IF EXISTS "Service role full access users"     ON users;
DROP POLICY IF EXISTS "Service role full access progress"  ON user_progress;

-- ── STEP 2: Make sure RLS is enabled on both tables

ALTER TABLE users         ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_progress ENABLE ROW LEVEL SECURITY;

-- ══════════════════════════════════════════════════════════════════════════
-- users table
--
-- Backend operations (from users.py):
--   signup:  INSERT a new user row
--   login:   SELECT by email (needs hashed_password)
--   onboard: UPDATE username, profile_pic_url, is_onboarded by id
--   get_me:  SELECT * by id
--   profile: UPDATE username/profile_pic_url by id
--
-- The backend uses SUPABASE_KEY (service role) which bypasses RLS.
-- These policies protect the anon key path only.
-- ══════════════════════════════════════════════════════════════════════════

-- Anyone can sign up (insert a new row with no prior auth)
CREATE POLICY "Allow public signup"
ON users FOR INSERT
TO anon, authenticated
WITH CHECK (true);

-- A user can read their own row
CREATE POLICY "Users can read own profile"
ON users FOR SELECT
TO authenticated
USING (id::text = current_setting('request.jwt.claims', true)::json->>'sub');

-- A user can update their own row
CREATE POLICY "Users can update own profile"
ON users FOR UPDATE
TO authenticated
USING (id::text = current_setting('request.jwt.claims', true)::json->>'sub')
WITH CHECK (id::text = current_setting('request.jwt.claims', true)::json->>'sub');

-- ══════════════════════════════════════════════════════════════════════════
-- user_progress table
--
-- Backend operations (from session.py):
--   GET /session:   SELECT * WHERE id = current_user["id"]
--   PATCH /session: INSERT {id, ...fields} OR UPDATE fields WHERE id = user_id
--   DELETE /session: DELETE WHERE id = user_id
--
-- The id column in user_progress = user's UUID (same as users.id).
-- ══════════════════════════════════════════════════════════════════════════

-- A user can read their own progress row
CREATE POLICY "Users can read own progress"
ON user_progress FOR SELECT
TO authenticated
USING (id::text = current_setting('request.jwt.claims', true)::json->>'sub');

-- A user can insert their own progress row (first time session save)
CREATE POLICY "Users can insert own progress"
ON user_progress FOR INSERT
TO authenticated
WITH CHECK (id::text = current_setting('request.jwt.claims', true)::json->>'sub');

-- A user can update their own progress row
CREATE POLICY "Users can update own progress"
ON user_progress FOR UPDATE
TO authenticated
USING (id::text = current_setting('request.jwt.claims', true)::json->>'sub')
WITH CHECK (id::text = current_setting('request.jwt.claims', true)::json->>'sub');

-- A user can delete their own progress row (reset session)
CREATE POLICY "Users can delete own progress"
ON user_progress FOR DELETE
TO authenticated
USING (id::text = current_setting('request.jwt.claims', true)::json->>'sub');

-- ══════════════════════════════════════════════════════════════════════════
-- IMPORTANT NOTE ABOUT YOUR SETUP:
-- ══════════════════════════════════════════════════════════════════════════
--
-- Your backend in database.py uses:
--   supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
--
-- If SUPABASE_KEY in your .env is the SERVICE ROLE key (starts with "eyJ..."
-- and is the longer key from Supabase > Settings > API > service_role):
--   → RLS is completely bypassed for your backend. These policies only
--     protect against direct browser/anon access. Your app will work fine.
--
-- If SUPABASE_KEY is the ANON key (shorter, labeled "anon public"):
--   → RLS DOES apply to your backend queries. The policies above use
--     current_setting('request.jwt.claims') which only works with
--     Supabase Auth JWTs — NOT your custom JWTs. In this case, the
--     safest fix is to switch to the service role key in your .env.
--
-- RECOMMENDATION: Use service role key in your .env for the backend.
-- Your custom JWT auth is already secured at the FastAPI layer.
--
-- To check which key you're using:
--   Service role key: Supabase Dashboard > Settings > API > service_role
--   Copy it into SUPABASE_KEY= in your .env file.
-- ══════════════════════════════════════════════════════════════════════════