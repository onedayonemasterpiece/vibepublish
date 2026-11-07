"""Bounded raster reuse and source-size canvas target regressions."""
import hashlib
import io
from xml.etree import ElementTree as ET
from PIL import Image
from social_operations.carousel_compositor import _prepare_raster, _prepared, _prepared_lock, _display_targets

def test_raster_cache_downsamples_opaque_png_by_target():
    source = Image.new('RGB', (3000, 4000), '#3a6980')
    output = io.BytesIO()
    source.save(output, format='PNG')
    data = output.getvalue()
    sha = hashlib.sha256(data).hexdigest()
    reduced = _prepare_raster(data, 'image/png', sha, (600, 800))
    assert reduced[1] == 'image/jpeg' and reduced[2] == (600, 800)
    assert len(reduced[0]) < len(data)
    assert _prepare_raster(data, 'image/png', sha, (600, 800)) is reduced
    with _prepared_lock:
        assert (sha, (600, 800)) in _prepared

def test_alpha_raster_remains_transparent_png():
    source = Image.new('RGBA', (160, 120), (30, 50, 80, 0))
    source.putpixel((80, 60), (200, 0, 0, 255))
    output = io.BytesIO()
    source.save(output, 'PNG')
    data = output.getvalue()
    reduced = _prepare_raster(data, 'image/png', hashlib.sha256(data).hexdigest(), (80, 60))
    assert reduced[1] == 'image/png'
    with Image.open(io.BytesIO(reduced[0])) as image:
        assert image.size == (80, 60) and image.getpixel((0, 0))[3] == 0

def test_target_tracks_largest_image_with_parent_scale():
    root = ET.fromstring('<svg xmlns="http://www.w3.org/2000/svg"><image href="asset:p" width="100" height="200"/><g transform="scale(2)"><image href="asset:p" width="200" height="100"/></g></svg>')
    assert _display_targets(root)['p'] == (600, 300)
