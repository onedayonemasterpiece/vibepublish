from io import BytesIO
from dataclasses import replace
from unittest.mock import AsyncMock
import pytest
from PIL import Image, PngImagePlugin
from adapters.vk_photo_wire import photo_wire_bytes
from adapters.vk_transport import VKHTTPTransport
from social_operations.domain import DomainError
from .test_vk_photo_copy_binding import setup_copy


def png(mode="RGB", size=(128, 192), compress_level=0):
    image = Image.new(mode, size, "orange")
    out = BytesIO()
    info = PngImagePlugin.PngInfo()
    info.add_text("private", "secret-sentinel")
    image.save(out, format="PNG", compress_level=compress_level, pnginfo=info)
    return out.getvalue()


def test_smaller_jpeg_preserves_dimensions_and_source():
    source = png()
    original = bytes(source)
    wire, mime = photo_wire_bytes(source, "image/png")
    assert mime == "image/jpeg" and len(wire) < len(source)
    assert source == original
    with Image.open(BytesIO(wire)) as image:
        assert image.size == (128, 192) and image.mode == "RGB"
        assert not image.getexif()
    assert b"secret-sentinel" not in wire


@pytest.mark.parametrize("data,mime", [
    (png(size=(1, 1), compress_level=9), "image/png"),
    (png(mode="RGBA"), "image/png"),
    (b"already-jpeg", "image/jpeg"),
    (b"invalid", "image/png"),
])
def test_no_larger_derivative_or_alpha_loss(data, mime):
    assert photo_wire_bytes(data, mime) == (data, mime)


@pytest.mark.asyncio
async def test_transport_upload_uses_jpeg_metadata(monkeypatch):
    import aiohttp
    fields = []
    class Form:
        def add_field(self, name, data, **kwargs):
            fields.append((name, data, kwargs))
    monkeypatch.setattr(aiohttp, "FormData", Form)
    transport = VKHTTPTransport(tokens={})
    transport._post = AsyncMock(return_value={"server": 1, "photo": "receipt", "hash": "hash"})
    await transport.upload_photo("https://pu.vk.com/upload", png(), "image/png")
    name, wire, meta = fields[0]
    assert name == "photo" and wire.startswith(b"\xff\xd8")
    assert meta == {"filename": "verified.jpg", "content_type": "image/jpeg"}


def failure(status, phase="media_upload"):
    error = DomainError("vk_http_failed")
    error.http_status = status
    error.http_phase = phase
    return error


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [502, 503, 504])
async def test_upload_retry_uses_fresh_server_then_single_effect(monkeypatch, status):
    import adapters.vk
    monkeypatch.setattr(adapters.vk.asyncio, "sleep", AsyncMock())
    a, t, j, r = setup_copy()
    r = replace(r, assets=(r.assets[0],))
    upload, invoke = t.upload_photo, t.invoke
    attempts, methods = [], []
    async def calls(**kwargs):
        methods.append(kwargs["method"])
        return await invoke(**kwargs)
    async def transient(url, data, mime):
        attempts.append(url)
        if len(attempts) < 3:
            raise failure(status)
        return await upload(url, data, mime)
    t.invoke, t.upload_photo = calls, transient
    result = await a.execute(await a.prepare(r, j.hooks), j.hooks)
    assert result.observed == "provider_scheduled"
    assert len(attempts) == 3
    assert methods.count("photos.getWallUploadServer") == 3
    assert methods.count("photos.saveWallPhoto") == 1
    assert t.effects == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status,phase,count", [
    (504, "media_upload", 3), (403, "media_upload", 1),
    (429, "media_upload", 1), (500, "media_upload", 1), (504, "api", 1),
    (None, "media_upload", 1),
])
async def test_retry_is_bounded_before_save_and_dispatch(monkeypatch, status, phase, count):
    import adapters.vk
    monkeypatch.setattr(adapters.vk.asyncio, "sleep", AsyncMock())
    a, t, j, r = setup_copy()
    t.upload_photo = AsyncMock(side_effect=failure(status, phase))
    with pytest.raises(DomainError):
        await a.execute(await a.prepare(r, j.hooks), j.hooks)
    assert t.upload_photo.await_count == count
    assert t.effects == 0 and not t.uploads


@pytest.mark.asyncio
async def test_save_failure_is_never_retried(monkeypatch):
    import adapters.vk
    monkeypatch.setattr(adapters.vk.asyncio, "sleep", AsyncMock())
    a, t, j, r = setup_copy()
    invoke = t.invoke
    saves = []
    async def broken_save(**kwargs):
        if kwargs["method"] == "photos.saveWallPhoto":
            saves.append(1)
            raise failure(504, "api")
        return await invoke(**kwargs)
    t.invoke = broken_save
    with pytest.raises(DomainError):
        await a.execute(await a.prepare(r, j.hooks), j.hooks)
    assert len(saves) == 1 and len(t.uploads) == 1 and t.effects == 0
