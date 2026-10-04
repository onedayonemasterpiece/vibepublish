# Dedicated KB connection topic resolution — 2026-10-04

Status: `Not confirmed by user`; live verification belongs in the source-archive
acceptance report. Registry: `inc_14e6b46cfbc3549c18b86e40`.

During the authorized KB archive rollout, two owner bindings to the same private
Telegram forum made topic resolution ambiguous. Binary ingress succeeded, but
source put admission failed; source staging remained intact and no source archive
was falsely marked verified. The first alias-aware core fix exposed the production
IngressApplication override, whose signature did not yet accept the alias. Actual
public tool readback returned the unexpected-keyword error before provider work.

Both core and owner-direct ingress now select the explicitly authorized alias for
put/list, preserve the unique ordinary connection for existing URL-only calls,
and reject other ambiguous/wrong-chat choices. Regression uses the actual public
IngressApplication, not only the core base class. Structured topic selection logs
record connection identity and explicit selection without private payloads.

The source extension also preserves exact PDF/DjVu evidence types at the native
port/output schema boundary and purges source ingress originals/transfer clones
only after verification. Durable ingress receipts survive byte removal, protecting
lost-response request-key replay. No credential replacement, new authorization,
public post or rights expansion was used.

Related historical VK hydration and scoped basic-group scheduling incidents were
reviewed; their provider gates are independent and their credentials/rights remain
unchanged. RKB additionally bounded its source request identity to the existing
128-character product limit; previous oversized source puts were rejected before
an operation/provider effect existed.
