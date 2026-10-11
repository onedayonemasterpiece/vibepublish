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

Diagnostics never contain raw request/response bodies, URLs, headers, credentials,
exception messages, DOM or publication text. A closed validator rejects unknown
fields, nonfinite/out-of-range numbers and malformed labels. Maximum512 diagnostic
events per operation; the final slot explicitly marks truncation. Existing status
pagination applies, so follow the progress cursor rather than inspecting only the
first page. Failed/unknown operations retain the diagnostic events across restart.

These are observations, not retry authorization. Existing before-effect markers,
quarantine, idempotency, unknown-outcome handling and recovery admission remain
unchanged. A diagnostic sink failure cannot cause a provider action to be repeated.
A phase-start event without a matching finish can indicate interruption; it alone
does not prove whether a provider effect happened.

Coverage: task-local concurrency; pre/post-dispatch failure and restart/cursor
retrieval; RPC cooldown fields; VK status/API errors; MAX original exceptions before
masking; secret-sentinel exclusion and unchanged no-repeat behavior.
