"""Advisory review priority and complete bounded access through the real application."""
import re

import pytest

from social_operations.assets import AssetPreview
from social_operations.carousel_guide import _read, guide, review_questions
from social_operations.domain import DomainError
from jsonschema import Draft202012Validator

from social_operations.service import Application, CATALOG
from social_operations.storage import Store


def test_render_question_selection_keeps_composition_and_reference_priorities():
    questions = review_questions("master")
    assert {"K14", "K16"} <= {question["id"] for question in questions}
    assert len(questions) <= 5


@pytest.mark.asyncio
async def test_master_render_exposes_composition_and_reference_questions(tmp_path):
    store = Store(tmp_path / "review.sqlite")
    actor = store.authenticate(store.create_principal("tenant", "owner", owner=True))
    app = Application(store)
    created = await app.call(actor, "vibepublish_carousel", {
        "command": {"kind": "create", "brief": "Composition review", "card_count": 3,
                    "card_width": 128, "card_height": 160,
                    "svg": '<svg xmlns="http://www.w3.org/2000/svg"><rect width="384" height="160" fill="#fff"/></svg>'},
        "request_key": "review-create"})
    rendered = await app.call(actor, "vibepublish_carousel", {
        "command": {"kind": "render", "carousel_id": created["carousel_id"],
                    "revision": 1, "view": "master"}})
    assert isinstance(rendered, AssetPreview)
    questions = rendered.metadata["review_questions"]
    assert {"K14", "K16"} <= {question["id"] for question in questions}
    assert len(questions) <= 5


QUESTION_IDS = ([f"{prefix}{number:02d}" for prefix, count in
                 (("Q", 35), ("V", 30), ("R", 15), ("K", 17))
                 for number in range(1, count + 1)]
                + [f"ST{number}" for number in range(1, 8)])


@pytest.mark.parametrize("question_id", QUESTION_IDS)
def test_every_review_question_is_addressable_without_rendering(question_id):
    section = f"question:{question_id}"
    result = guide("90-review", section=section)
    tool = CATALOG["vibepublish_carousel"]
    Draft202012Validator(tool["inputSchema"]).validate({"command": {
        "kind": "get", "scope": "guide", "topic": "90-review", "section": section}})
    Draft202012Validator(tool["outputSchema"]).validate(result)
    source = "85-style-continuity.md" if question_id.startswith("ST") else "90-review.md"
    row = next(line for line in _read(source).splitlines()
               if re.match(r"^\|\s*" + question_id + r"(?:\.\s|\s*\|)", line))
    cells = [cell.strip() for cell in row.strip().strip("|").split("|")]
    assert result["private"] and result["section"] == question_id
    assert result["sources"] == ["docs/llm/carousel/" + source]
    assert len(result["content"]) <= 7000
    assert "images" not in result
    for cell in cells:
        assert cell in result["content"]
    if question_id not in ("K01", "R01"):
        assert guide("90-review", section=question_id) == result


def test_review_priority_is_source_order_not_a_fixed_category_mix(monkeypatch):
    import social_operations.carousel_guide as module
    original_read = module._read
    priority = ["Q01", "K14", "V01", "K16", "ST7", "Q34"]

    def read(name):
        text = original_read(name)
        if name == "90-review.md":
            text = re.sub(r"(?m)^- \[master\].+$", "- [master] " + " ".join(priority), text)
        return text

    monkeypatch.setattr(module, "_read", read)
    assert [item["id"] for item in review_questions("master")] == priority[:5]


def test_review_index_explains_existing_section_lookup_and_old_sections_survive():
    assert 'section:"question:Q01"' in guide("90-review")["content"]
    assert guide("90-review", section=" k14 ")["section"] == "K14"
    assert guide("90-review", section="K01–K16")["section"].startswith("K01–K16:")
    for prefix, heading in (("K01", "K01–K16"), ("R01", "R01–R15")):
        assert guide("90-review", section=prefix) == guide("90-review", section=heading)
    assert guide("90-review", section=" Question:k01 ")["section"] == "K01"
    for question_id in ("Q99", "ST8", "K14,K16"):
        with pytest.raises(DomainError):
            guide("90-review", section=question_id)


@pytest.mark.asyncio
async def test_individual_review_questions_use_unchanged_mcp_guide_contract(tmp_path):
    store = Store(tmp_path / "review-guide.sqlite")
    actor = store.authenticate(store.create_principal("tenant", "owner", owner=True))
    app = Application(store)
    for ident in ("K14", "K16", "Q35", "V30", "R15", "ST7", "question:K01", "question:R01"):
        result = await app.call(actor, "vibepublish_carousel", {
            "command": {"kind": "get", "scope": "guide", "topic": "90-review", "section": ident}})
        assert result["section"] == ident.removeprefix("question:")
        assert result["private"] and "images" not in result
    with store.connection() as db:
        assert db.execute("SELECT count(*) FROM operations").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM publications").fetchone()[0] == 0
