"""Executable design, not an MCP server. Render: python contracts/social_mcp_v1.py.

The original eight-tool publication design plus the owner-only Telegram media
database are selected for implementation; weak-agent effectiveness
is not established by schema validation. No credentials or provider I/O here.
"""
from __future__ import annotations
import copy
import json

VERSION = "1.13.0-runtime"
DIALECT = "https://json-schema.org/draft/2020-12/schema"


def obj(properties, required=()):
    return {"type": "object", "properties": properties,
            "required": list(required), "additionalProperties": False}


def string(max_length=20000, **kwargs):
    return {"type": "string", "minLength": 1, "maxLength": max_length, **kwargs}


# VK stories link_text selectors (stories.getPhotoUploadServer / getVideoUploadServer); VK renders its own localized label.
VK_STORY_LINK_TEXTS = ("read", "more", "watch", "view", "open", "go_to", "learn_more", "ticket", "buy", "book", "order",
                       "enroll", "signup", "fill", "write", "contact", "vote", "play", "install", "to_store", "calendar")


def enum(*values):
    return {"type": "string", "enum": list(values)}


def array(items, minimum=0, maximum=50):
    return {"type": "array", "items": items, "minItems": minimum, "maxItems": maximum}


def ref(name):
    return {"$ref": f"#/$defs/{name}"}


def arm(kind, properties=None, required=()):
    return obj({"kind": {"const": kind}, **(properties or {})}, ("kind", *required))


ALIAS = string(80, pattern=r"^[a-z][a-z0-9_-]*$")
ID = string(128, pattern=r"^[a-z][a-z0-9_:-]*$")
REV = {"type": "integer", "minimum": 1}
DATE = string(40, format="date-time")
# Explicitly consume the whole URL: some MCP clients apply full-match pattern
# validation rather than JSON Schema's search semantics.
URL = string(4096, format="uri", pattern=r"^https://[^\s]+$")
TELEGRAM_THREAD_URL = string(4096, format="uri", pattern=r"^https://t\.me/c/[1-9][0-9]*/[1-9][0-9]*/?$")
KEY = string(128)
LIMIT = {"type": "integer", "minimum": 1, "maximum": 50}
PROVIDER = enum("telegram", "vk", "max")
NEXT = enum("none", "check_status", "approve", "select_visual", "fix_input",
            "refresh", "reauthorize", "review_outcome", "contact_owner")
STATE = enum("accepted", "running", "needs_approval", "needs_selection", "scheduled",
             "verified", "partial", "failed", "outcome_unknown", "cancelled", "blocked")
STAGE = enum("accepted", "validating", "importing_media", "rendering", "awaiting_approval",
             "awaiting_selection", "waiting_connection", "resolving_source", "checking_forward_rights", "uploading", "submitting",
             "reading_back", "verifying", "finished", "blocked", "outcome_unknown")

DEFS = {
    "media": obj({"source": {"oneOf": [
        arm("asset", {"id": ID}, ("id",)),
        arm("existing", {"position": {"type": "integer", "minimum": 0, "maximum": 9}}, ("position",)),
        arm("url", {"url": URL}, ("url",)),
        arm("upload", {"ticket": ID}, ("ticket",))]},
        "role": enum("auto", "image", "video", "audio", "document", "animation"),
        "caption": {**string(), "minLength": 0}, "alt_text": string(2000)}, ("source",)),
    "inline": {"oneOf": [
        arm("text", {"text": string(), "style": enum("normal", "bold", "italic", "code", "spoiler")}, ("text",)),
        arm("link", {"label": string(1000), "url": URL}, ("label", "url")),
        arm("mention", {"label": string(1000), "target_ref": ID}, ("label", "target_ref")),
        arm("emoji", {"alias": ALIAS}, ("alias",))]},
    "content": {"oneOf": [
        obj({"text": {**string(), "minLength": 0}, "format": enum("plain", "markdown")}, ("text",)),
        obj({"paragraphs": array(array(ref("inline"), 1, 200), 1, 100)}, ("paragraphs",))]},
    "renderings": obj({p: ref("content") for p in ("telegram", "vk", "max")}),
    "delivery": {"oneOf": [arm("now"), arm("at", {
        "at": DATE}, ("at",))]},
    "visual_spec": {"oneOf": [
        arm("generate", {"brief": string(5000), "preset": ALIAS,
            "candidates": {"type": "integer", "minimum": 1, "maximum": 4},
            "selection": enum("automatic", "human")}, ("brief",)),
        arm("tune", {"source": ref("media"), "brief": string(5000), "preset": ALIAS,
            "candidates": {"type": "integer", "minimum": 1, "maximum": 4},
            "selection": enum("automatic", "human")}, ("source", "brief")),
        arm("compose", {"sources": array(ref("media"), 2, 8), "brief": string(5000),
            "preset": ALIAS, "candidates": {"type": "integer", "minimum": 1, "maximum": 4},
            "selection": enum("automatic", "human")}, ("sources", "brief"))]},
    "destination": obj({"alias": ALIAS, "kind": enum("destination", "set"),
        "label": string(200), "revision": REV, "provider": PROVIDER, "native_id": string(128),
        "members": array(ALIAS, 0, 100)},
        ("alias", "kind", "label", "revision")),
    "capability": obj({"destination": ALIAS, "operation": string(80),
        "surface": string(80), "status": enum("supported", "unsupported", "needs_auth", "needs_review", "temporarily_unavailable"),
        "observed_at": DATE, "reason": string(500)},
        ("destination", "operation", "surface", "status", "observed_at")),
    "delivery_result": obj({"destination": ALIAS, "provider": PROVIDER, "attempt_id": ID,
        "state": STATE, "observed": enum("not_attempted", "provider_scheduled", "provider_processing", "published", "edited", "reacted", "deleted", "cancelled", "absent", "unknown"),
        "observed_at": DATE, "revision": REV, "requested_at": DATE, "effective_at": DATE,
        "applied_revision": {"type": ["integer", "null"], "minimum": 1}, "desired_revision": REV,
        "sync_status": enum("current", "outdated", "pending", "unknown"),
        "stage": STAGE, "scheduling_owner": {"const": "provider"}, "item_ref": ID, "url": URL,
        "queue_ref": ID, "preview_ref": ID, "navigate_hint": string(500),
        "evidence_ref": ID, "media_check": enum("not_applicable", "source_bytes", "provider_binding", "provider_identity_only", "download_binding", "visual_correspondence", "incomplete"),
        "missing_checks": array(string(100), 0, 20), "retry_safe": {"type": "boolean"},
        "compensation": enum("intent_cancelled_without_effect"), "reason": string(100),
        "reply_to_ref": ID, "reaction": string(100), "reaction_mode": enum("add", "remove")},
        ("destination", "provider", "state", "stage", "observed", "revision", "media_check", "retry_safe")),
    "candidate": obj({"id": ID, "asset_ref": ID, "sha256": string(64, pattern=r"^[a-f0-9]{64}$"),
        "preview_url": URL, "width": {"type": "integer", "minimum": 1},
        "height": {"type": "integer", "minimum": 1}, "format": enum("post_4_5", "story_9_16", "original"),
        "selection_token": string(512), "requires_review": {"type": "boolean"}}, ("id", "asset_ref", "sha256", "width", "height")),
    "error": obj({"code": string(80), "message": string(1000), "field": string(200)}, ("code", "message")),
}
# Editorial profiles are local per-principal metadata, never grants or provider edits.
DEFS["destination_profile"] = obj({
    "usage": enum("primary", "secondary"), "purpose": string(800),
    "audience": string(400), "topics": array(string(80), 0, 20),
    "avoid_topics": array(string(80), 0, 20), "notes": {**string(1600), "minLength": 0},
    "selection": enum("explicit_only", "agent_may_choose")})
