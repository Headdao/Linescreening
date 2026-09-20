"""Tiny CGImage helpers (shared by capture/ocr/checks — no circular deps)."""

from __future__ import annotations

from typing import Any


def image_size(img: Any) -> tuple[int, int]:
    """Return (width, height) in pixels for a CGImageRef."""
    import Quartz

    return int(Quartz.CGImageGetWidth(img)), int(Quartz.CGImageGetHeight(img))
