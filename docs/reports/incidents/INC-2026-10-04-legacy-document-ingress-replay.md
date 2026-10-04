# Legacy source ingress replay after purge — 2026-10-04

Engineering fix; feature status remains `Not confirmed by user`.
Registry: `inc_58662c9d0181b6bb3a6b35df`.

A final actual HTTP binary-ingress replay on canonical main returned
`422 asset_not_available` for the owned PDF and DjVu controls. Their original
assets were already purged, and their ingress operations predated durable
`document_receipt` metadata. They had been admitted before rollout and safely
recovered with `retry_failed`, bypassing the new-admission metadata upgrade.
Original media-store put replay remained verified and added zero publications.

For an absent document asset, replay now returns the original scalar receipt
from the immutable, complete, owner-scoped `asset_ingress` intent: exact MIME/SHA,
original asset identity and zero generic-document dimensions. It does not create
bytes, an asset, a publication or a provider effect. Images do not acquire this
fallback; another actor/key or mismatched upload intent remains denied.

Regression explicitly removes legacy receipt metadata after put admission and
before verification/purge, modelling in-flight rollout recovery. Focused media
and authenticated-ingress tests passed. Actual PDF/DjVu HTTP replay and final
canonical source identity/readback are retained in the RKB archive acceptance
artifact directory; final runtime SHAs are returned to the owner.
