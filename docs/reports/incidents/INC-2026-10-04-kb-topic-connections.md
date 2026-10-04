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

Engineering verification completed: actual public URL-only topic read operation
`op_02a3bd87947c41f5aa47e92a96993c8a` finished verified on
`devcoveer2-telegram`. Eight exact source publications finished verified on
`devcoveer2-knowledge-base`, with two owned PDF/DjVu controls in topic /2 and the
new illustration in /4. Replaying all eight source request keys added zero
publications. Original Gause bytes were freshly downloaded and SHA-verified;
its source staging was deleted only after verified archival.

Native DOCUMENT admission also needed a narrow PDF/DjVu allowance and safe
filename metadata; ordinary image/video limits and rendering gates remain.
Eight pre-dispatch blocked operations were recovered through existing
`retry_failed`, retaining original operation/attempt identities. No uncertain
operation was resent. Native-prepare tests now exercise the real Telegram
adapter rather than only a fake core provider.

Full mandatory CI at implementation `fa709cb88552044cc2731d259432a05546f49a03`
passed Python 3.12/3.13 verify, core recovery and Telegram P0 gates:
https://github.com/onedayonemasterpiece/vibepublish/actions/runs/37215614348.
The initial full local Python 3.14 run at the earlier implementation passed
1,173 tests/219 subtests. A subsequent local run was interrupted after four
browser observation deadline failures and 315 passing tests; all four affected
cases passed separately (42.56 seconds). Supported-version full CI is the
complete final-code regression evidence. Retained raw evidence is in the RKB
20261004T151348Z Telegram source archive task directory.

The feature remains `Not confirmed by user`; engineering acceptance and closure
of this rollout incident do not imply user confirmation of a canonical requirement.
