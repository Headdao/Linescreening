"""Screen capture — the only module that touches pixels, strictly bounded.

All regions pass through guards.py validation. Nothing here ever clicks or
sends events; capturing pixels has no effect on LINE's read state.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from linescreening import checks, guards
from linescreening.cgimage import image_size
from linescreening.config import Config, load_config
from linescreening.guards import GuardError


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
        int(image_size(img)[0]),
        int(image_size(img)[1]),
        left_frac=float(side["width_fraction"]),
        top_frac=float(side["top_inset_fraction"]),
    )
    rect = quartz.CGRectMake(
        0,
        int(image_size(img)[1] * float(side["top_inset_fraction"])),
        int(image_size(img)[0] * float(side["width_fraction"])),
        int(image_size(img)[1] * (1 - float(side["top_inset_fraction"]))),
    )
    cropped = quartz.CGImageCreateWithImageInRect(img, rect)
    if cropped is None:
        raise CaptureError("側欄裁切失敗")
    return cropped


def capture_sidebar(cfg: Config | None = None) -> Any:
    """One call: window capture + sidebar crop. Returns the CGImage."""
    cfg = cfg or load_config()
    return crop_sidebar(capture_line_window(), cfg)


def capture_nc_panel() -> Any:
    """Capture the open Notification Center panel (call after opening it).

    Prefers the NC overlay window itself (window-scoped capture); falls back
    to the right-hand screen strip (guards: nc_panel)."""
    quartz = _quartz()

    try:
        from Quartz import (
            CGWindowListCopyWindowInfo,
            kCGNullWindowID,
            kCGWindowListExcludeDesktopElements,
            kCGWindowListOptionOnScreenOnly,
        )

        infos = CGWindowListCopyWindowInfo(
            kCGWindowListOptionOnScreenOnly | kCGWindowListExcludeDesktopElements,
            kCGNullWindowID,
        )
        for info in infos or []:
            owner = info.get("kCGWindowOwnerName") or ""
            if owner == "通知中心" and (info.get("kCGWindowLayer") or 0) >= 20:
                b = info.get("kCGWindowBounds", {})
                guards.capture_rect(
                    "nc_panel",
                    int(b.get("X", 0)),
                    int(b.get("Y", 0)),
                    int(b.get("Width", 0)),
                    int(b.get("Height", 0)),
                )
                img = quartz.CGWindowListCreateImage(
                    quartz.CGRectNull,
                    quartz.kCGWindowListOptionIncludingWindow,
                    info["kCGWindowNumber"],
                    quartz.kCGWindowImageNominalResolution,
                )
                if img is not None:
                    return img
    except GuardError:
        raise

    # Fallback: right strip of the main display (panel slides from the edge).
    from Quartz import CGDisplayBounds, CGMainDisplayID

    display = CGMainDisplayID()
    bounds = CGDisplayBounds(display)
    width = int(bounds.size.width * 0.35)
    guards.capture_rect(
        "nc_panel",
        int(bounds.size.width - width),
        0,
        width,
        int(bounds.size.height),
    )
    rect = quartz.CGRectMake(bounds.size.width - width, 0, width, bounds.size.height)
    img = quartz.CGWindowListCreateImage(
        rect,
        quartz.kCGWindowListOptionOnScreenOnly,
        quartz.kCGNullWindowID,
        quartz.kCGWindowImageNominalResolution,
    )
    if img is None:
        raise CaptureError("擷取通知中心失敗（可能沒有螢幕錄製權限）")
    return img


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
