"""Canonical guide, real MCP image bytes and view-tagged review questions."""
import io
import re

import pytest
from PIL import Image

from social_operations.assets import AssetPreview
from social_operations.carousel_guide import GuideImages, _read, _sections, guide
from social_operations.service import Application
from social_operations.storage import Store


@pytest.mark.asyncio
async def test_canonical_guide_and_half_scale_master_are_exposed_by_mcp(tmp_path):
    store = Store(tmp_path / "carousel-guide.sqlite")
    actor = store.authenticate(store.create_principal("tenant", "owner", owner=True))
    app = Application(store)

    async def call(command, request_key=None):
        args = {"command": command}
        if request_key:
            args["request_key"] = request_key
        result = await app.call(actor, "vibepublish_carousel", args)
        assert not (isinstance(result, dict) and "error" in result), result
        return result

    index = await call({"kind": "get", "scope": "guide"})
    assert index["private"] and index["content"] == _read("README.md")
    assert index["topics"] == [
        "steps/s01", "steps/s02", "steps/s03", "steps/s04", "steps/s05", "steps/s06", "steps/s07", "steps/s08", "steps/s09", "steps/s10",
        "00-process", "10-storytelling", "20-composition", "30-seams",
        "40-typography", "50-palettes", "60-generation", "70-montage",
        "80-variation", "85-style-continuity", "90-review", "95-infographics", "99-platform"]
    step = await call({"kind": "get", "scope": "guide", "topic": "steps/s01"})
    assert step["content"] == _read("steps/s01.md")
    process = await call({"kind": "get", "scope": "guide", "topic": "00-process"})
    assert "Правила процесса" in process["content"] and "Знаков" in process["content"]
    process_part = await call({"kind": "get", "scope": "guide", "topic": "00-process",
                               "section": "Правила"})
    assert len(process_part["content"]) <= 7000
    review = await call({"kind": "get", "scope": "guide", "topic": "90-review"})
    assert "Теги видов" in review["content"] and len(review["content"]) <= 7000
    review_part = await call({"kind": "get", "scope": "guide", "topic": "90-review",
                             "section": "Теги видов"})
    assert "[master]" in review_part["content"]

    seams_index = await call({"kind": "get", "scope": "guide", "topic": "30-seams"})
    assert not isinstance(seams_index, GuideImages)
    assert "Введение" in seams_index["content"] and len(seams_index["content"]) <= 7000
    seams = await call({"kind": "get", "scope": "guide", "topic": "30-seams",
                        "section": "Введение"})
    assert isinstance(seams, GuideImages)
    assert "transition-atlas.svg" in seams.metadata["content"]
    assert seams.metadata["images"][0]["path"].endswith("/transition-atlas.svg")
    with Image.open(io.BytesIO(seams.images[0])) as atlas:
        assert atlas.format == "PNG" and atlas.size == (1320, 1470)

    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="384" height="160">'
           '<rect width="192" height="160" fill="#E5A448"/>'
           '<text x="10" y="110" fill="#222" font-size="30" font-family="Bebas Neue">ЁЖЯ</text>'
           '</svg>')
    created = await call({"kind": "create", "brief": "Три кадра",
        "card_count": 3, "card_width": 128, "card_height": 160,
        "svg": svg}, request_key="guide-create")
    carousel_id = created["carousel_id"]
    scoped = await call({"kind": "get", "scope": "guide", "carousel_id": carousel_id,
                         "topic": "30-seams", "section": "Введение"})
    assert scoped.metadata["carousel_id"] == carousel_id
    journal = await call({"kind": "get", "scope": "journal", "carousel_id": carousel_id})
    guide_reads = [entry for entry in journal["journal"]
                   if entry["kind"] == "get" and entry.get("scope") == "guide"]
    assert len(guide_reads) == 1
    assert isinstance(guide_reads[0]["duration_ms"], int)
    def expected_questions(view):
        tag = next(line for line in _read("90-review.md").splitlines()
                   if line.startswith(f"- [{view}] "))
        ids = re.findall(r"\b(?:[QVRK]\d{2}|ST[1-7])\b", tag)
        # Every tagged question is delivered; more than seven would overload render.
        assert 1 <= len(ids) <= 7, (view, ids)
        return ids

    master = await call({"kind": "render", "carousel_id": carousel_id,
        "revision": 1, "view": "master", "scale": 0.5, "cutlines": True})
    assert isinstance(master, AssetPreview)
    assert master.metadata["mime_type"] == "image/jpeg"
    assert master.metadata["size"] == "full"
    assert master.metadata["scale"] == 0.5 and master.metadata["cutlines"]
    assert master.metadata["width"] == 192 and master.metadata["height"] == 80
    assert [q["id"] for q in master.metadata["review_questions"]] == expected_questions("master")
    with Image.open(io.BytesIO(master.data)) as image:
        image = image.convert("RGB")
        assert image.size == (192, 80)
        assert image.getpixel((64, 40))[0] < 110  # actual dark cutline
        assert min(image.getpixel((160, 40))) > 235  # white empty card

    card = await call({"kind": "render", "carousel_id": carousel_id,
        "revision": 1, "card": 2})
    assert [q["id"] for q in card.metadata["review_questions"]] == expected_questions("card")
    crop = await call({"kind": "render", "carousel_id": carousel_id,
        "revision": 1, "view": "region", "region": [10, 20, 20, 80]})
    assert [q["id"] for q in crop.metadata["review_questions"]] == expected_questions("region")
    pair = await call({"kind": "render", "carousel_id": carousel_id,
        "revision": 1, "view": "region", "region": [118, 20, 20, 80]})
    assert [q["id"] for q in pair.metadata["review_questions"]] == expected_questions("pair")
    with store.connection() as db:
        assert db.execute("SELECT count(*) FROM publications").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_generation_guide_does_not_default_body_to_typesetting(tmp_path):
    store = Store(tmp_path / "generation-guide.sqlite")
    actor = store.authenticate(store.create_principal("tenant", "owner", owner=True))
    result = await Application(store).call(actor, "vibepublish_carousel", {
        "command": {"kind": "get", "scope": "guide", "topic": "60-generation", "section": "§0"}})
    content = result["content"]
    assert "основной способ — генерация компонентов, включая читаемые поясняющие мини-абзацы" in content
    assert "автоматического перехода тела, подписей и длинных формулировок на F8 нет" in content
    assert "обычно набирай F8" not in content
    assert "F8 остаётся осмысленной адресной альтернативой для конкретного блока" in content
    assert "проверяй каждую букву, число и факт на готовом изображении" in content
    assert "для одинаковых ролей (все заголовки) — один" in content


def test_each_model_guide_reply_is_bounded_and_sections_are_complete():
    """No guide reply may be long enough to truncate in the model's context."""
    index = guide()
    assert len(index["content"]) <= 7000
    for topic in index["topics"]:
        item = guide(topic)
        metadata = item.metadata if isinstance(item, GuideImages) else item
        assert len(metadata["content"]) <= 7000, topic
        if topic.startswith("steps/"):
            assert metadata["content"] == _read(topic + ".md")
            assert len(metadata["content"]) < 3000
            continue
        sections = _sections(_read(topic + ".md"))
        assert sections
        for title, original in sections:
            part = guide(topic, section=title)
            data = part.metadata if isinstance(part, GuideImages) else part
            assert len(data["content"]) <= 7000, (topic, title)
            assert data["content"] == original, (topic, title)
            assert data["section"] == title
