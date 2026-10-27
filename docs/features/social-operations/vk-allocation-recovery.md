# VK allocation-only recovery (legacy case)

Status: **historical compatibility**, not a publication prerequisite. W1 worker
source is offline tested; live acceptance remains with the integrator.

A failed video upload may have allocated a native video before any VK
`wall.post` call. Earlier releases allowed an explicit, read-only
`publication_update.reconcile` to classify that precise case by its existing
checkpoint and diagnostics. This operation never uploads or posts another item;
it does not infer that a wall publication succeeded.

The current publication worker does **not** quarantine the whole VK connection
because of that historical attempt. Another authorized publication proceeds
independently. For a new attempt the same fixed deadline controls preparation,
lane waiting, retries and recovery. A recoverable pre-dispatch failure retries;
a known wall post ID is accepted as publication success; a dispatched attempt
without a confirmable post ID ends in a clear `publication_unconfirmed` refusal
when its budget expires. It never asks the user to verify a native queue by hand.

Existing authority checks, immutable plans and dispatch markers continue to
protect a subsequent edit or replacement of the *same* object. Historical
allocation-only records may be inspected without rewriting the old ledger.

Verification is limited to fake transports and local tests. No real VK calls,
deployment or production database mutation were performed in W1.