DEFS["destination"]["properties"].update({"profile": ref("destination_profile"), "profile_revision": REV})
DEFS["forward_origin"] = obj({"source_ref": ID, "provider": enum("telegram", "vk", "max"),
    "original_url": URL, "mode": {"const": "native"},
    "origin_check": enum("matched", "pending", "incomplete")},
    ("source_ref", "provider", "mode", "origin_check"))
DEFS["delivery_result"]["properties"]["forward_origin"] = ref("forward_origin")
DEFS["media_store_origin"] = obj({
    "system": string(80, pattern=r"^[a-z][a-z0-9._-]*$"),
    "ref": string(1000, pattern=r"^[a-z][a-z0-9+.-]*://"),
    "sha256": string(64, pattern=r"^[a-f0-9]{64}$"),
}, ("system", "ref"))

# Exact typography is data, not text inferred from a generation prompt.
DEFS["visual_copy"] = obj({"title": string(160), "subtitle": string(240),
    "body": string(1200), "date_line": string(160), "location_line": string(240),
    "source_line": string(300)})
for visual_arm in DEFS["visual_spec"]["oneOf"]:
    visual_arm["properties"]["prompt"] = {**string(5000), "description": "Visual request; quotes stay literal. Legacy brief is an alias. Structured copy is optional, not inferred from this text."}
    visual_arm["required"].remove("brief")
    visual_arm["anyOf"] = [{"required": ["prompt"]}, {"required": ["brief"]}]
    if visual_arm["properties"]["kind"]["const"] == "generate":
        visual_arm["properties"]["sources"] = array(ref("media"), 0, 8)
    visual_arm["properties"]["copy"] = ref("visual_copy")
    visual_arm["properties"]["formats"] = {**array(enum("post_4_5", "story_9_16", "original"), 1, 2),
                                           "uniqueItems": True}
    if visual_arm["properties"]["kind"]["const"] == "tune":
        # Keep legacy single-source tune; batch sources are ordered cards.
        visual_arm["properties"]["sources"] = array(ref("media"), 2, 8)
        visual_arm["required"].remove("source")
        visual_arm["oneOf"] = [{"required": ["source"]}, {"required": ["sources"]}]
        visual_arm["properties"]["brief"] = string(32000)
        visual_arm["properties"]["prompt"] = string(32000)
        # Mixed aspect ratios and repeated formats are meaningful per-card.
        visual_arm["properties"]["formats"] = array(enum("post_4_5", "story_9_16", "original"), 1, 8)
# Events commit with the corresponding state change; they are not transient logs.
DEFS["event"] = obj({"seq": REV, "operation_id": ID, "destination": ALIAS,
    "at": DATE, "stage": STAGE, "status": enum("started", "completed", "failed", "blocked", "unknown"),
    "message": string(1000), "item_index": {"type": "integer", "minimum": 0},
    "item_count": {"type": "integer", "minimum": 1}, "evidence_ref": ID},
    ("seq", "operation_id", "at", "stage", "status", "message"))
DEFS["progress"] = obj({"events": array(ref("event"), 0, 50),
    "cursor": string(512), "has_more": {"type": "boolean"}}, ("events", "cursor", "has_more"))
DEFS["downloaded_media"] = obj({
    "kind": {"const": "download_sha256"}, "slot": {"type": "integer", "minimum": 0, "maximum": 9},
    "sha256": string(64, pattern=r"^[a-f0-9]{64}$"),
    "mime": enum("image/png", "image/jpeg", "image/webp", "video/mp4", "application/pdf", "image/vnd.djvu"),
    "size": {"type": "integer", "minimum": 1, "maximum": 128*1024*1024},
    "asset_ref": ID, "resource_uri": string(300, pattern=r"^vibepublish://assets/[a-z][a-z0-9_:-]*$"),
    "media_kind": enum("photo", "document")},
    ("kind", "slot", "sha256", "mime", "size"))
DEFS["read_media"] = {"oneOf": [obj({
    **DEFS["media"]["properties"],
    "width": {"type": "integer", "minimum": 1},
    "height": {"type": "integer", "minimum": 1}}, ("source",)), obj({
    "role": enum("auto", "image", "video", "audio", "document", "animation")}, ("role",))]}
DEFS["read_item"] = obj({"ref": ID, "kind": string(80), "text": string(), "url": URL,
    "publication_id": ID, "revision": REV, "destination": ALIAS, "own_reactions": array(string(100),0,100),
    "publication_kind": enum("original", "forward"), "forward_origin": ref("forward_origin"),
    "scheduled_at": DATE, "published_at": DATE, "observed_at": DATE,
    "source": enum("provider", "local_history"), "freshness": enum("current", "cached", "unknown"),
    "origin": enum("vibepublish", "provider_client", "imported"),
    "observed_state": enum("provider_scheduled", "provider_processing", "published", "deleted", "cancelled", "unknown"),
    "queue_ref": ID, "preview_ref": ID, "navigate_hint": string(500),
    "media": array(ref("read_media"), 0, 20), "media_evidence": array(ref("downloaded_media"), 0, 10),
    "metrics_observed_at": DATE, "error": ref("error"),
    "metrics": array(obj({"name": string(100), "value": {"type": "number"}, "unit": string(40)},
                         ("name", "value")), 0, 100)}, ("ref", "kind", "observed_at", "source", "freshness"))
DEFS["read_item"]["properties"]["native_schedule_origin"] = obj({
    "owner_id": string(64, pattern=r"^-[1-9][0-9]*$"),
    "postponed_id": string(64, pattern=r"^[1-9][0-9]*$"),
    "published_id": string(64, pattern=r"^[1-9][0-9]*$"),
    "evidence": enum("vk_postponed_id")},
    ("owner_id", "postponed_id", "published_id", "evidence"))
DEFS["recompose_lineage"] = obj({"job_id": ID, "candidate_id": ID, "visual_revision": REV,
    **{key: string(64, pattern=r"^[a-f0-9]{64}$") for key in
       ("candidate_sha256", "input_digest", "art_sha256")}},
    ("job_id", "candidate_id", "visual_revision", "candidate_sha256", "input_digest", "art_sha256"))
DEFS["receipt"] = obj({"operation_id": ID, "resource_id": ID, "revision": REV,
    "action": string(80), "state": STATE, "message": string(1500),
    "operation_complete": {"type": "boolean"}, "progress": ref("progress"),
    "items": array(ref("read_item"), 0, 50), "next_cursor": string(512), "worker_seen_at": DATE,
    "truncated": {"type": "boolean"},
    "visual_job_id": ID, "visual_revision": REV, "selected_asset_ref": ID,
    "local_recomposition": {"type": "boolean"}, "recompose_from": ref("recompose_lineage"),
    "selected_sha256": string(64, pattern=r"^[a-f0-9]{64}$"),
    "executor": obj({"requested_route": string(120), "actual_executor": {"type": ["string", "null"], "maxLength": 160},
                     "actual_model": {"type": ["string", "null"], "maxLength": 160}, "fixture": {"type": "boolean"}},
                    ("requested_route", "actual_executor", "actual_model", "fixture")),
    "next_action": NEXT, "retry_safe": {"type": "boolean"}, "receipt_ref": ID,
    "generation_dispatch": enum("not_sent"),
    "duration_ms": {"type": "integer", "minimum": 0},
    "observation_recovery": obj({"job_id": ID, "execution_ref": ID,
        "input_digest": string(64, pattern=r"^[a-f0-9]{64}$"),
        "operation_revision": REV, "visual_revision": REV,
        "generation_deadline": {"type": "number"}, "read_deadline": {"type": "number"}},
        ("job_id", "execution_ref", "input_digest", "operation_revision", "visual_revision", "generation_deadline", "read_deadline")),
    "deliveries": array(ref("delivery_result"), 0, 100),
    "candidates": array(ref("candidate"), 0, 4), "destinations": array(ref("destination"), 0, 100),
    "review_token": string(512), "poll_after_seconds": {"type": "integer", "minimum": 1},
    "error": ref("error"), "dry_run": {"type": "boolean"}},
    ("operation_id", "action", "state", "message", "operation_complete", "progress", "next_action", "retry_safe", "receipt_ref", "deliveries"))
