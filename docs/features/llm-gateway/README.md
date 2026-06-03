# LLM Limit Management Framework

Status: `Fixed`

Component: `google_ai.GoogleAIClient`

## Goal

Provide one shared gateway for Google AI / Gemini / Gemma calls with quota control, auditability, and fail-fast behavior.

## Requirements

- [x] `Not confirmed by user` Provider calls go through `GoogleAIClient` by default.
- [x] `Not confirmed by user` Quota state can be stored in Supabase tables named `google_ai_*`.
- [x] `Not confirmed by user` `google_ai_reserve`, `google_ai_mark_sent`, and `google_ai_finalize` support atomic reserve/finalize behavior.
- [x] `Not confirmed by user` The gateway raises `RateLimitError` immediately instead of sleeping inside the client.
- [x] `Not confirmed by user` Secrets are read from env/Kaggle/encrypted bundles and are not stored in Supabase.
- [x] `Not confirmed by user` Provider errors are retried only for retryable failures.
- [x] `Not confirmed by user` Stale reserved rows can be swept with `google_ai_sweep_stale`.

## Files

- Client package: `google_ai/`
- SQL migrations: `migrations/001_google_ai.sql` through `migrations/005_gemini_flash_lite_limits.sql`
- RPC probe: `scripts/inspect/probe_supabase_rpc.py`
- Stale sweep: `scripts/inspect/sweep_google_ai_stale.py`
- Env template: `.env.example`

## Setup

1. Install dependencies from `requirements.txt` or `pyproject.toml`.
2. Set `SUPABASE_URL`, `SUPABASE_KEY`, and preferably `SUPABASE_SERVICE_KEY`.
3. Set `GOOGLE_API_KEY`.
4. Apply migrations in order:
   - `001_google_ai.sql`
   - `002_google_ai_rpc_rollout.sql`
   - `003_google_ai_sweep_stale.sql`
   - `004_google_ai_gemma4_limits.sql`
   - `005_gemini_flash_lite_limits.sql`
5. Insert metadata rows into `google_ai_api_keys` for active env keys. Supabase stores metadata only, never secret values.

## RPC Checks

```bash
python scripts/inspect/probe_supabase_rpc.py google_ai_reserve --schema public --use-service
python scripts/inspect/probe_supabase_rpc.py google_ai_mark_sent --schema public --use-service
python scripts/inspect/probe_supabase_rpc.py google_ai_finalize --schema public --use-service
```

## Usage

```python
from google_ai import GoogleAIClient, RateLimitError

client = GoogleAIClient(supabase_client=supabase_client, consumer="vibepublish")

try:
    text, usage = await client.generate_content_async(
        model="gemini-3.1-flash-lite",
        prompt="Draft a concise publishing summary.",
    )
except RateLimitError:
    # Defer or reschedule at the caller level.
    raise
```

## Notes

- `model` is normalized for quota tables.
- Provider model names may differ from limiter model names.
- `GOOGLE_AI_ALLOW_RESERVE_FALLBACK=0` enables strict mode when Supabase RPCs must exist.
- `GOOGLE_AI_PROVIDER_TIMEOUT_SEC` can bound provider calls.

