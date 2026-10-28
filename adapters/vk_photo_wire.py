"""Small, metadata-free VK photo wire derivatives; immutable assets stay unchanged."""
from io import BytesIO
from PIL import Image


def photo_wire_bytes(data: bytes, mime: str, max_edge: int | None = None) -> tuple[bytes, str]:
    """JPEG wire copy; with max_edge (stories) larger photos are also downscaled."""
    if mime not in {"image/png", "image/webp"} and not max_edge:
        return data, mime
    try:
        with Image.open(BytesIO(data)) as image:
            if (image.mode != "RGB" or getattr(image, "n_frames", 1) != 1
                    or image.width * image.height > 25_000_000):
                return data, mime
            image.load()
            # A fresh image prevents source EXIF, comments or profiles leaking.
            clean = Image.frombytes("RGB", image.size, image.tobytes())
            if max_edge and max(clean.size) > max_edge:
                clean.thumbnail((max_edge, max_edge), Image.LANCZOS)
            elif mime == "image/jpeg":
                return data, mime
            output = BytesIO()
            clean.save(output, format="JPEG", quality=92, subsampling=0, optimize=True)
            candidate = output.getvalue()
        if len(candidate) < len(data):
            return candidate, "image/jpeg"
    except (OSError, ValueError, Image.DecompressionBombError):
        pass
    return data, mime