DEFS["receipt"]["properties"]["linked_story"] = obj({
    "id": ID, "state": enum("waiting", "queued", "verified", "blocked", "cancelled", "expired", "outcome_unknown"),
    "reason": {"type": ["string", "null"], "maxLength": 200},
    "event_status": string(100), "child_operation_id": {"type": ["string", "null"], "maxLength": 200},
    "expires": {"type": "number"}}, ("id", "state", "reason", "event_status", "child_operation_id", "expires"))
DEFS["binding_grant_snapshot"] = obj({
    "rights": {**array(enum("publish", "edit", "reschedule", "cancel", "delete", "forward",
                           "reply", "react", "basic_group_schedule"), 0, 9), "uniqueItems": True},
    "binding_epoch": REV, "actor_epoch": REV, "routing_revision": REV},
    ("rights", "binding_epoch", "actor_epoch", "routing_revision"))
DEFS["receipt"]["properties"]["binding_grant"] = obj({
    "binding_id": ID, "alias": ALIAS, "right": {"const": "edit"},
    "before": ref("binding_grant_snapshot"), "after": ref("binding_grant_snapshot")},
    ("binding_id", "alias", "right", "before", "after"))
DEFS["receipt"]["properties"]["workspace_upload"] = obj({
    "upload_id": ID, "received_bytes": {"type": "integer", "minimum": 0, "maximum": 20971520},
    "size_bytes": {"type": "integer", "minimum": 1, "maximum": 20971520},
    "source_sha256": string(64, pattern=r"^[a-f0-9]{64}$"),
    "mime": enum("image/png", "image/jpeg", "image/webp", "video/mp4"),
    "expires_at": DATE, "state": enum("receiving", "completed", "aborted", "expired")},
    ("upload_id", "received_bytes", "size_bytes", "source_sha256", "mime", "expires_at", "state"))
DEFS["media_store_item"] = obj({
    "entry_ref": ID, "text": {**string(), "minLength": 0}, "observed_at": DATE,
    "native_id": string(128), "destination": ALIAS,
    "thread_ref": TELEGRAM_THREAD_URL, "telegram_url": TELEGRAM_THREAD_URL,
    "sha256": array(string(64, pattern=r"^[a-f0-9]{64}$"), 0, 20),
    "origin": ref("media_store_origin"),
}, ("entry_ref", "text", "observed_at", "native_id", "destination",
    "thread_ref", "telegram_url", "sha256"))
DEFS["receipt"]["properties"]["media_store_items"] = array(ref("media_store_item"), 0, 50)
DEFS["receipt"]["properties"]["media_store_retry_count"] = {"type": "integer", "minimum": 1}
DEFS["receipt"]["properties"]["media_store_retry_at"] = DATE
DEFS["receipt"]["properties"]["vk_completion_retry_at"] = DATE
DEFS["receipt"]["properties"]["vk_completion_retry_counts"] = {
    "type": "object",
    "minProperties": 1,
    "maxProperties": 100,
    "patternProperties": {
        r"^attempt_[a-f0-9]{32}$": {"type": "integer", "minimum": 1, "maximum": 3},
    },
    "additionalProperties": False,
}

TOOLS = []


def tool(name, description, inputs, outputs, scope, read_only=False):
    TOOLS.append({"name": "vibepublish_" + name, "description": description,
        "inputSchema": inputs, "outputSchema": outputs, "required_scope": scope,
        "annotations": {"readOnlyHint": read_only, "destructiveHint": name in DESTRUCTIVE,
                        "openWorldHint": name in OPEN_WORLD}})


# Hints describe real effects; ChatGPT asks for explicit approval on destructiveHint.
# Only lifecycle changes can delete or overwrite published posts.
DESTRUCTIVE = {"publication_update"}
# Tools that write to or read from social networks; private asset work is not open-world.
OPEN_WORLD = {"publish", "media_store", "publication_update", "read", "engage", "destinations"}


tool("get_started", "Get the versioned skill, allowed aliases and current capabilities. Never grants access.",
    obj({"section": enum("core", "examples", "visuals", "reading", "forwarding", "destinations", "all"), "if_version": string(80), "cursor": string(512)}),
    obj({"version": string(80), "schema_version": string(80), "skill_sha256": string(64, pattern=r"^[a-f0-9]{64}$"),
        "skill": string(30000), "estimated_tokens": {"type": "integer", "minimum": 0},
        "timezone": string(100), "server_time": DATE, "policy_epoch": REV, "routing_revision": REV,
        "scheduling": {"const": "provider_native_only"},
        "read_policy": enum("bound_publish_destinations", "provider_visible_owner", "none"),
        "destinations": array(ref("destination"), 0, 100), "capabilities": array(ref("capability"), 0, 500),
        "next_cursor": string(512)},
        ("version", "schema_version", "skill_sha256", "skill", "estimated_tokens", "server_time", "policy_epoch", "scheduling", "read_policy", "destinations", "capabilities")),
    "bootstrap", True)

tool("publish", "Create one publication now or in native provider queues; return accepted progress without waiting for providers. No local scheduler. Preview does not send. An explicit execute publication with a visual defaults to eligible automatic selection: omitted delivery means now; delivery at uses a native queue. Preview and explicit human selection remain gated.",
    obj({"to": array(ALIAS, 1, 20), "content": ref("content"), "media": array(ref("media"), 0, 20),
        "linked_story": obj({"media": array(ref("media"), 1, 1), "text": enum(*VK_STORY_LINK_TEXTS)}, ("media", "text")),
        "story_link": {"oneOf": [
            obj({"item_ref": {"oneOf": [ID, URL]}, "text": enum(*VK_STORY_LINK_TEXTS)}, ("item_ref", "text")),
            obj({"url": URL, "text": string(120)}, ("url",)),
        ]},
        "thread_ref": {"oneOf": [ID, TELEGRAM_THREAD_URL]},
        "surface": enum("post", "story", "message", "album", "video", "short_video"),
        "delivery": ref("delivery"), "mode": enum("execute", "preview"),
        "renderings": ref("renderings"), "visual": ref("visual_spec"),
        "vk": obj({"primary_attachments_mode": {"const": "carousel"}}),
        "request_key": KEY, "repeat_of": ID, "routing_revision": REV}, ("to",)), ref("receipt"), "publish")

TOOLS[-1]["inputSchema"]["anyOf"] = [
    {"required": ["content"]}, {"required": ["visual"]},
    {"required": ["media"], "properties": {"media": {"minItems": 1}}}]

tool("media_store", "Private Telegram DOCUMENT archive. Put verified assets, or import one PDF/DjVu from an allowlisted public source URL through the authenticated owner interface, without exposing service credentials. List/search/get retain existing scoped semantics.",
    obj({"command": {"oneOf": [
        arm("put", {"to": ALIAS, "thread_ref": TELEGRAM_THREAD_URL,
            "content": ref("content"), "media": array(ref("media"), 1, 20),
            "origin": ref("media_store_origin")},
            ("to", "thread_ref", "content", "media")),
        arm("put_url", {"to": ALIAS, "thread_ref": TELEGRAM_THREAD_URL,
            "url": URL, "mime": enum("application/pdf", "image/vnd.djvu"),
            "filename": string(160),
            "expected_sha256": string(64, pattern=r"^[0-9a-f]{64}$")},
            ("to", "thread_ref", "url", "mime", "filename")),
        arm("list", {"to": ALIAS, "thread_ref": TELEGRAM_THREAD_URL,
            "text": {**string(1000), "minLength": 0}}, ("thread_ref",)),
        arm("search", {"text": string(1000)}, ("text",)),
        arm("get", {"entry_ref": ID}, ("entry_ref",))]},
        "request_key": KEY, "limit": LIMIT}, ("command",)), ref("receipt"), "media.store")
