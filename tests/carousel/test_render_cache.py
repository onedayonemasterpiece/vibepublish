from types import SimpleNamespace

from social_operations import carousel


def test_full_canvas_render_is_reused_per_owner_svg_and_layers(monkeypatch):
    calls = []
    monkeypatch.setattr(carousel, 'render_svg', lambda svg, **kw: calls.append((svg, kw.get('layers'))) or b'png')
    carousel._RENDERED.clear()
    service = carousel.CarouselService.__new__(carousel.CarouselService)
    owner = SimpleNamespace(tenant_id='t', principal_id='p')
    other = SimpleNamespace(tenant_id='t', principal_id='q')
    row = {'svg': '<svg/>', 'card_count': 3, 'card_width': 128, 'card_height': 160}
    assert service._render(owner, row) == b'png'
    assert service._render(owner, row) == b'png'
    assert len(calls) == 1
    service._render(owner, row, layers={'only': ['bg']})
    service._render(other, row)
    service._render(owner, {**row, 'svg': '<svg id="x"/>'})
    assert len(calls) == 4
