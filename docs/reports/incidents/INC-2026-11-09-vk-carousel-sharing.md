# INC-2026-11-09-vk-carousel-sharing

Status: `Open / Not done`. Registry: `inc_71a1cfe740f9c1e2f0de58dd`.

## Summary and impact

The owner cannot share manually released VK carousels 270 and 259 in community
241261191. The requirement is a normally shareable published carousel, with every
photo visible. Successful uploads, API reads and CI do not establish that result.
Source: [owner report](https://mira-projects.slack.com/archives/C0CFP01K292/p1794217987027749)
and [original requirement](https://mira-projects.slack.com/archives/C0CFP01K292/p1794126804365119).

## Observations, 2026-11-09 10:29–10:35 UTC

- Existing VK transport and production credential loader performed read-only
  `wall.getById` calls for 270, 259 and control 268. All are published original
  posts; postponed origins are 267, 258 and 66. None returns top-level `can_repost`,
  `can_publish`, `friends_only` or `primary_attachments_mode`. There is no protected
  copyright, copy history or Donut-only marker. Absence is not a refusal flag.
- `wall.get` across ten published controls likewise omits these permission flags.
  An isolated diagnostic using API 5.131 instead of production 5.199 does not
  reveal a difference. No runtime API version was changed.
- Photos in the published posts belong to the community and album -7. Scheduled
  controls use album -8. One control photo has a `post_id`, most do not; this is
  not yet a causal distinction. No access keys or download URLs were retained.
- Ordinary MCP read `op_73aa414c5c834b06936ed375877ab9e1` completed in 9.94 seconds:
  all six post-270 JPEGs downloaded and verified at 1080×1350. Read
  `op_f4ef0909d19d4c67b2f966e347b70391` completed in 11.01 seconds with all seven
  post-259 photos. This does not establish native mobile rendition availability.
- Negative search `op_667228ade5ba43bca8a7356c3ecadfea` completed in 8.74 seconds
  with zero results; provider search itself took 460 ms.
- The existing browser profile `vk-owner-communities` shows VK's login page for
  post 270. It cannot verify the authenticated Share control. No login change,
  publication, repost, media upload or provider edit was performed.

## Corrected sharing-field diagnosis, 2026-11-09 12:21 UTC

The earlier safe projections listed the top-level `likes` key but discarded its
contents. Their missing top-level `can_publish`/`can_repost` fields therefore
did not establish that the native response lacks sharing permissions.

The official [VK base object schema](https://github.com/VKCOM/vk-api-schema/blob/master/base/objects.json)
defines optional `likes.can_publish` for the **current API user** and optional
boolean `likes.repost_disabled`. Omission is not a false value.

One bounded `wall.getById` 5.199 read through the existing production credential
loader, user-token reader role and unchanged transport returned:

| Published post | Native postponed origin | likes.can_publish | likes.repost_disabled |
| --- | --- | --- | --- |
| 270, affected | 267 | 1 | false |
| 259, affected | 258 | 1 | false |
| 268, ordinary control | 66 | 1 | false |
| 250, ordinary control | 65 | 1 | false |
| 246, control | 64 | 1 | false |
| 244, control | 240 | 1 | false |
| 242, control | 63 | 1 | false |

All seven have `from_id=owner_id=-241261191`. Their `reposts.count`,
`wall_count`, `mail_count` and `user_reposted` are zero, which does not
establish a prohibition. The affected posts have no copy history, Donut-only
marker or protected copyright. Affected and multi-photo controls both return
`carousel_offset=0`; this field is not an authoritative grid/carousel mode.

The request completed successfully in 1.813 seconds, including loader/startup.
Receipt: `op_97a7a862e15b3d7f8f3e0f64`; safe native fields:
`vk-nested-sharing-20261109T1222.json` in the existing retained directory.
There were zero provider mutations. This is explicit API permission evidence,
**not** a successful Share action in the owner's or a reader's application.

A separate bounded `groups.getById` read at 12:26:54 UTC confirms the community
is open (`is_closed=0`). The API account is an administrator (`is_admin=1`,
`admin_level=3`), so the transport role named `reader` must not be interpreted as
an ordinary non-admin reader. Receipt: `op_1144d66d050b4a8656236885`;
safe evidence: `vk-sharing-community-20261109.json` in the same retained directory.

The relevant `adapters/vk.py` blob is identical in the actual worker release
88225204 and current main. Creation sets `from_group=1`, `signed=0`,
the ordered attachments and the requested native schedule/mode. Existing-post
edits send the observed/new attachments with `wall.edit`. Neither this path nor
the transport whitelist supplies a sharing prohibition. The official public
schema does not describe `primary_attachments_mode`; it establishes neither a
carousel-sharing prohibition nor mode preservation/reset on edit.

## Separate SQLite recurrence

Registry `inc_247a251746662872b81bffbc` remains the runtime incident. Complete
worker log search over 09:32–10:32 returned all 16 slow-maintenance records.
Before the host reboot, retention held the writer for tens of seconds: at
10:06:04 maintenance took 59.135 seconds, retention 57.410 seconds;
attempt references took 24.993 seconds wall / 232 ms thread CPU, carousel
references 25.336 seconds wall / 320 ms thread CPU.

The dated sysstat archive confirms severe common-host pressure in the overlapping
10:00:09–10:10:01 interval: run queue 69 on two CPUs, load 55.48, available memory
731160 KiB, swap free 212 KiB, page input about 1010 MiB/s, 356 major faults/s.
It records a Linux restart at 10:18:01. This identifies an observed resource
condition, not the responsible process or a proven SQL defect.

At the 10:29 UTC observation, server and worker had started at 10:18:02,
using releases d6be7f7 and 8822520.
The complete server search over 10:22–10:32 found no SQLITE_BUSY. Current memory
and successful reads improved after reboot; durable resolution is not established.
Do not repeat earlier GIL/index fixes or add retries based on this evidence.

## Root cause, fix and next verification

Sharing root cause remains unproved. Current API flags explicitly permit
reposting for the configured API user, while the owner reports failure in a
native client. These observations must remain separate; no carousel-format
change, new flag/gate, retry or recovery path is justified.

The missing distinguishing observation is the exact client surface and failed
action: absent Share control, unavailable wall/message/Story destination, or the
literal native error. The existing owner question already asks for this; the
coordinator instructed us not to repeat it. A read-only screenshot/opening of the
existing post and Share menu would locate the failure without sending a repost.
The saved browser profile is logged out, so that authenticated inspection is
currently unavailable. Generic photo downloads or another same-context API read
would not establish this outcome.

No production source correction or distinguishing regression has been authored,
because the component causing the product defect is not established. Net
production lines: 0 of the 100-line budget. No PR, merge, deployment or product
acceptance is claimed. The engineer retains diagnosis; the coordinator alone
merges/deploys, and dot performs the ordinary product E2E.

Retained evidence (managed directory, no credentials):
`/home/dev/artifacts/vibepublish/20261109T102844Z-carousel-quality-20261109`:
`vk-share-flags.json`, `vk-controls.json`, `vk-feed.json`, `vk-5131.json`,
`live-evidence.json`, `sar-20261109-1000-1020.txt`, `mcp-read-receipts.json`,
`vk-nested-sharing-20261109T1222.json`, `vk-sharing-community-20261109.json`.

## Documentation handoff, 2026-11-09

The coordinator requested this incident record and a CHANGELOG entry for normal
source review. The record preserves the corrected diagnosis and the remaining
native-client observation; it is not a product fix or an instruction to change
the format. Production source delta is zero. Documentation consistency and
whitespace checks do not close sharing, photo availability or runtime incidents.
