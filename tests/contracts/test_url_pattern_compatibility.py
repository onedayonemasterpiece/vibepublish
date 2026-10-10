"""Public HTTPS schemas must work in whole-string-matching MCP clients."""
import copy
import re

import pytest
from jsonschema import Draft202012Validator, FormatChecker, ValidationError, validators

from contracts.social_mcp_v1 import catalog, project_catalog

URLS = (
    "https://example.com",
    "https://app.myatom.ru/event/7873af3a-b103-44c9-89cb-164b273b03fc",
    "https://vk.com/club231828790",
    "https://max.ru/channel_kenigevents",
    "https://example.com/path?next=a%20b&x=1#section",
)


def full_match_pattern(validator, pattern, instance, schema):
    if isinstance(instance, str) and re.fullmatch(pattern, instance) is None:
        yield ValidationError("Pattern must match the entire string")


FullMatchValidator = validators.extend(
    Draft202012Validator, {"pattern": full_match_pattern}
)


def update_schema():
    return next(t["inputSchema"] for t in project_catalog(
        {"publication.manage"}, owner=True
    ) if t["name"] == "vibepublish_publication_update")


@pytest.mark.parametrize("url", URLS)
@pytest.mark.parametrize("target", [
    {"item_ref": "item_fixture"},
    {"publication_id": "pub_fixture", "expected_revision": 1},
])
@pytest.mark.parametrize("field", ["content", "renderings"])
def test_semantic_link_edit_accepts_https_with_search_and_fullmatch_clients(url, target, field):
    content = {"paragraphs": [[{"kind": "text", "text": "🌍 "}],
                              [{"kind": "link", "label": "Зарегистрироваться", "url": url}]]}
    change = {"kind": "edit", field: content if field == "content" else {"telegram": content}}
    args = {**target, "change": change, "request_key": "semantic-url-fixture"}
    for cls in (Draft202012Validator, FullMatchValidator):
        cls(update_schema(), format_checker=FormatChecker()).validate(args)


def test_regression_old_prefix_regex_rejects_valid_link_only_in_fullmatch_client():
    schema = copy.deepcopy(update_schema())
    schema["$defs"]["inline"]["oneOf"][1]["properties"]["url"]["pattern"] = r"^https://"
    args = {"item_ref": "item_fixture", "change": {"kind": "edit", "content": {
        "paragraphs": [[{"kind": "link", "label": "Register", "url": URLS[0]}]]
    }}}
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(args)
    assert list(FullMatchValidator(schema, format_checker=FormatChecker()).iter_errors(args))


@pytest.mark.parametrize("url", ["http://example.com", "https://", "javascript:alert(1)",
                               "https://example.com/has space"])
def test_invalid_link_is_rejected_before_admission(url):
    args = {"item_ref": "item_fixture", "change": {"kind": "edit", "content": {
        "paragraphs": [[{"kind": "link", "label": "Register", "url": url}]]
    }}}
    for cls in (Draft202012Validator, FullMatchValidator):
        assert list(cls(update_schema(), format_checker=FormatChecker()).iter_errors(args))


def test_shared_url_pattern_is_complete_on_every_public_schema_surface():
    found = 0
    def visit(node):
        nonlocal found
        if isinstance(node, dict):
            if node.get("pattern", "").startswith("^https://"):
                found += 1
                assert node["pattern"].endswith("$")
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)
    for tool in catalog()["tools"]:
        visit(tool["inputSchema"])
    assert found >= 4