TOOLS[-1]["inputSchema"]["allOf"] = [{
    "if": {"properties": {"command": {"properties": {"kind": {"enum": ["put", "put_url"]}}, "required": ["kind"]}}},
    "then": {"required": ["request_key"]}
}]

change = {"oneOf": [
    arm("approve", {"token": string(512)}, ("token",)),
    arm("edit", {"content": ref("content"), "media": array(ref("media"), 0, 20), "renderings": ref("renderings"),
        "destinations": {**array(ALIAS, 1, 20), "uniqueItems": True}}),
    arm("reschedule", {"delivery": DEFS["delivery"]["oneOf"][1]}, ("delivery",)),
    arm("cancel"), arm("delete"),
    arm("reconcile_removed", {"attempt_id": ID}, ("attempt_id",)),
    arm("reconcile", {"operation_id": ID, "attempt_id": ID, "native_reference": string(2048)}, ("operation_id",)),
    arm("retry_failed", {"destinations": array(ALIAS, 1, 20)}, ("destinations",)),
    arm("supersede_failed", {"destinations": {**array(ALIAS, 1, 20), "uniqueItems": True},
        "content": ref("content")}, ("destinations", "content"))]}
change["oneOf"][1]["anyOf"] = [{"required": [p]} for p in ("content", "media", "renderings")]
tool("publication_update", "Change an existing publication at an exact revision. Cancel unsent work; delete published work; retry only proven safe failures. Owner-only reconcile_removed reads a checkpoint-bound uncertain VK scheduled object without any write; verified absence resolves only its quarantine, never retries publication. Reconcile observes the original uncertain operation without repeating its effect. For a never-dispatched tracked VK edit conflict, an owner may pass a fresh same-post item ref as native_reference to accept a new local baseline revision; this performs no provider write and requires a separate edit. A fresh exact Telegram item_ref may replace one image/video only on a provably managed same-principal published message; it creates a new revision of that same publication, edits the existing message, and retains unselected sibling receipts. VK edits can order new assets and existing attachment positions from the same freshly read post, including postponed posts; Telegram retains its single managed replacement rule. An edit may select existing publication destinations by alias with a request key; only verified selected targets execute. Unselected target evidence remains visible with desired/applied revision and synchronization status.",
    obj({"publication_id": ID, "expected_revision": REV, "item_ref": ID, "change": change, "request_key": KEY},
        ("change",)), ref("receipt"), "publication.manage")
# Existing private publication CAS or one exact immutable observed native item.
# An item ref is already a scoped snapshot CAS, not a mutable provider revision.
TOOLS[-1]["inputSchema"]["oneOf"] = [
    {"required": ["publication_id", "expected_revision"], "not": {"required": ["item_ref"]}},
    {"required": ["item_ref"], "not": {"anyOf": [{"required": ["publication_id"]}, {"required": ["expected_revision"]}]}}]

TOOLS[-1]["inputSchema"]["allOf"] = [{
    "if": {"properties": {"change": {"properties": {"kind": {"const": "supersede_failed"}},
                                       "required": ["kind"]}}},
    "then": {"required": ["publication_id", "expected_revision", "request_key"],
             "not": {"required": ["item_ref"]}}
}, {
    "if": {"required": ["item_ref"], "properties": {
        "change": {"required": ["kind", "media"], "properties": {"kind": {"const": "edit"}}}}},
    "then": {"required": ["request_key"]}
}, {
    "if": {"properties": {"change": {"required": ["kind", "destinations"],
        "properties": {"kind": {"const": "edit"}}}}},
    "then": {"required": ["publication_id", "expected_revision", "request_key"],
             "not": {"required": ["item_ref"]}}
}]

