-- Add Gemma 4 model limits to the shared Google AI limiter.
--
-- Verified against this project's Google AI Studio quota UI on 2026-04-06:
--   * gemma-4-31b: 15 RPM, Unlimited TPM, 1500 RPD
--   * gemma-4-26b-a4b: 15 RPM, Unlimited TPM, 1500 RPD
--
-- The limiter schema stores TPM as INT, so "Unlimited TPM" is represented by
-- the PostgreSQL INT max sentinel 2147483647.

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
        ('gemma-4-31b', 15, 2147483647, 1500, 1000),
        ('gemma-4-26b-a4b', 15, 2147483647, 1500, 1000)
) AS s(model, rpm, tpm, rpd, tpm_reserve_extra)
WHERE m.model = s.model;

INSERT INTO google_ai_model_limits (model, rpm, tpm, rpd, tpm_reserve_extra)
SELECT s.model, s.rpm, s.tpm, s.rpd, s.tpm_reserve_extra
FROM (
    VALUES
        ('gemma-4-31b', 15, 2147483647, 1500, 1000),
        ('gemma-4-26b-a4b', 15, 2147483647, 1500, 1000)
) AS s(model, rpm, tpm, rpd, tpm_reserve_extra)
WHERE NOT EXISTS (
    SELECT 1 FROM google_ai_model_limits m WHERE m.model = s.model
);

COMMIT;
