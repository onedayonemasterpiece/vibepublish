# Explicit VK edit-baseline refresh

If a tracked VK edit failed before dispatch with remote_revision_conflict or an
explicit media-upload HTTP502/503/504, a fresh
read does not silently replace the expected snapshot. The owner may explicitly
accept one fresh scoped item ref through the existing publication_update command:

- publication_id and expected_revision identify the original tracked publication.
- change.kind is reconcile; operation_id and attempt_id identify its latest failed edit.
- change.native_reference is the fresh item_ ref from a normal read of that same post.
- request_key is required and identifies this single baseline acceptance.

This narrow branch is owner-only, single-destination VK, published posts, exact
binding/epoch/native identity and a read no older than5 minutes. Wrong/private-other-
principal refs, revoked rights, stale publication revisions, dispatched/unknown
attempts and pending finalization are rejected.

The operation is local and complete: a new revision preserves the failed edit's
desired content/media and stores the explicitly selected baseline. The old request,
plan and checkpoint are immutable. It does not send, upload, edit, retry or delete
anything at VK. The receipt explicitly reports that a separate edit is required.

Submit that subsequent edit against the returned revision. Its usual exact native
CAS still runs immediately before staging/mutation; another external change blocks
again. The existing post ID and publication ID remain unchanged. Existing uncertain-
effect reconcile with native URLs is unchanged.

Regression: real VK adapter with scripted native transport, four replacement images,
same post identity, no effect during rebase, immutable original intent, idempotent
replay, second-change CAS, stale evidence and mismatched/armed attempts.
