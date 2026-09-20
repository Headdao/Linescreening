"""Screen capture — the only module that touches pixels, strictly bounded.

All regions pass through guards.py validation. Nothing here ever clicks or
sends events; capturing pixels has no effect on LINE's read state.
"""

from __future__ import annotations

import subprocess
import time
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


def _capture_window_by_id(quartz: Any, window_id: int) -> Any:
    return quartz.CGWindowListCreateImage(
        quartz.CGRectNull,
        quartz.kCGWindowListOptionIncludingWindow,
        window_id,
        quartz.kCGWindowImageNominalResolution,
    )


def _frontmost_app() -> str | None:
    try:
        from AppKit import NSWorkspace

        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        return app.localizedName()
    except Exception:  # noqa: BLE001 — best effort
        return None


def _activate(app_name: str) -> None:
    guards.os_assert_allowed("activate_app")
    subprocess.run(["open", "-a", app_name], check=False, timeout=10)


def _capture_line_candidate(quartz: Any, win: dict) -> Any:
    """Validate + capture one window dict, or None if not capturable."""
    bounds = win.get("kCGWindowBounds", {})
    guards.capture_rect(
        "line_window",
        int(bounds.get("X", 0)),
        int(bounds.get("Y", 0)),
        int(bounds.get("Width", 0)),
        int(bounds.get("Height", 0)),
    )
    return _capture_window_by_id(quartz, win["kCGWindowNumber"])


def _onscreen_line_windows(quartz: Any) -> list[dict]:
    """Currently visible layer-0 LINE windows, widest first (main window
    with the chat-list sidebar is the widest)."""
    infos = quartz.CGWindowListCopyWindowInfo(
        quartz.kCGWindowListOptionOnScreenOnly | quartz.kCGWindowListExcludeDesktopElements,
        quartz.kCGNullWindowID,
    )
    wins = []
    for info in infos or []:
        if (info.get("kCGWindowOwnerName") or "") != "LINE":
            continue
        if info.get("kCGWindowLayer", 0) != 0:
            continue
        b = info.get("kCGWindowBounds") or {}
        if b.get("Width", 0) >= 300 and b.get("Height", 0) >= 300:
            wins.append(dict(info))
    wins.sort(key=lambda w: -(w["kCGWindowBounds"].get("Width", 0)))
    return wins


def capture_line_window(activate_if_needed: bool = True) -> Any:  # noqa: FBT001, FBT002
    """Capture ONLY the LINE main window (other windows never enter the frame).

    LINE often lives on another Space where its buffer is not capturable —
    in that case briefly activate LINE (switching Space), re-scan the now
    visible windows, capture the widest (main window with sidebar), and put
    the previous app back in front. Activation never sends input into LINE,
    so it cannot mark anything as read."""
    quartz = _quartz()

    win = checks.find_line_window()
    if win is not None:
        img = _capture_line_candidate(quartz, win)
        if img is not None:
            return img

    if not activate_if_needed:
        raise CaptureError("擷取 LINE 視窗失敗（可能沒有螢幕錄製權限）")

    previous = _frontmost_app()
    _activate("LINE")
    img = None
    for _ in range(12):  # wait up to ~1.8s for the Space switch
        for win in _onscreen_line_windows(quartz):
            img = _capture_line_candidate(quartz, win)
            if img is not None:
                break
        if img is not None:
            break
        time.sleep(0.15)
    if previous and previous != "LINE":
        _activate(previous)
    if img is None:
        raise CaptureError("擷取 LINE 視窗失敗（無法聚焦 LINE；請確認它在某個桌面上未最小化）")
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
