-- Register gemini-3.1-flash-lite in the shared Google AI limiter.
--
-- Used by Smart Update facts_extract and main writer stages as the primary
-- model after the 2026-05-09 cutover from gemma-4-31b-it (which entered an
-- ~58% 5xx INTERNAL window on Google's side, see the same-day investigation).
--
-- Verified against this project's Google AI Studio quota UI on 2026-05-09:
--   * gemini-3.1-flash-lite (Free Tier): 15 RPM, 250000 TPM, 500 RPD
--
-- We apply a 10% safety margin on RPM/RPD because the limiter only blocks at
-- the boundary; a small buffer below the published cap avoids burning a key
-- for the day on borderline accounting drift between Supabase and Google.
-- TPM gets a 4% margin (just enough to leave reserve_extra room for a single
-- input-token-spike event).

BEGIN;

UPDATE google_ai_model_limits AS m
SET
    rpm = s.rpm,
    tpm = s.tpm,
    rpd = s.rpd,
    tpm_reserve_extra = s.tpm_reserve_extra,
    updated_at = NOW()
FROM (
    VALUES
        ('gemini-3.1-flash-lite', 13, 240000, 450, 1000)
) AS s(model, rpm, tpm, rpd, tpm_reserve_extra)
WHERE m.model = s.model;

INSERT INTO google_ai_model_limits (model, rpm, tpm, rpd, tpm_reserve_extra)
SELECT s.model, s.rpm, s.tpm, s.rpd, s.tpm_reserve_extra
FROM (
    VALUES
        ('gemini-3.1-flash-lite', 13, 240000, 450, 1000)
) AS s(model, rpm, tpm, rpd, tpm_reserve_extra)
WHERE NOT EXISTS (
    SELECT 1 FROM google_ai_model_limits m WHERE m.model = s.model
);

COMMIT;
