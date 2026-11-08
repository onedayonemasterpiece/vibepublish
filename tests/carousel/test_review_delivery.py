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
    assert questions[0]["id"] == "Q01"
    assert {"Q01", "Q07", "Q04", "K16"} <= {question["id"] for question in review_questions("card")}
    assert len(questions) <= 7


@pytest.mark.asyncio
@pytest.mark.parametrize("view", ["master", "card"])
async def test_render_exposes_priority_questions_and_document_text_fact(tmp_path, view):
    store = Store(tmp_path / "review.sqlite")
    actor = store.authenticate(store.create_principal("tenant", "owner", owner=True))
    app = Application(store)
    created = await app.call(actor, "vibepublish_carousel", {
        "command": {"kind": "create", "brief": "Composition review", "card_count": 3,
                    "card_width": 128, "card_height": 160,
                    "svg": '<svg xmlns="http://www.w3.org/2000/svg"><rect width="384" height="160" fill="#fff"/>'
                           '<text x="270" y="40" font-family="Montserrat" font-size="20">Текст</text></svg>'},
        "request_key": "review-create"})
    rendered = await app.call(actor, "vibepublish_carousel", {
        "command": {"kind": "render", "carousel_id": created["carousel_id"],
                    "revision": 1, **({"view": "master"} if view == "master" else {"card": 1})}})
    assert isinstance(rendered, AssetPreview)
    questions = rendered.metadata["review_questions"]
    assert questions[0]["id"] == ("Q01" if view == "master" else "Q07")
    # The text is on card 3, outside the card-1 crop: the fact remains document-scoped.
    assert "1 узлов <text> (scope=document" in questions[0]["observe"]
    assert len(questions) <= 7


@pytest.mark.parametrize("namespace", ["", ' xmlns="http://www.w3.org/2000/svg"'])
def test_text_fact_counts_source_nodes_not_visibility_size_or_use_clones(namespace):
    svg = (f'<svg{namespace} xmlns:other="urn:other">'
           '<defs><text id="word">Один</text></defs>'
           '<style>.hidden { display: none; font-size: 400px }</style>'
           '<g transform="translate(2160 0) scale(4)"><text class="hidden">Два<tspan>три</tspan></text></g>'
           '<use href="#word"/><use href="#word"/>'
           '<path d="M0 0 L1 1"/><image href="asset:raster"/>'
           '<desc>&lt;text&gt; is not a node</desc><!-- <text/> -->'
           '<other:text>Not SVG text</other:text></svg>')
    for view in ("master", "card", "pair", "region"):
        question = review_questions(view, source_svg=svg)[0]
        assert "2 узлов <text> (scope=document" in question["observe"]
        assert "не число видимых или крупных" in question["observe"]
        assert "scope=document" not in review_questions(view)[0]["observe"]


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
    assert [item["id"] for item in review_questions("master")] == priority


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
