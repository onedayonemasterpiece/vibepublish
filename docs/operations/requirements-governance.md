# Requirements Governance

Status: `Fixed`

## Policy

- Every feature needs one canonical requirements document.
- Before implementation, read the relevant canonical document and check for conflicts.
- If no document exists, create a draft feature document before changing behavior.
- Requirement changes must be proposed as deltas against the current canonical text.
- User-reported defects must set affected requirement items to `Not done` or `Not confirmed by user`.

## Status Markers

- `Draft`: proposed but not fixed.
- `Fixed`: accepted as a contract.
- `Not done`: known incomplete or broken.
- `Not confirmed by user`: internally checked but awaiting user confirmation.
- `Done`: explicitly confirmed by user after testing or review.

## Requirement Review Buckets

Use these buckets before proposing requirement edits:

- `Already present`
- `Needs clarification`
- `Missing`

