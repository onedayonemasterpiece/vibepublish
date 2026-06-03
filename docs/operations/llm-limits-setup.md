# LLM Limits Setup

Status: `Fixed`

Canonical feature doc: `docs/features/llm-gateway/README.md`

## Apply SQL

Apply the migrations in `migrations/` in numeric order.

## Required Env

- `SUPABASE_URL`
- `SUPABASE_KEY`
- `SUPABASE_SERVICE_KEY` for privileged RPC/probe/sweep work
- `SUPABASE_SCHEMA`, usually `public`
- `GOOGLE_API_KEY`

## Probe

```bash
python scripts/inspect/probe_supabase_rpc.py google_ai_reserve --schema public --use-service
```

