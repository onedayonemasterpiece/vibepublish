"""Executable design, not an MCP server. Render: python contracts/social_mcp_v1.py.

The eight-tool design is selected for implementation; weak-agent effectiveness
is not established by schema validation. No credentials or provider I/O here.
"""
from __future__ import annotations
import copy
import json

VERSION = "1.5.0-runtime"
DIALECT = "https://json-schema.org/draft/2020-12/schema"


def obj(properties, required=()):
    return {"type": "object", "properties": properties,
            "required": list(required), "additionalProperties": False}


def string(max_length=20000, **kwargs):
    return {"type": "string", "minLength": 1, "maxLength": max_length, **kwargs}


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
URL = string(4096, format="uri", pattern=r"^https://")
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
        "label": string(200), "revision": REV, "members": array(ALIAS, 0, 100)},
        ("alias", "kind", "label", "revision")),
    "capability": obj({"destination": ALIAS, "operation": string(80),
        "surface": string(80), "status": enum("supported", "unsupported", "needs_auth", "needs_review", "temporarily_unavailable"),
        "observed_at": DATE, "reason": string(500)},
        ("destination", "operation", "surface", "status", "observed_at")),
    "delivery_result": obj({"destination": ALIAS, "provider": PROVIDER,
        "state": STATE, "observed": enum("not_attempted", "provider_scheduled", "provider_processing", "published", "edited", "deleted", "cancelled", "absent", "unknown"),
        "observed_at": DATE, "revision": REV, "requested_at": DATE, "effective_at": DATE,
        "stage": STAGE, "scheduling_owner": {"const": "provider"}, "item_ref": ID, "url": URL,
        "queue_ref": ID, "preview_ref": ID, "navigate_hint": string(500),
        "evidence_ref": ID, "media_check": enum("not_applicable", "source_bytes", "provider_binding", "visual_correspondence", "incomplete"),
        "missing_checks": array(string(100), 0, 20), "retry_safe": {"type": "boolean"}},
        ("destination", "provider", "state", "stage", "observed", "revision", "media_check", "retry_safe")),
    "candidate": obj({"id": ID, "asset_ref": ID, "sha256": string(64, pattern=r"^[a-f0-9]{64}$"),
        "preview_url": URL, "width": {"type": "integer", "minimum": 1},
        "height": {"type": "integer", "minimum": 1}, "format": enum("post_4_5", "story_9_16"),
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

# Exact typography is data, not text inferred from a generation prompt.
DEFS["visual_copy"] = obj({"title": string(160), "subtitle": string(240),
    "body": string(1200), "date_line": string(160), "location_line": string(240),
    "source_line": string(300)})
for visual_arm in DEFS["visual_spec"]["oneOf"]:
    visual_arm["properties"]["copy"] = ref("visual_copy")
    visual_arm["properties"]["formats"] = {**array(enum("post_4_5", "story_9_16"), 1, 2),
                                           "uniqueItems": True}
# Events commit with the corresponding state change; they are not transient logs.
DEFS["event"] = obj({"seq": REV, "operation_id": ID, "destination": ALIAS,
    "at": DATE, "stage": STAGE, "status": enum("started", "completed", "failed", "blocked", "unknown"),
    "message": string(1000), "item_index": {"type": "integer", "minimum": 0},
    "item_count": {"type": "integer", "minimum": 1}, "evidence_ref": ID},
    ("seq", "operation_id", "at", "stage", "status", "message"))
DEFS["progress"] = obj({"events": array(ref("event"), 0, 50),
    "cursor": string(512), "has_more": {"type": "boolean"}}, ("events", "cursor", "has_more"))
DEFS["read_item"] = obj({"ref": ID, "kind": string(80), "text": string(), "url": URL,
    "publication_id": ID, "revision": REV, "destination": ALIAS,
    "publication_kind": enum("original", "forward"), "forward_origin": ref("forward_origin"),
    "scheduled_at": DATE, "published_at": DATE, "observed_at": DATE,
    "source": enum("provider", "local_history"), "freshness": enum("current", "cached", "unknown"),
    "origin": enum("vibepublish", "provider_client", "imported"),
    "observed_state": enum("provider_scheduled", "provider_processing", "published", "deleted", "cancelled", "unknown"),
    "queue_ref": ID, "preview_ref": ID, "navigate_hint": string(500),
    "media": array(ref("media"), 0, 20), "metrics_observed_at": DATE, "error": ref("error"),
    "metrics": array(obj({"name": string(100), "value": {"type": "number"}, "unit": string(40)},
                         ("name", "value")), 0, 100)}, ("ref", "kind", "observed_at", "source", "freshness"))
DEFS["receipt"] = obj({"operation_id": ID, "resource_id": ID, "revision": REV,
    "action": string(80), "state": STATE, "message": string(1500),
    "operation_complete": {"type": "boolean"}, "progress": ref("progress"),
    "items": array(ref("read_item"), 0, 50), "next_cursor": string(512), "worker_seen_at": DATE,
    "truncated": {"type": "boolean"},
    "visual_job_id": ID, "visual_revision": REV, "selected_asset_ref": ID,
    "selected_sha256": string(64, pattern=r"^[a-f0-9]{64}$"),
    "executor": obj({"requested_route": string(120), "actual_executor": {"type": ["string", "null"], "maxLength": 160},
                     "actual_model": {"type": ["string", "null"], "maxLength": 160}, "fixture": {"type": "boolean"}},
                    ("requested_route", "actual_executor", "actual_model", "fixture")),
    "next_action": NEXT, "retry_safe": {"type": "boolean"}, "receipt_ref": ID,
    "deliveries": array(ref("delivery_result"), 0, 100),
    "candidates": array(ref("candidate"), 0, 4), "destinations": array(ref("destination"), 0, 100),
    "review_token": string(512), "poll_after_seconds": {"type": "integer", "minimum": 1},
    "error": ref("error"), "dry_run": {"type": "boolean"}},
    ("operation_id", "action", "state", "message", "operation_complete", "progress", "next_action", "retry_safe", "receipt_ref", "deliveries"))

TOOLS = []


def tool(name, description, inputs, outputs, scope, read_only=False):
    TOOLS.append({"name": "vibepublish_" + name, "description": description,
        "inputSchema": inputs, "outputSchema": outputs, "required_scope": scope,
        "annotations": {"readOnlyHint": read_only, "destructiveHint": not read_only,
                        "openWorldHint": name not in ("get_started", "status")}})


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

tool("publish", "Create one publication now or in native provider queues; return accepted progress without waiting for providers. No local scheduler. Preview does not send.",
    obj({"to": array(ALIAS, 1, 20), "content": ref("content"), "media": array(ref("media"), 0, 20),
        "surface": enum("post", "story", "message", "album", "video", "short_video"),
        "delivery": ref("delivery"), "mode": enum("execute", "preview"),
        "renderings": ref("renderings"), "visual": ref("visual_spec"),
        "request_key": KEY, "repeat_of": ID, "routing_revision": REV}, ("to",)), ref("receipt"), "publish")

TOOLS[-1]["inputSchema"]["anyOf"] = [
    {"required": ["content"]}, {"required": ["visual"]},
    {"required": ["media"], "properties": {"media": {"minItems": 1}}}]

change = {"oneOf": [
    arm("approve", {"token": string(512)}, ("token",)),
    arm("edit", {"content": ref("content"), "media": array(ref("media"), 0, 20), "renderings": ref("renderings")}),
    arm("reschedule", {"delivery": DEFS["delivery"]["oneOf"][1]}, ("delivery",)),
    arm("cancel"), arm("delete"),
    arm("retry_failed", {"destinations": array(ALIAS, 1, 20)}, ("destinations",))]}
change["oneOf"][1]["anyOf"] = [{"required": [p]} for p in ("content", "media", "renderings")]
tool("publication_update", "Change an existing publication at an exact revision. Cancel unsent work; delete published work; retry only proven safe failures.",
    obj({"publication_id": ID, "expected_revision": REV, "item_ref": ID, "change": change, "request_key": KEY},
        ("change",)), ref("receipt"), "publication.manage")
# Existing private publication CAS or one exact immutable observed native item.
# An item ref is already a scoped snapshot CAS, not a mutable provider revision.
TOOLS[-1]["inputSchema"]["oneOf"] = [
    {"required": ["publication_id", "expected_revision"], "not": {"required": ["item_ref"]}},
    {"required": ["item_ref"], "not": {"anyOf": [{"required": ["publication_id"]}, {"required": ["expected_revision"]}]}}]

visual_cmd = {"oneOf": [ref("visual_spec"),
    arm("select", {"job_id": ID, "candidate_id": ID, "expected_revision": REV, "token": string(512)},
        ("job_id", "candidate_id", "expected_revision", "token")),
    arm("feedback", {"job_id": ID, "candidate_id": ID, "rating": enum("accepted", "rejected"), "reason": string(2000)},
        ("job_id", "candidate_id", "rating"))]}
tool("visual", "Generate, tune or compose image candidates, select one, or record feedback. Selection resumes only its exact authorized parent.",
    obj({"command": visual_cmd, "request_key": KEY}, ("command",)), ref("receipt"), "visual")

tool("status", "Read local receipts and atomic progress, never retry. Watch one operation with after_event; return on its first new event, not all providers.",
    obj({"ids": array(ID, 1, 20), "limit": LIMIT, "cursor": string(512),
        "after_event": string(512), "wait_seconds": {"type": "integer", "minimum": 0, "maximum": 10}}),
    obj({"receipts": array(ref("receipt"), 0, 50), "next_cursor": string(512)}, ("receipts",)), "status", True)

# Event cursors are bound to one operation, principal and policy epoch.
TOOLS[-1]["inputSchema"]["allOf"] = [{
    "if": {"anyOf": [{"required": ["after_event"]}, {"required": ["wait_seconds"]}]},
    "then": {"required": ["ids"], "properties": {"ids": {"maxItems": 1}},
             "not": {"required": ["cursor"]}}}]

queries = [arm("item", {"item_ref": {"oneOf": [ID, URL]}}, ("item_ref",)),
    arm("dialogs", {"provider": PROVIDER}, ("provider",))]
for k in ("feed", "stories", "scheduled", "notifications", "audience", "editorial_sample"):
    queries.append(arm(k, {"destination": ALIAS}, ("destination",)))
for k in ("thread", "reactions"):
    queries.append(arm(k, {"item_ref": ID}, ("item_ref",)))
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

tool("destinations", "List allowed aliases, update personal purpose/notes/primary-channel profiles, or manage granted destination sets. Profiles and URLs never grant access.",
    obj({"command": {"oneOf": [arm("list"),
        arm("profile_update", {"alias": ALIAS, "expected_revision": {"type": "integer", "minimum": 0},
            "profile": {**DEFS["destination_profile"], "minProperties": 1}}, ("alias", "expected_revision", "profile")),
        arm("resolve", {"provider": PROVIDER, "url": URL}, ("provider", "url")),
        arm("search", {"provider": PROVIDER, "text": string(500)}, ("provider", "text")),
        arm("set_put", {"alias": ALIAS, "label": string(200), "expected_revision": {"type": "integer", "minimum": 0},
            "members": array(ALIAS, 1, 100)}, ("alias", "label", "expected_revision", "members")),
        arm("set_delete", {"alias": ALIAS, "expected_revision": REV}, ("alias", "expected_revision")),
        arm("rename_label", {"alias": ALIAS, "label": string(200), "expected_revision": REV},
            ("alias", "label", "expected_revision"))]}, "request_key": KEY}, ("command",)),
    ref("receipt"), "destinations")



# Telegram palette extensions keep the canonical eight methods and closed grammar.
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
    # Narrow task scopes expose only their own command variants.
    if publish_destinations and "publish" in effective:
        if "forward" in effective:
            effective.add("engage")
        if "destination.profile" in effective:
            effective.add("destinations")
    result = []
    for item in catalog()["tools"]:
        if item["required_scope"] not in effective:
            continue
        item.pop("required_scope")
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
        if item["name"] == "vibepublish_destinations" and "destinations" not in scopes and not owner:
            variants = item["inputSchema"]["properties"]["command"]["oneOf"]
            item["inputSchema"]["properties"]["command"]["oneOf"] = [
                v for v in variants if v["properties"]["kind"]["const"] in {"list", "profile_update", "emoji_set_register", "emoji_alias_select", "emoji_rule_put"}]
        if "publish" not in scopes:
            for _field in ("command", "query"):
                _variants = item["inputSchema"].get("properties", {}).get(_field, {}).get("oneOf")
                if _variants:
                    item["inputSchema"]["properties"][_field]["oneOf"] = [v for v in _variants if not v["properties"]["kind"]["const"].startswith("emoji_")]
        result.append(item)
    return result


if __name__ == "__main__":
    print(json.dumps(catalog(), ensure_ascii=False, indent=2))
