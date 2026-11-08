"""The API loop must keep progressing during a native call that holds the GIL."""
import asyncio
import importlib.util
import io
import os
import shlex
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from PIL import Image

from social_operations.carousel_compositor import render_document_svg


def test_event_loop_progresses_during_native_raster(tmp_path, monkeypatch):
    # PyDLL keeps the caller's GIL for the whole C system() call. The shell writes
    # both markers inside that native call, so a delayed Python callback cannot
    # mistake the end of the blocking call for progress during it.
    started, finished = tmp_path / "started", tmp_path / "finished"
    command = (f"touch {shlex.quote(str(started))}; sleep 1; "
               f"touch {shlex.quote(str(finished))}")
    module_path = tmp_path / "resvg_py.py"
    module_path.write_text(
        "import ctypes\n"
        "def svg_to_bytes(**options):\n"
        f"    ctypes.PyDLL(None).system({command.encode()!r})\n"
        "    return b'render-result'\n"
    )
    spec = importlib.util.spec_from_file_location("resvg_py", module_path)
    native = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(native)
    monkeypatch.setitem(sys.modules, "resvg_py", native)
    monkeypatch.setenv("PYTHONPATH", str(tmp_path) + os.pathsep + os.environ.get("PYTHONPATH", ""))

    async def exercise():
        task = asyncio.create_task(asyncio.to_thread(
            render_document_svg, "<svg/>", width=1, height=1))
        try:
            async with asyncio.timeout(5):
                while not started.exists():
                    if task.done():
                        await task
                        raise AssertionError("Native renderer did not start")
                    await asyncio.sleep(.005)
                assert not finished.exists(), "Native raster held the API process GIL"
                # A second independently scheduled callback also runs before
                # native completion, as another request on the API loop would.
                await asyncio.sleep(0)
                assert not finished.exists()
        finally:
            assert await task == b"render-result"

    asyncio.run(exercise())


@pytest.mark.parametrize("background", [None, "#ffffff"])
def test_real_resvg_bytes_dimensions_fonts_and_alpha_are_unchanged(background):
    import resvg_py
    from social_operations import svg_raster
    from social_operations.carousel_compositor import _RENDER_FONT_FILES

    options = dict(svg_string='<svg xmlns="http://www.w3.org/2000/svg" width="96" height="64">'
                   '<text x="2" y="22" font-size="18">Йёй</text></svg>',
                   width=96, height=64, skip_system_fonts=True,
                   font_files=list(_RENDER_FONT_FILES), font_family="Montserrat")
    if background is not None:
        options["background"] = background
    actual = svg_raster.svg_to_bytes(**options)
    assert actual == resvg_py.svg_to_bytes(**options)
    with Image.open(io.BytesIO(actual)) as png:
        assert png.format == "PNG" and png.size == (96, 64)
        assert png.convert("RGBA").getpixel((95, 63))[3] == (0 if background is None else 255)


def test_concurrent_rasters_keep_previous_single_native_invocation(monkeypatch):
    from social_operations import svg_raster

    start = threading.Barrier(2)
    active = maximum = 0

    def child(*args, **kwargs):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        time.sleep(.05)  # Yield the GIL while the other caller is ready.
        kwargs["stdout"].write(b"PNG")
        active -= 1
        return SimpleNamespace(returncode=0)

    def render():
        start.wait(timeout=5)
        return svg_raster.svg_to_bytes(svg_string="<svg/>", width=1, height=1)

    monkeypatch.setattr(svg_raster.subprocess, "run", child)
    with ThreadPoolExecutor(2) as workers:
        results = [workers.submit(render) for _ in range(2)]
        assert [result.result(timeout=5) for result in results] == [b"PNG", b"PNG"]
    assert maximum == 1


@pytest.mark.parametrize("route,command", [
    ("search", {"kind": "get", "scope": "icons", "query": "library"}),
    ("get", {"kind": "get", "scope": "icon", "id": "svgrepo:342687"}),
    ("command", {"kind": "get", "scope": "guide", "topic": "20-cover"}),
    ("command", {"kind": "render", "carousel_id": "carousel_" + "1" * 32, "revision": 1}),
])
def test_mcp_raster_routes_keep_subprocess_wait_off_event_loop(tmp_path, monkeypatch, route, command):
    from social_operations.domain import DomainError
    from social_operations.service import Application
    from social_operations.storage import Store

    store = Store(tmp_path / "routes.sqlite")
    actor = store.authenticate(store.create_principal("tenant", "owner", owner=True))
    app = Application(store)
    loop_thread = threading.get_ident()
    calls = []

    def reached(*args):
        calls.append(threading.get_ident())
        raise DomainError("raster_route_checked")

    target = app.carousels if route == "command" else app.carousel_icons
    monkeypatch.setattr(target, route, reached)
    result = asyncio.run(app.call(actor, "vibepublish_carousel", {"command": command}))
    assert result["error"]["code"] == "raster_route_checked"
    assert calls and calls[0] != loop_thread


@pytest.mark.parametrize("icon,code", [(False, "carousel_svg_invalid"), (True, "carousel_icon_unsafe")])
def test_native_failure_preserves_existing_domain_errors(icon, code):
    from social_operations.carousel_icons import _thumb
    from social_operations.domain import DomainError

    with pytest.raises(DomainError) as error:
        if icon:
            _thumb("invalid SVG")
        else:
            render_document_svg("invalid SVG", width=1, height=1)
    assert error.value.code == code