browser_artifact_uri = string(47, pattern=r"^artifact://[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
workspace_import_commands = [
    arm("import_begin", {"source_sha256": string(64, pattern=r"^[a-f0-9]{64}$"),
        "mime": enum("image/png", "image/jpeg", "image/webp", "video/mp4"),
        "size_bytes": {"type": "integer", "minimum": 1, "maximum": 20971520}},
        ("source_sha256", "mime", "size_bytes")),
    arm("import_chunk", {"upload_id": ID, "offset": {"type": "integer", "minimum": 0, "maximum": 20971520},
        "data_base64": string(262144, pattern=r"^[A-Za-z0-9+/]*={0,2}$")},
        ("upload_id", "offset", "data_base64")),
    arm("import_finish", {"upload_id": ID}, ("upload_id",)),
    arm("import_status", {"upload_id": ID}, ("upload_id",)),
    arm("import_abort", {"upload_id": ID}, ("upload_id",)),
]

# Private carousel authoring. Generation remains with the calling model (dot).
_carousel_region = array({"type": "integer", "minimum": 0, "maximum": 25600}, 4, 4)
_reference_id = string(80, pattern=r"^[A-Za-z0-9_-]+$")
_reference_use = obj({"reference_id": _reference_id, "observation": string(2000),
    "change": string(2000)}, ("reference_id", "observation", "change"))
_carousel_scene = {"brief": string(12000), "svg": string(262144),
    "card_count": {"type": "integer", "minimum": 3, "maximum": 10},
    "card_width": {"type": "integer", "minimum": 128, "maximum": 2560},
    "card_height": {"type": "integer", "minimum": 128, "maximum": 2560},
    "caption": {**string(), "minLength": 0}}
_carousel_card = obj({"index": {"type": "integer", "minimum": 1, "maximum": 10},
    "asset_ref": ID, "resource_uri": string(300), "sha256": string(64),
    "width": {"type": "integer"}, "height": {"type": "integer"},
    "mime_type": enum("image/png", "image/jpeg")},
    ("index", "asset_ref", "resource_uri", "sha256", "width", "height", "mime_type"))
_carousel_receipt_fields = {"carousel_id": ID, "private": {"const": True},
    "scene_ready": {"type": "boolean"}, "cards": array(_carousel_card, 3, 10),
    "media": array(ref("media"), 3, 10), "caption": {**string(), "minLength": 0}}
DEFS["receipt"]["properties"].update(_carousel_receipt_fields)
_reference = obj({"id": _reference_id, "title": string(1000),
    "tags": array(string(200), 0, 50), "look_for": string(5000), "transfer": string(5000),
    "source": obj({"slack_url": URL, "file_id": string(200)}, ("slack_url", "file_id")),
    "use_note": string(5000), "duplicate_of": _reference_id, "available": {"type": "boolean"},
    "matched": {"type": "boolean"}},
    ("id", "title", "tags", "look_for", "transfer", "source", "use_note", "available"))
CAROUSEL_REFERENCE = _reference  # Shared catalog validation at import and read boundaries.
_icon_id = string(128, pattern=r"^(?:[1-9][0-9]{0,9}|[a-z0-9-]{1,40}:[a-z0-9-]{1,80})$")
_icon = obj({"id": _icon_id, "name": string(120), "source": URL,
    "license": string(100), "style": {**string(60), "minLength": 0}},
    ("id", "name", "source", "license", "style"))
_carousel_output = obj({
    **DEFS["receipt"]["properties"], **_carousel_scene,
    "svg": {**string(262144), "minLength": 0},
    "latest_revision": REV, "asset_refs": array(ID, 0, 100),
    "journal": array(obj({"operation_id": ID, "revision": REV,
        "kind": enum("create", "revise", "export", "render", "get", "asset_import"), "at": DATE,
        "duration_ms": {"type": "integer", "minimum": 0},
        "scope": enum("reference", "library", "guide", "icons"),
        "view": enum("master", "region", "card"), "region": _carousel_region,
        "card": {"type": "integer", "minimum": 1, "maximum": 10},
        "reference_id": _reference_id, "asset_ref": ID, "imported_at": DATE,
        "note": string(2000), "reference_use": _reference_use},
        ("operation_id", "revision", "kind", "at")), 0, 50),
    "next_step": enum("compose_svg", "render_then_review"),
    "references": array(_reference, 0, 20), "total": {"type": "integer", "minimum": 0},
    "offset": {"type": "integer", "minimum": 0}, "next_offset": {"type": ["integer", "null"]},
    "reference": _reference, "resource_uri": string(300),
    "icons": array(_icon, 0, 8), "icon": _icon,
    "view": enum("master", "region", "full", "crop"),
    "region": {"anyOf": [_carousel_region, {"type": "null"}]},
    "mime_type": enum("image/png", "image/jpeg", "image/webp"),
    "width": {"type": "integer", "minimum": 1}, "height": {"type": "integer", "minimum": 1},
    "source_width": {"type": "integer", "minimum": 1}, "source_height": {"type": "integer", "minimum": 1},
    "source_sha256": string(64), "preview_sha256": string(64),
    "size": enum("full"), "reencoded": {"type": "boolean"},
    "bytes": {"type": "integer", "minimum": 1}, "size_bytes": {"type": "integer", "minimum": 1},
    "preview_data_url": string(2796240), "full_data_url": string(2796240),
}, ("private",))
_carousel_commands = [
    arm("create", _carousel_scene, ("brief",)),
    arm("get", {"scope": {"const": "story"}, "carousel_id": ID, "revision": REV,
        "include_svg": {"type": "boolean"}}, ("carousel_id",)),
    arm("get", {"scope": {"const": "journal"}, "carousel_id": ID, "revision": REV,
        "limit": {"type": "integer", "minimum": 1, "maximum": 50}}, ("scope", "carousel_id")),
    arm("get", {"scope": {"const": "library"}, "carousel_id": ID,
        "query": {**string(500), "minLength": 0},
        "limit": {"type": "integer", "minimum": 1, "maximum": 20},
        "offset": {"type": "integer", "minimum": 0}}, ("scope",)),
    arm("get", {"scope": {"const": "reference"}, "carousel_id": ID,
        "reference_id": _reference_id, "region": _carousel_region}, ("scope", "reference_id")),
    arm("get", {"scope": {"const": "icons"}, "carousel_id": ID, "query": string(100),
        "style": {**string(60), "minLength": 0}}, ("scope", "query")),
    arm("get", {"scope": {"const": "icon"}, "carousel_id": ID, "id": _icon_id}, ("scope", "id")),
    arm("revise", {**_carousel_scene, "carousel_id": ID, "expected_revision": REV,
        "note": string(2000), "reference_use": _reference_use}, ("carousel_id", "expected_revision")),
    arm("render", {"carousel_id": ID, "revision": REV, "view": enum("master", "region"),
        "region": _carousel_region, "card": {"type": "integer", "minimum": 1, "maximum": 10}},
        ("carousel_id", "revision")),
    arm("export", {"carousel_id": ID, "revision": REV}, ("carousel_id", "revision")),
]
tool("carousel", "Create, get, revise, render and export private SVG story carousels. "
    "These commands never publish, edit a social post, send a message or dispatch image generation. "
    "Dot generates components with its own tool and imports them through visual import. "
    "Pass carousel_id when reading references to record the tool use in the private journal. "
    "get(scope:library) ranks owner-bound references by Russian/English token overlap and marks unmatched fallback entries; get(scope:reference,reference_id) "
    "returns one actual image or original-resolution pixel crop. Look at a useful reference, "
    "record the visible technique and concrete change in revise.reference_use, then render the changed region. "
    "get(scope:icons,query,style?) searches the local cache, SVG Repo over HTTP, then Iconify on unavailable results (including SVG Repo 429); maps line/filled/illustrative to icon sets and returns one PNG sheet of up to eight options (150/28 px) labeled with source and icon-set license. Inspect the actual pixels, then get(scope:icon,id) for cleaned inline SVG or a visual hint for dot's own image generator. Inspect the composed card too. "
    "SVG images use asset:RETURNED_ASSET_ID; safe style/class/use/filter/pattern/mask/paint-order; no external URLs, scripts, foreignObject or author data: URIs. "
    "Bundled Cyrillic SIL OFL fonts: Oswald (narrow), Unbounded (display), Montserrat (grotesk), PT Serif (serif), their package weights and italic; kerning by resvg. Primary dot asset input: vibepublish_visual import with host-supplied file:{download_url,file_id}; begin/chunk/finish only fallback. Use explicit text/tspan lines. "
    "Render master shows composition; render region or card shows readable detail. Export returns "
    "ordered private assets for the exact revision; export is not owner selection or permission to publish.",
    obj({"command": {"oneOf": _carousel_commands}, "request_key": KEY}, ("command",)),
    _carousel_output, "visual")
TOOLS[-1]["annotations"]["title"] = "Private story carousels — no publication or generation"
TOOLS[-1]["inputSchema"]["allOf"] = [{
    "if": {"properties": {"command": {"properties": {"kind": {"enum": ["create", "revise", "export"]}},
        "required": ["kind"]}}}, "then": {"required": ["request_key"]}}]
workspace_import_kinds = [v["properties"]["kind"]["const"] for v in workspace_import_commands]
visual_cmd = {"oneOf": [arm("import"), *workspace_import_commands,
    arm("import_browser_artifact", {"uri": browser_artifact_uri}, ("uri",)),
    ref("visual_spec"),
    arm("frame_source", {"source": ref("media"), "copy": ref("visual_copy"),
        "format": enum("post_4_5", "story_9_16", "original"),
        "layout": obj({"text_box": array({"type": "number", "minimum": 0, "maximum": 1}, 4, 4),
            "title_size": {"type": "number", "minimum": 28, "maximum": 68},
            "body_size": {"type": "number", "minimum": 22, "maximum": 42},
            "text_color": string(7, pattern=r"^#[a-fA-F0-9]{6}$"),
            "backplate_opacity": {"type": "number", "minimum": 0, "maximum": 0.65}}, ("text_box",))},
        ("source", "copy", "layout")),
    arm("recompose", {"job_id": ID, "candidate_id": ID,
        "expected_visual_revision": REV, "expected_sha256": string(64, pattern=r"^[a-f0-9]{64}$"),
        "format": enum("post_4_5", "story_9_16", "original")},
        ("job_id", "candidate_id", "expected_visual_revision", "expected_sha256")),
    arm("reconcile_dispatch", {"operation_id": ID, "job_id": ID,
        "expected_revision": REV, "expected_visual_revision": REV},
        ("operation_id", "job_id", "expected_revision", "expected_visual_revision")),
    arm("reconcile_observation", {"operation_id": ID, "job_id": ID,
        "expected_revision": REV, "expected_visual_revision": REV},
        ("operation_id", "job_id", "expected_revision", "expected_visual_revision")),
    arm("select", {"job_id": ID, "candidate_id": ID, "expected_revision": REV, "token": string(512)},
        ("job_id", "candidate_id", "expected_revision", "token")),
    arm("feedback", {"job_id": ID, "candidate_id": ID, "rating": enum("accepted", "rejected"), "reason": string(2000)},
        ("job_id", "candidate_id", "rating"))]}
tool("visual", "Import a chat attachment, bounded workspace bytes (import_begin/chunk/finish/status/abort), or trusted same-host browser artifact as a private asset without AI, or generate, tune or compose from prompt (legacy brief accepted), select a candidate, or record feedback. Explicit recompose creates a separate standalone candidate from verified stored art without AI, fenced by source visual revision and candidate SHA256; it never changes an existing choice or publishes. Generate allows optional source references. Selection resumes only its exact authorized parent. Explicit reconcile_dispatch seals an original terminal unknown only with trusted executor proof of no generation dispatch; it never resubmits or publishes. Explicit reconcile_observation queues one bounded read of the SAME saved dispatched execution to import completed artifacts; it never submits, starts another turn, renews generation deadlines, or automatically selects/publishes.",
    obj({"command": visual_cmd, "request_key": KEY,
         "file": obj({"download_url": string(8192), "file_id": string(512),
                      "mime_type": enum("image/png", "image/jpeg", "image/webp"),
                      "file_name": string(512)}, ("download_url", "file_id"))},
        ("command",)), ref("receipt"), "visual")
TOOLS[-1]["_meta"] = {"openai/fileParams": ["file"]}
TOOLS[-1]["annotations"]["title"] = "Private image import; selection may resume an authorized publication"
TOOLS[-1]["inputSchema"]["allOf"] = [{
    "if": {"properties": {"command": {"properties": {"kind": {"const": "import"}}, "required": ["kind"]}}},
    "then": {"required": ["file", "request_key"]},
    "else": {"not": {"required": ["file"]}}},
    {"if": {"properties": {"command": {"properties": {"kind": {"enum": ["import_browser_artifact", *workspace_import_kinds]}},
                                        "required": ["kind"]}}},
     "then": {"required": ["request_key"]}},
    {"if": {"properties": {"command": {"properties": {"kind": {"enum": ["recompose", "frame_source"]}},
                                        "required": ["kind"]}}},
       "then": {"required": ["request_key"]}}
]

_asset_preview_uri = string(300, pattern=r"^vibepublish://assets/[a-z][a-z0-9_:-]*$")
_asset_preview_fields = {
    "resource_uri": _asset_preview_uri,
    "source_sha256": string(64, pattern=r"^[a-f0-9]{64}$"),
    "preview_sha256": string(64, pattern=r"^[a-f0-9]{64}$"),
    "mime_type": {"const": "image/webp"},
    "width": {"type": "integer", "minimum": 1, "maximum": 768},
    "height": {"type": "integer", "minimum": 1, "maximum": 768},
    "source_width": {"type": "integer", "minimum": 1},
    "source_height": {"type": "integer", "minimum": 1},
    "size_bytes": {"type": "integer", "minimum": 1, "maximum": 393216},
    "preview_data_url": string(524320, pattern=r"^data:image/webp;base64,[A-Za-z0-9+/=]+$"),
}
_asset_full_fields = {
    "resource_uri": _asset_preview_uri,
    "source_sha256": string(64, pattern=r"^[a-f0-9]{64}$"),
    "mime_type": enum("image/png", "image/jpeg", "image/webp"),
    "width": {"type": "integer", "minimum": 1, "maximum": 2560},
    "height": {"type": "integer", "minimum": 1, "maximum": 2560},
    "bytes": {"type": "integer", "minimum": 1, "maximum": 2 * 1024 * 1024},
    "full_data_url": string(2796240, pattern=r"^data:image/(?:png|jpeg|webp);base64,[A-Za-z0-9+/=]+$"),
    "size": {"const": "full"},
    "reencoded": {"type": "boolean"},
}
tool("asset_preview", "Preview (default) is for inspection and selection; request size='full' for generation, colourization or image editing. Authorized full ImageContent contains original bytes if <=2 MiB and <=2560 px, otherwise a bounded reencoded JPEG. Both modes include a structured data URL for clients without ImageContent.",
    obj({"resource_uri": _asset_preview_uri, "size": enum("preview", "full")},
        ("resource_uri",)),
    {"type": "object", "properties": {key: {} for key in (*_asset_preview_fields, *_asset_full_fields)},
     "additionalProperties": False, "oneOf": [
         obj(_asset_preview_fields, ("resource_uri", "source_sha256", "preview_sha256", "mime_type", "width", "height", "source_width", "source_height", "size_bytes")),
         obj(_asset_full_fields, ("resource_uri", "source_sha256", "mime_type", "width", "height", "bytes", "size", "reencoded")),
     ]},
    "visual", True)

DEFS["status_network"] = obj({"destination": ALIAS, "provider": PROVIDER,
    "status": enum("готово", "выполняется", "отказ"), "url": URL,
    "queue_ref": ID, "item_ref": ID, "reason": string(200), "next_attempt_at": DATE,
    "next_attempt_time": string(5, pattern=r"^[0-2][0-9]:[0-5][0-9]$")},
    ("destination", "provider", "status"))
DEFS["status_summary"] = obj({"result": string(120),
    "networks": array(ref("status_network"), 0, 100)}, ("result", "networks"))
DEFS["status_snapshot"] = obj({"operation_id": ID, "revision": REV,
    "action": string(80), "state": STATE, "operation_complete": {"type": "boolean"},
    "resource_id": ID, "deliveries": array(ref("delivery_result"), 0, 100),
    "summary": ref("status_summary"), "error": ref("error"),
    "review_token": string(512),
    "linked_story": DEFS["receipt"]["properties"]["linked_story"]},
    ("operation_id", "action", "state", "operation_complete", "deliveries", "summary"))

tool("status", "Read an immediate, read-only per-network summary without a cursor; optional wait_final waits for every destination within the MCP budget. after_event retains detailed resumable journal reads.",
    obj({"ids": array(ID, 1, 20), "limit": LIMIT, "cursor": string(512),
        "after_event": string(512), "wait_seconds": {"type": "integer", "minimum": 0, "maximum": 40},
        "wait_final": {"type": "boolean"}}),
    obj({"receipts": array({"oneOf": [ref("receipt"), ref("status_snapshot")]}, 0, 50),
         "next_cursor": string(512)}, ("receipts",)), "status", True)

# Event cursors remain supported for detailed diagnostics, not normal publishing.
TOOLS[-1]["inputSchema"]["allOf"] = [{
    "if": {"anyOf": [{"required": ["after_event"]}, {"required": ["wait_seconds"]},
                      {"required": ["wait_final"]}]},
    "then": {"required": ["ids"], "properties": {"ids": {"maxItems": 1}},
             "not": {"required": ["cursor"]}}},
    {"if": {"properties": {"wait_final": {"const": True}}, "required": ["wait_final"]},
     "then": {"not": {"required": ["after_event"]}}}]

queries = [arm("item", {"item_ref": {"oneOf": [ID, URL]}}, ("item_ref",)),
    arm("dialogs", {"provider": PROVIDER}, ("provider",))]
for k in ("feed", "stories", "scheduled", "notifications", "audience", "editorial_sample"):
    queries.append(arm(k, {"destination": ALIAS}, ("destination",)))
queries.append(arm("thread", {"item_ref": {"oneOf": [ID, TELEGRAM_THREAD_URL]}}, ("item_ref",)))
queries.append(arm("reactions", {"item_ref": ID}, ("item_ref",)))
queries += [arm("search", {"destination": ALIAS, "text": string(1000)}, ("destination", "text")),
    arm("history", {"destination": ALIAS, "author": enum("mine", "channel"),
        "text": string(1000), "from": DATE, "to": DATE,
        "state": enum("provider_scheduled", "published", "cancelled", "deleted", "unknown"),
        "publication_kind": enum("original", "forward")}),
    arm("analytics", {"destination": ALIAS, "from": DATE, "to": DATE,
        "publication_ids": array(ID, 1, 20), "freshness": enum("cached", "refresh")})]
queries[-1]["oneOf"] = [
    {"required": ["destination", "from", "to"], "not": {"required": ["publication_ids"]}},
    {"required": ["publication_ids"], "not": {"anyOf": [{"required": [k]} for k in ("destination", "from", "to")]}}]
tool("read", "Read bound publishing channels in full, including native queues, or search local history/statistics. Only owners can read arbitrary provider-visible resources. Returns incremental receipts.",
    obj({"query": {"oneOf": queries}, "limit": LIMIT, "cursor": string(512)}, ("query",)),
    ref("receipt"), "social.read", True)

tool("engage", "Natively forward/repost an exact item or Telegram/VK post URL; preserve origin, never rewrite/copy. Reply/reaction are separate commands. Native scheduling only; return progress.",
    obj({"command": {"oneOf": [
        arm("reply", {"item_ref": ID, "content": ref("content")}, ("item_ref", "content")),
        arm("react", {"item_ref": ID, "reaction": string(100), "mode": enum("add", "remove")}, ("item_ref", "reaction", "mode")),
        arm("forward", {"item_ref": {"oneOf": [ID, URL]}, "to": array(ALIAS, 1, 20),
            "selection": enum("post", "message"), "delivery": ref("delivery"),
            "mode": enum("execute", "preview")}, ("item_ref", "to"))]},
        "request_key": KEY, "repeat_of": ID, "routing_revision": REV}, ("command",)), ref("receipt"), "engage")

tool("destinations", "List allowed aliases, update personal profiles, or manage granted destination sets. Owner-only binding_grant_edit adds only edit to one own binding using exact epoch/routing CAS and a request key; it never changes scopes. Profiles and URLs never grant access.",
    obj({"command": {"oneOf": [arm("list"),
        arm("profile_update", {"alias": ALIAS, "expected_revision": {"type": "integer", "minimum": 0},
            "profile": {**DEFS["destination_profile"], "minProperties": 1}}, ("alias", "expected_revision", "profile")),
        arm("binding_grant_edit", {"alias": ALIAS, "expected_binding_epoch": REV,
            "expected_routing_revision": REV}, ("alias", "expected_binding_epoch", "expected_routing_revision")),
        arm("resolve", {"provider": PROVIDER, "url": URL}, ("provider", "url")),
        arm("search", {"provider": PROVIDER, "text": string(500)}, ("provider", "text")),
        arm("set_put", {"alias": ALIAS, "label": string(200), "expected_revision": {"type": "integer", "minimum": 0},
            "members": array(ALIAS, 1, 100)}, ("alias", "label", "expected_revision", "members")),
        arm("set_delete", {"alias": ALIAS, "expected_revision": REV}, ("alias", "expected_revision")),
        arm("rename_label", {"alias": ALIAS, "label": string(200), "expected_revision": REV},
            ("alias", "label", "expected_revision"))]}, "request_key": KEY}, ("command",)),
    ref("receipt"), "destinations")

TOOLS[-1]["inputSchema"]["allOf"] = [{
    "if": {"properties": {"command": {"properties": {"kind": {"const": "binding_grant_edit"}},
                                        "required": ["kind"]}}},
    "then": {"required": ["request_key"]}
}]

# Exact discovery accepts one explicit URL or one provider-native ID. It never
# turns discovery into account-wide enumeration.
_destination_resolve = next(
    branch for branch in TOOLS[-1]["inputSchema"]["properties"]["command"]["oneOf"]
    if branch["properties"]["kind"].get("const") == "resolve"
)
_destination_resolve["required"] = ["kind", "provider"]
_destination_resolve["properties"]["provider_id"] = string(20, pattern=r"^-?[1-9][0-9]{0,18}$")
_destination_resolve["oneOf"] = [
    {"required": ["url"], "not": {"required": ["provider_id"]}},
    # MAX channel discovery requires an exact URL; raw IDs cannot prove its route.
    {"properties": {"provider": enum("telegram", "vk")},
     "required": ["provider_id"], "not": {"required": ["url"]}},
]
# Telegram palette extensions keep the publication methods and closed grammar.
DEFS["emoji_part"] = obj({"document_id": string(19, pattern=r"^[1-9][0-9]{0,18}$"),
    "alt": string(128), "preview_sha256": string(64, pattern=r"^[a-f0-9]{64}$")},
    ("document_id", "alt", "preview_sha256"))
DEFS["emoji_alias"] = obj({"alias": ALIAS, "revision": REV, "catalog_ref": ID,
    "catalog_revision": REV, "parts": array(ref("emoji_part"), 1, 16),
    "cells": array({"type": "integer", "minimum": 1, "maximum": 200}, 1, 16),
    "fallback": string(300)}, ("alias", "revision", "catalog_ref", "catalog_revision", "parts", "cells", "fallback"))
DEFS["emoji_context"] = obj({"venue": string(128), "category": string(128)})
DEFS["emoji_rule"] = obj({"name": ALIAS, "revision": REV, "match": string(100),
    "alias": ALIAS, "enabled": {"type": "boolean"}, "context": ref("emoji_context")},
    ("name", "revision", "match", "alias", "enabled", "context"))
DEFS["emoji_entry"] = obj({**DEFS["emoji_part"]["properties"], "cell": REV,
    "preview_ref": ID, "preview_kind": {"const": "static_thumbnail"}, "free": {"type": "boolean"}},
    ("document_id", "alt", "preview_sha256", "cell", "preview_ref", "preview_kind", "free"))
DEFS["emoji_sheet"] = obj({"first_cell": REV, "preview_ref": ID,
    "preview_sha256": string(64, pattern=r"^[a-f0-9]{64}$")}, ("first_cell", "preview_ref", "preview_sha256"))
DEFS["emoji_catalog"] = obj({"catalog_ref": ID, "revision": REV, "short_name": string(64),
    "observed_at": DATE, "preview_kind": {"const": "static_thumbnail"},
    "entries": array(ref("emoji_entry"), 0, 50), "sheets": array(ref("emoji_sheet"), 1, 2),
    "selection_token": string(512), "total": {"type": "integer", "minimum": 1, "maximum": 200}},
    ("catalog_ref", "revision", "short_name", "observed_at", "preview_kind", "entries", "sheets", "selection_token", "total"))
_entity_base = {"offset": {"type": "integer", "minimum": 0}, "length": REV}
DEFS["semantic_entity"] = {"oneOf": [
    obj({"type": enum("bold", "italic", "code", "spoiler", "underline", "strikethrough", "url", "mention"), **_entity_base}, ("type", "offset", "length")),
    obj({"type": {"const": "custom_emoji"}, **_entity_base, "document_id": string(19, pattern=r"^[1-9][0-9]{0,18}$")}, ("type", "offset", "length", "document_id")),
    obj({"type": {"const": "text_link"}, **_entity_base, "url": string(4096)}, ("type", "offset", "length", "url")),
    obj({"type": {"const": "pre"}, **_entity_base, "language": {**string(100), "minLength": 0}}, ("type", "offset", "length", "language"))]}
DEFS["receipt"]["properties"].update({"emoji_catalog": ref("emoji_catalog"),
    "emoji_alias": ref("emoji_alias"), "emoji_aliases": array(ref("emoji_alias"), 0, 100),
    "emoji_rule": ref("emoji_rule"), "emoji_rules": array(ref("emoji_rule"), 0, 100), "content_previews": array(obj({"destination": ALIAS,
        "provider": PROVIDER, "text": {**string(), "minLength": 0},
        "entities": array(ref("semantic_entity"), 0, 1000)}, ("destination", "provider", "text", "entities")), 0, 100)})
DEFS["read_item"]["properties"]["entities"] = array(ref("semantic_entity"), 0, 1000)
for _tool in TOOLS:
    _name = _tool["name"]
    _props = _tool["inputSchema"]["properties"]
    if _name == "vibepublish_get_started":
        _props["section"]["enum"].append("emoji")
    elif _name == "vibepublish_publish":
        _props.update(emoji_fallback=enum("approved_text"), emoji_context=ref("emoji_context"))
    elif _name == "vibepublish_publication_update":
        for _arm in _props["change"]["oneOf"]:
            if _arm["properties"]["kind"]["const"] == "edit":
                _arm["properties"].update(emoji_fallback=enum("approved_text"), emoji_context=ref("emoji_context"))
    elif _name == "vibepublish_read":
        _props["query"]["oneOf"].extend([arm("emoji_catalog", {"catalog_ref": ID}, ("catalog_ref",)), arm("emoji_palette")])
    elif _name == "vibepublish_destinations":
        _props["command"]["oneOf"].extend([
            arm("emoji_set_register", {"destination": ALIAS, "url": URL,
                "expected_revision": {"type": "integer", "minimum": 0}}, ("destination", "url", "expected_revision")),
            arm("emoji_alias_select", {"catalog_ref": ID, "catalog_revision": REV,
                "selection_token": string(512), "cells": array({"type": "integer", "minimum": 1, "maximum": 200}, 1, 16),
                "alias": ALIAS, "expected_revision": {"type": "integer", "minimum": 0}, "fallback": string(300)},
                ("catalog_ref", "catalog_revision", "selection_token", "cells", "alias", "expected_revision", "fallback")),
            arm("emoji_rule_put", {"name": ALIAS, "match": string(100), "alias": ALIAS,
                "enabled": {"type": "boolean"}, "expected_revision": {"type": "integer", "minimum": 0}, "context": ref("emoji_context")},
                ("name", "match", "alias", "enabled", "expected_revision"))])


def schema_with_defs(node):
    """Self-contained schemas with only reachable definitions, not duplicate expansion."""
    root = copy.deepcopy(node)
    if "$ref" in root:
        root = copy.deepcopy(DEFS[root["$ref"].rsplit("/", 1)[-1]])
    needed = {}

    def visit(value):
        if isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, dict):
            if "$ref" in value:
                name = value["$ref"].rsplit("/", 1)[-1]
                if name not in needed:
                    needed[name] = copy.deepcopy(DEFS[name])
                    visit(needed[name])
            for key, item in value.items():
                if key != "$ref":
                    visit(item)

    visit(root)
    result = {"$schema": DIALECT, **root}
    if needed:
        result["$defs"] = needed
    return result


