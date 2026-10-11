# Provider diagnostics in the existing ledger

The normal status tool and its progress cursor retrieve bounded provider diagnostics.
Messages beginning with `provider_diagnostic ` contain a JSON metadata object.
No new endpoint, credential, database table, logging service or client argument is required.

Each record is correlated with operation and publication; publication attempts also
include attempt ID, provider, destination, current ledger stage and authoritative
dispatch state. Calls record start and finish/failure, operation/subphase, elapsed
milliseconds and safe exception category. VK includes numeric HTTP/API error codes
and numeric Retry-After seconds when supplied. Telegram includes RPC category/code
and FloodWait/SlowMode seconds. MAX records key navigation, composition, scheduling,
submit and readback phases before existing error conversion. Readback summaries
include observed outcome, item count and media-check kind where available.

Diagnostics never contain raw request/response bodies, full URLs, credentials,
arbitrary exception/provider messages, DOM or publication text. VK upload events
retain only sanitized hostname, source asset SHA, actual wire byte count/MIME,
HTTP status, safe peer IP/family where available, request framing and bounded
allowlisted Server/Via/hex request identifiers. DNS and combined header-wait timing
are observations; header-wait is not claimed to be isolated TLS/upload/TTFB time.
Direct URL rejection emits hostname plus a closed reason before transport entry,
without DNS or upload. VK API errors use closed categories and fixed safe text;
raw error_msg is never persisted. A closed validator rejects unknown
fields, nonfinite/out-of-range numbers and malformed labels. Maximum512 diagnostic
events per operation; the final slot explicitly marks truncation. Complete JSON
records fit the existing 1000-character message cap, retaining core correlation
and outcome fields while dropping optional metadata with an omission marker.
Existing status
pagination applies, so follow the progress cursor rather than inspecting only the
first page. Failed/unknown operations retain the diagnostic events across restart.

These are observations, not retry authorization. Existing before-effect markers,
quarantine, idempotency, unknown-outcome handling and recovery admission remain
unchanged. A diagnostic sink failure cannot cause a provider action to be repeated.
A phase-start event without a matching finish can indicate interruption; it alone
does not prove whether a provider effect happened.

Coverage: task-local concurrency; pre/post-dispatch failure and restart/cursor
retrieval; RPC cooldown fields; VK status/API errors; MAX original exceptions before
masking; secret-sentinel exclusion and unchanged no-repeat behavior; rejected URL
privacy, multipart byte/framing evidence, hostile response headers and final JSON
budget. Missing metadata remains unknown, and a response header alone cannot
prove which infrastructure component caused an HTTP 502/504.
