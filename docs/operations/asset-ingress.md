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
scope 403, body limit 413, deadline 408. The binary route accepts no URL or upload tickets.

Decode runs off the HTTP event loop, limited to two concurrent decodes per
application process; busy uploads return429. This does not bound total concurrent
receive buffers beyond the per-request body limit and upstream connection limits.
On DevCoveer the dedicated VibePublish virtual host allows20MiB; existing hosts
retain their limits. Uploads above1MiB have been read back through public HTTPS.

## Chat attachment import through MCP

Status: **Not confirmed by user**. `vibepublish_visual` also accepts
`command: {kind: "import"}`, a top-level `file`, and `request_key`. The tool's
`_meta["openai/fileParams"] = ["file"]` follows the
[official file-input contract](https://developers.openai.com/plugins/reference#Define-file-inputs).
The client supplies `file.download_url` and `file.file_id`; `mime_type` and
`file_name` are declared but optional. No manual HTTP upload or server path is
required. Whether a particular connected client delivers real attachment objects
still requires client-level acceptance; IDs/URLs must never be fabricated.

The verified standard receipt's `resource_id` is the private sanitized asset for
publish/tune/compose. Import performs no generation or publication. Principals
with publish but no visual scope see only the import command, not generation.
Import requires the file object and explicit key; other visual commands reject
file objects (import each reference first). MIME is sniffed from actual bytes;
provided MIME, if present, must match. Filename is display metadata only and is
not used as a path or retained. The default original/derivative policy above
still applies.

Downloads are HTTPS/443 only, with validated public DNS addresses pinned for the
connection while retaining TLS hostname verification. No redirects, proxies,
cookies, caller credentials, local paths or compressed HTTP bodies are accepted.
DNS and response reading share a 10-second deadline and 20 MiB byte limit.
URLs, query signatures and filenames are never stored in the ledger or errors.
The ledger records a digest of the client file ID and MIME declaration, and the
owned asset. Same-key replay returns the existing receipt without fetching the
possibly expired URL. A different file ID/declaration under the same key conflicts.
The client file ID is an immutable client attachment identity, not a claim that
the service verified its provenance with a separate OpenAI API.

Chat imports are limited to two concurrent download/decode jobs per application
process; excess jobs fail `asset_ingress_busy` rather than queue unbounded buffers.

Permission-surface correction: older transport assertions expected the visual tool
absent for publish-only principals. It is now present strictly for attachment
import. Real MCP transport tests enforce the import-only schema and reject direct
generate/tune/select calls, while retaining existing private-asset isolation and
inline-generation denial checks. This is not an additional visual generation grant.
