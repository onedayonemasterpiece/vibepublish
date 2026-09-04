# Architecture Overview

Status: `Draft`

`vibepublish` is a standalone publishing system with feature-owned requirements.
Architecture decisions remain canonical in the corresponding feature document.

## Current committed component

- `llm_gateway`: Google AI / Supabase limit-control framework.

## Fixed target component

- `social_operations`: independent DevCoveer service for Telegram, VK and MAX,
  exposed through MCP and an ordinary service API. It owns provider connections,
  destination sets, platform rendering, durable execution, scheduling, readback
  and audit. EventsBot becomes a client after its reusable provider code and
  regression tests are extracted. See
  `docs/features/social-operations/README.md`.

```text
ChatGPT / LADENO / EventsBot / other clients
                     |
                 MCP or API
                     |
          VibePublish Social Operations
                     |
          Telegram | VK | MAX adapters
```
