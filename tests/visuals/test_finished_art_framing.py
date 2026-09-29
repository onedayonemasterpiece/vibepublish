import io
import json

from PIL import Image, ImageDraw
import pytest

from social_operations.compositor import FORMATS, render


@pytest.mark.parametrize("format_name", ["post_4_5", "story_9_16"])
@pytest.mark.parametrize("source_size", [(1280, 960), (960, 1280), (1600, 900)])
def test_finished_art_preserves_all_four_corners(format_name, source_size):
    iw, ih = source_size
    art = Image.new("RGB", source_size, "white")
    draw = ImageDraw.Draw(art)
    corners = [(0, 0, "red"), (iw - 80, 0, "green"), (0, ih - 80, "blue"), (iw - 80, ih - 80, "black")]
    for x, y, color in corners:
        draw.rectangle((x, y, x + 79, y + 79), fill=color)
    buf = io.BytesIO()
    art.save(buf, "PNG")
    result = render(buf.getvalue(), {}, format_name)
    image = Image.open(io.BytesIO(result.png)).convert("RGB")
    w, h = FORMATS[format_name]
    assert image.size == (w, h)
    scale = min(w / iw, h / ih)
    ox, oy = (w - iw * scale) / 2, (h - ih * scale) / 2
    expected = [(255, 0, 0), (0, 128, 0), (0, 0, 255), (0, 0, 0)]
    for (x, y, _), color in zip(corners, expected):
        px, py = round(ox + (x + 40) * scale), round(oy + (y + 40) * scale)
        assert image.getpixel((px, py)) == color
    assert b'preserveAspectRatio="xMidYMid meet"' in result.svg
    assert json.loads(result.recipe_json)["art_fit"] == "contain"


def test_structured_copy_retains_existing_cover_and_exact_text():
    art = Image.new("RGB", (1280, 960), "white")
    buf = io.BytesIO()
    art.save(buf, "PNG")
    result = render(buf.getvalue(), {"title": "История города"}, "post_4_5")
    recipe = json.loads(result.recipe_json)
    assert recipe["art_fit"] == "cover"
    assert b'preserveAspectRatio="xMidYMid slice"' in result.svg
    assert recipe["copy"]["title"] == "История города"
