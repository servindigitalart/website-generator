-- Generation durability layer — step tracking, callback state, retry metadata.
--
-- All columns are nullable so existing rows are unaffected.
-- The status constraint is extended to include 'deployed' (callback acknowledged)
-- and 'failed' (explicit terminal state distinct from 'error').

-- ── Extend status constraint ────────────────────────────────────────────────
-- Original: pending|generating|building|deploying|live|error|paused
-- Added:    deployed (callback ack'd), failed (terminal after retries)
ALTER TABLE clinic_websites
    DROP CONSTRAINT IF EXISTS clinic_websites_status_check;

ALTER TABLE clinic_websites
    ADD CONSTRAINT clinic_websites_status_check
    CHECK (status IN (
        'pending', 'generating', 'building', 'deploying',
        'live', 'deployed', 'failed', 'error', 'paused'
    ));

-- ── Step tracking ───────────────────────────────────────────────────────────
ALTER TABLE clinic_websites
    ADD COLUMN IF NOT EXISTS current_step          TEXT,
    ADD COLUMN IF NOT EXISTS last_step_completed   TEXT,
    ADD COLUMN IF NOT EXISTS step_started_at       TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS step_completed_at     TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS step_failed_at        TIMESTAMPTZ;

-- ── Failure details ─────────────────────────────────────────────────────────
ALTER TABLE clinic_websites
    ADD COLUMN IF NOT EXISTS failed_at             TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS last_error            TEXT;

-- ── Retry / correlation ─────────────────────────────────────────────────────
ALTER TABLE clinic_websites
    ADD COLUMN IF NOT EXISTS retry_count           INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS wg_job_id             TEXT;

-- ── Callback tracking ───────────────────────────────────────────────────────
ALTER TABLE clinic_websites
    ADD COLUMN IF NOT EXISTS callback_ok           BOOLEAN,
    ADD COLUMN IF NOT EXISTS callback_attempts     INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS callback_last_error   TEXT;

-- ── Vercel intermediate state ───────────────────────────────────────────────
-- vercel_deployment_id already exists (from 016). Add the polling URL separately
-- so it can be persisted as soon as Vercel responds (before step 6 completes).
ALTER TABLE clinic_websites
    ADD COLUMN IF NOT EXISTS vercel_deployment_url TEXT;

-- ── Site readiness tracking ─────────────────────────────────────────────────
ALTER TABLE clinic_websites
    ADD COLUMN IF NOT EXISTS readiness_verified_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS readiness_attempts    INTEGER DEFAULT 0;

-- ── Indexes for operational queries ────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_clinic_websites_current_step
    ON clinic_websites(current_step)
    WHERE current_step IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_clinic_websites_failed_at
    ON clinic_websites(failed_at)
    WHERE failed_at IS NOT NULL;
