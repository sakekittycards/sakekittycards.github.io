"""
Real-ESRGAN wrapper for the graded-card pipeline.

Runs the `realesrgan-ncnn-vulkan.exe` binary on a PIL image and returns a
PIL image. The binary is a single Windows executable with a `models/`
folder beside it - free, MIT-licensed, GPU-accelerated via Vulkan
(falls back to CPU when no GPU is present).

If the binary isn't installed we fall back to Pillow's LANCZOS resize so
the rest of the pipeline keeps working - users just don't get the AI
quality boost. Print a one-time warning so the miss is visible.

Install with `setup-upscaler.ps1` (one-shot download + extract).
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from PIL import Image

UPSCALER_DIR = Path(__file__).parent / "upscaler"
BIN_NAME = "realesrgan-ncnn-vulkan.exe"
# realesrgan-x4plus is the photo-trained model; the default
# realesr-animevideov3 oversmooths card art textures.
DEFAULT_MODEL = "realesrgan-x4plus"


def find_binary() -> Path | None:
    candidate = UPSCALER_DIR / BIN_NAME
    if candidate.exists():
        return candidate
    # Some release zips nest the binary one folder deep - check children too.
    if UPSCALER_DIR.exists():
        for sub in UPSCALER_DIR.iterdir():
            if sub.is_dir():
                inner = sub / BIN_NAME
                if inner.exists():
                    return inner
    return None


_warned = False


def upscale_pil(img: Image.Image, scale: int = 2,
                model: str = DEFAULT_MODEL) -> Image.Image:
    """
    Upscale a PIL image with Real-ESRGAN. Returns a PIL image.

    Falls back to Pillow LANCZOS if the binary is missing or fails so the
    pipeline doesn't hard-stop on a misconfigured machine.
    """
    global _warned
    binary = find_binary()
    if binary is None:
        if not _warned:
            print(f"    [upscaler] Real-ESRGAN not found at {UPSCALER_DIR} - "
                  f"using LANCZOS fallback. Run setup-upscaler.ps1 to install.")
            _warned = True
        w, h = img.size
        return img.resize((w * scale, h * scale), Image.LANCZOS)

    models_dir = binary.parent / "models"
    with tempfile.TemporaryDirectory() as td:
        in_path = Path(td) / "in.png"
        out_path = Path(td) / "out.png"
        img.convert("RGB").save(in_path, "PNG")
        cmd = [
            str(binary),
            "-i", str(in_path),
            "-o", str(out_path),
            "-s", str(scale),
            "-n", model,
            "-m", str(models_dir),
        ]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=180,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            print(f"    [upscaler] failed ({e}) - using LANCZOS fallback")
            w, h = img.size
            return img.resize((w * scale, h * scale), Image.LANCZOS)
        if result.returncode != 0 or not out_path.exists():
            tail = ""
            if result.stderr:
                tail = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else ""
            print(f"    [upscaler] Real-ESRGAN exit={result.returncode} {tail}"
                  f" - using LANCZOS fallback")
            w, h = img.size
            return img.resize((w * scale, h * scale), Image.LANCZOS)
        # .copy() so the temp file can be deleted before we hand the image off.
        return Image.open(out_path).convert("RGB").copy()
