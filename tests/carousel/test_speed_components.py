"""Direct raster resize and SVG target regression without renderer dependencies."""
import hashlib
import io
from xml.etree import ElementTree as ET

from PIL import Image
from social_operations.carousel_compositor import _prepare_raster, _prepared, _prepared_lock, _display_targets


def test_prepared_image_downsizes_and_reuses_by_sha_and_target():
    image = Image.new("RGB", (3000, 4000), "#3a6980")
    raw = io.BytesIO()
    image.save(raw, "PNG")
    data = raw.getvalue()
    sha = hashlib.sha256(data).hexdigest()
    first = _prepare_raster(data, "image/png", sha, (600, 800))
    assert first[1] == "image/jpeg"
    assert first[2] == (600, 800)
    assert len(first[0]) < len(data)
    assert _prepare_raster(data, "image/png", sha, (600, 800)) is first
    assert _prepare_raster(data, "image/png", sha, (300, 400))[2] == (300, 400)
    with _prepared_lock:
        assert (sha, (600, 800)) in _prepared


def test_prepared_transparent_png_keeps_alpha():
    image = Image.new("RGBA", (160, 120), (20, 40, 60, 0))
    image.putpixel((80, 60), (200, 0, 0, 255))
    raw = io.BytesIO()
    image.save(raw, "PNG")
    data = raw.getvalue()
    prepared = _prepare_raster(data, "image/png", hashlib.sha256(data).hexdigest(), (80, 60))
    assert prepared[1] == "image/png"
    with Image.open(io.BytesIO(prepared[0])) as scaled:
        assert scaled.size == (80, 60)
        assert scaled.getpixel((0, 0))[3] == 0
        assert scaled.getpixel((40, 30))[3] > 0


def test_display_targets_largest_reuse_and_scale():
    root = ET.fromstring('<svg xmlns="http://www.w3.org/2000/svg"><image href="asset:p" width="100" height="200"/><g transform="scale(2)"><image href="asset:p" width="200" height="100"/></g></svg>')
    assert _display_targets(root)["p"] == (600, 300)
