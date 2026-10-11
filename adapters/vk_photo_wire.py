"""Small, metadata-free VK photo wire derivatives; immutable assets stay unchanged."""
from io import BytesIO
from PIL import Image


def photo_wire_bytes(data: bytes, mime: str) -> tuple[bytes, str]:
    if mime not in {"image/png", "image/webp"}:
        return data, mime
    try:
        with Image.open(BytesIO(data)) as image:
            if (image.mode != "RGB" or getattr(image, "n_frames", 1) != 1
                    or image.width * image.height > 25_000_000):
                return data, mime
            image.load()
            # A fresh image prevents source EXIF, comments or profiles leaking.
            clean = Image.frombytes("RGB", image.size, image.tobytes())
            output = BytesIO()
            clean.save(output, format="JPEG", quality=92, subsampling=0, optimize=True)
            candidate = output.getvalue()
        if len(candidate) < len(data):
            return candidate, "image/jpeg"
    except (OSError, ValueError, Image.DecompressionBombError):
        pass
    return data, mime
