# Private original image upload

Status: **Not confirmed by user**. This is authenticated HTTP ingress, not a
claim that arbitrary MCP clients can bridge chat attachments automatically.

POST `/v1/assets` with the existing service bearer token, `Idempotency-Key`
(1–200 printable ASCII characters), an exact image Content-Type (`image/png`,
`image/jpeg`, `image/webp`), and binary bytes. Either current `publish` or `visual`
scope is required. Maximum body is 20 MiB, with the existing 10-second total
read deadline. All other JSON and MCP bodies retain their 512 KiB limit.

The service validates decoding, actual MIME, dimensions and tenant storage quota.
It stores the original privately and a sanitized PNG derivative without EXIF.
The returned `asset_id` identifies that derivative, not a byte-identical upload;
`source_sha256` identifies original bytes. This performs **no AI generation,
retouching, composition or publication**. GET `/v1/assets/{asset_id}` reads the
private derivative using the same principal's authorized token. Use the asset
in publication media or as a visual source: `{"source":{"kind":"asset","id":"asset_..."}}`.

Success is HTTP 200 with `asset_id`, `sha256`, `source_sha256`, `mime`, `width`,
`height`, and `idempotency_key`. Durable replay with the same key, bytes and MIME
returns exactly the same receipt without additional asset storage. Reusing a key
for different content conflicts; keys remain principal-scoped and share the
existing command key registry. Inserts and key admission commit atomically.
Malformed requests return 422, conflicts 409, unauthorized tokens 401, missing
scope 403, body limit 413, deadline 408. No URL fetching or upload tickets exist.