def output_with_errors(success):
    """Pre-acceptance failures never fabricate an operation or success receipt."""
    failure = obj({"error": ref("error"), "message": string(1500),
                   "next_action": NEXT, "retry_safe": {"const": False}},
                  ("error", "message", "next_action", "retry_safe"))
    properties = {key: {} for key in (*success.get("properties", {}), *failure["properties"])}
    # Success and failure are disjoint: success-specific required fields are absent
    # from the closed failure branch. The definitions are gathered transitively.
    return {"type": "object", "properties": properties,
            "additionalProperties": False, "oneOf": [success, failure]}


def catalog():
    result = copy.deepcopy(TOOLS)
    for item in result:
        for field in ("inputSchema", "outputSchema"):
            node = item[field]
            if field == "outputSchema":
                if "$ref" in node:
                    node = copy.deepcopy(DEFS[node["$ref"].rsplit("/", 1)[-1]])
                node = output_with_errors(node)
            item[field] = schema_with_defs(node)
    return {"version": VERSION, "tools": result}


def project_catalog(scopes, *, publish_destinations=(), owner=False):
    """Trusted auth-context projection, not a substitute for per-resource checks.

    publish_destinations must be the active verified binding snapshot resolved by
    the server, never caller-supplied aliases. Read access is derived, not a new grant.
    """
    effective = set(scopes)
    effective.discard("social.read")  # Legacy read scope cannot bypass destination binding.
    if owner or ("publish" in effective and publish_destinations):
        effective.add("social.read")
    if owner:
        effective.add("media.store")
    # Narrow task scopes expose only their own command variants.
    if publish_destinations and ("publish" in effective or "media.store" in effective):
        effective.add("publication.manage")  # Original-publish recovery projection; no lifecycle grant.
        if "forward" in effective:
            effective.add("engage")
        if "destination.profile" in effective:
            effective.add("destinations")
    if "publish" in effective:
        effective.add("visual")  # Import-only projection below; no generation grant.
    result = []
    for item in catalog()["tools"]:
        if item["required_scope"] not in effective:
            continue
        if item["name"] == "vibepublish_carousel" and "visual" not in scopes:
            continue  # Publish-only identities receive image import, not private authoring.
        item.pop("required_scope")
        if item["name"] == "vibepublish_publication_update" and "publication.manage" not in scopes:
            schema = item["inputSchema"]
            schema["properties"].pop("item_ref", None)
            scoped_destinations = {**array(enum(*sorted(set(publish_destinations))), 1, 20),
                                   "uniqueItems": True}
            schema["properties"]["change"] = {"oneOf": [
                arm("retry_failed", {"destinations": scoped_destinations}, ("destinations",)),
                arm("supersede_failed", {"destinations": scoped_destinations, "content": ref("content")},
                    ("destinations", "content")),
                arm("reconcile", {"operation_id": ID, "attempt_id": ID},
                    ("operation_id", "attempt_id"))]}
            if "media.store" in scopes and "publish" not in scopes:
                # Service identity may only retry its own proven zero-dispatch
                # media_store effect, never supersede/change/delete messages.
                schema["properties"]["change"]["oneOf"] = [
                    item for item in schema["properties"]["change"]["oneOf"]
                    if item["properties"]["kind"]["const"] == "retry_failed"]
            schema["required"] = ["publication_id", "expected_revision", "change", "request_key"]
            schema.pop("oneOf", None)
            item["description"] = ("Recover only this principal's original publish. reconcile observes its frozen dispatched MAX attempt without another effect; "
                "retry_failed re-admits the same revision; supersede_failed cancels selected failed children "
                "and creates a linked new publication with corrected content and the same verified media. "
                "Current publish bindings and request keys are required; successful siblings stay unchanged.")
        if item["name"] == "vibepublish_visual" and "visual" not in scopes:
            item["inputSchema"]["properties"]["command"] = {"oneOf": [arm("import"), *copy.deepcopy(workspace_import_commands)]}
            item["description"] = "Import a chat attachment or bounded workspace image bytes as a private image asset, without AI or publication."
            item["annotations"]["title"] = "Private image import — no publication or generation"
        if item["name"] == "vibepublish_publish" and "visual" not in scopes:
            item["inputSchema"]["properties"].pop("visual", None)
            item["inputSchema"]["anyOf"] = [v for v in item["inputSchema"]["anyOf"] if v.get("required") != ["visual"]]
        if item["name"] == "vibepublish_read" and not owner:
            variants = item["inputSchema"]["properties"]["query"]["oneOf"]
            item["inputSchema"]["properties"]["query"]["oneOf"] = [
                v for v in variants if v["properties"]["kind"]["const"] != "dialogs"]
        if item["name"] == "vibepublish_engage" and "engage" not in scopes and not owner:
            variants = item["inputSchema"]["properties"]["command"]["oneOf"]
            item["inputSchema"]["properties"]["command"]["oneOf"] = [
                v for v in variants if v["properties"]["kind"]["const"] == "forward"]
        if item["name"] == "vibepublish_destinations" and (
                not owner or not {"destinations", "publication.manage"} <= set(scopes)):
            variants = item["inputSchema"]["properties"]["command"]["oneOf"]
            item["inputSchema"]["properties"]["command"]["oneOf"] = [
                v for v in variants if v["properties"]["kind"]["const"] != "binding_grant_edit"]
        if item["name"] == "vibepublish_destinations" and "destinations" not in scopes and not owner:
            variants = item["inputSchema"]["properties"]["command"]["oneOf"]
            item["inputSchema"]["properties"]["command"]["oneOf"] = [
                v for v in variants if v["properties"]["kind"]["const"] in {"list", "profile_update", "emoji_set_register", "emoji_alias_select", "emoji_rule_put"}]
        if "publish" not in scopes:
            for _field in ("command", "query"):
                _variants = item["inputSchema"].get("properties", {}).get(_field, {}).get("oneOf")
                if _variants:
                    item["inputSchema"]["properties"][_field]["oneOf"] = [v for v in _variants if not v.get("properties", {}).get("kind", {}).get("const", "").startswith("emoji_")]
        result.append(item)
    return result


if __name__ == "__main__":
    print(json.dumps(catalog(), ensure_ascii=False, indent=2))
