"""Screen capture — the only module that touches pixels, strictly bounded.

All regions pass through guards.py validation. Nothing here ever clicks or
sends events; capturing pixels has no effect on LINE's read state.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from linescreening import checks, guards
from linescreening.config import Config, load_config


class CaptureError(RuntimeError):
    """LINE window missing, or permission denied (see checks.doctor)."""


def _quartz() -> Any:
    try:
        import Quartz
    except ImportError as exc:  # pragma: no cover - non-macOS/CI
        raise CaptureError("pyobjc Quartz unavailable") from exc
    return Quartz


def capture_line_window() -> Any:
    """Capture ONLY the LINE window (other windows never enter the frame)."""
    quartz = _quartz()
    win = checks.find_line_window()
    if win is None:
        raise CaptureError(
            "找不到畫面上的 LINE 視窗（需要 LINE 開啟且未最小化，且終端機具備螢幕錄製權限）"
        )
    bounds = win.get("kCGWindowBounds", {})
    guards.capture_rect(
        "line_window",
        int(bounds.get("X", 0)),
        int(bounds.get("Y", 0)),
        int(bounds.get("Width", 0)),
        int(bounds.get("Height", 0)),
    )
    img = quartz.CGWindowListCreateImage(
        quartz.CGRectNull,
        quartz.kCGWindowListOptionIncludingWindow,
        win["kCGWindowNumber"],
        quartz.kCGWindowImageNominalResolution,
    )
    if img is None:
        raise CaptureError("擷取 LINE 視窗失敗（可能沒有螢幕錄製權限）")
    return img


def crop_sidebar(img: Any, cfg: Config) -> Any:
    """Crop the chat-list sidebar from the LINE window capture."""
    quartz = _quartz()
    side = cfg.sidebar
    guards.crop_to_kind(
        "line_window",
        int(img.getWidth()),
        int(img.getHeight()),
        left_frac=float(side["width_fraction"]),
        top_frac=float(side["top_inset_fraction"]),
    )
    rect = quartz.CGRectMake(
        0,
        int(img.getHeight() * float(side["top_inset_fraction"])),
        int(img.getWidth() * float(side["width_fraction"])),
        int(img.getHeight() * (1 - float(side["top_inset_fraction"]))),
    )
    cropped = quartz.CGImageCreateWithImageInRect(img, rect)
    if cropped is None:
        raise CaptureError("側欄裁切失敗")
    return cropped


def capture_sidebar(cfg: Config | None = None) -> Any:
    """One call: window capture + sidebar crop. Returns the CGImage."""
    cfg = cfg or load_config()
    return crop_sidebar(capture_line_window(), cfg)


def save_png(img: Any, path: Path | str) -> Path:
    """Dev helper: dump a capture to disk for calibration/debugging."""
    quartz = _quartz()
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    url = quartz.CFURLCreateFromFileSystemRepresentation(
        None, str(path).encode(), len(str(path).encode()), False
    )
    dest = quartz.CGImageDestinationCreateWithURL(url, "public.png", 1, None)
    if dest is None:
        raise CaptureError(f"cannot create {path}")
    quartz.CGImageDestinationAddImage(dest, img, None)
    quartz.CGImageDestinationFinalize(dest)
    return path
