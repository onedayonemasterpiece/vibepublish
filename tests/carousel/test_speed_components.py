"""Downsampling, bounded reuse, and component revision inventory."""
import hashlib
import io
from PIL import Image
from social_operations.carousel_compositor import _prepare_raster, _prepared, _prepared_lock, _display_targets
from xml.etree import ElementTree as ET


def test_prepared_image_downsizes_and_reuses_by_sha_and_target():
    original = Image.new("RGB", (3000, 4000), "#3a6980")
    source = io.BytesIO()
    original.save(source, "PNG")
    data = source.getvalue()
    sha = hashlib.sha256(data).hexdigest()
    first = _prepare_raster(data, "image/png", sha, (600, 800))
    assert first[1] == "image/jpeg"
    assert first[2] == (600, 800)
    assert len(first[0]) < len(data)
    second = _prepare_raster(data, "image/png", sha, (600, 800))
    assert second is first
    third = _prepare_raster(data, "image/png", sha, (300, 400))
    assert third[2] == (300, 400)
    with _prepared_lock:
        assert (sha, (600, 800)) in _prepared


def test_transparent_prepared_png_preserves_alpha():
    source = Image.new("RGBA", (160, 120), (20, 40, 60, 0))
    source.putpixel((80, 60), (200, 0, 0, 255))
    out = io.BytesIO()
    source.save(out, "PNG")
    data = out.getvalue()
    result = _prepare_raster(data, "image/png", hashlib.sha256(data).hexdigest(), (80, 60))
    assert result[1] == "image/png"
    with Image.open(io.BytesIO(result[0])) as reduced:
        assert reduced.size == (80, 60)
        assert reduced.getpixel((0, 0))[3] == 0
        assert reduced.getpixel((40, 30))[3] > 0


def test_display_target_uses_largest_reuse_and_group_scale():
    svg = ET.fromstring('<svg xmlns="http://www.w3.org/2000/svg"><image href="asset:p" width="100" height="200"/><g transform="scale(2)"><image href="asset:p" width="200" height="100"/></g></svg>')
    assert _display_targets(svg)["p"] == (600, 300)
