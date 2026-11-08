"""Run native SVG rasterization outside the caller's Python GIL."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading

# Saved ordinary cold renders reached 96 s; this bounds a stuck child without
# shortening that observed working path. This is not a raster speed target.
_RENDER_TIMEOUT_SECONDS = 300
# Native resvg previously serialized on this process's GIL. Keep that bound.
_RASTER_LOCK = threading.Lock()


def svg_to_bytes(**options) -> bytes:
    """Keep the existing renderer/options; return its PNG or one terminal error."""
    width, height = options["width"], options["height"]
    # resvg returns 8-bit RGBA PNG. Include row filters and ample PNG/deflate
    # overhead without buffering an unbounded child stdout in the API process.
    output_limit = 4 * width * height + height + 1024 * 1024
    with _RASTER_LOCK, tempfile.TemporaryFile() as output:
        try:
            result = subprocess.run(
                [sys.executable, str(Path(__file__).resolve())],
                input=json.dumps(options).encode("utf-8"),
                stdout=output, stderr=subprocess.DEVNULL,
                timeout=_RENDER_TIMEOUT_SECONDS, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            # run() kills and waits for its child before raising.
            raise RuntimeError("SVG renderer timed out") from exc
        if result.returncode:
            raise RuntimeError("SVG renderer failed")
        output.seek(0)
        data = output.read(output_limit + 1)
        if len(data) > output_limit:
            raise RuntimeError("SVG renderer output limit exceeded")
        return data


if __name__ == "__main__":
    import resvg_py

    sys.stdout.buffer.write(resvg_py.svg_to_bytes(**json.load(sys.stdin)))
