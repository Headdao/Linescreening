"""Notification Center dump (content source C) — the quiet-mode workhorse.

Flow (all AX actions whitelisted in guards.py):
  click menu-bar clock → wait for panel animation → capture panel → OCR →
  parse notifications → press Esc to close. Never touches LINE itself.
"""

from __future__ import annotations

import subprocess
import time

from linescreening import capture, guards
from linescreening.cgimage import image_size
from linescreening.config import Config
from linescreening.ocr import recognize_cgimage
from linescreening.parse import NotificationItem, parse_notifications


class NcDumpError(RuntimeError):
    """Could not open/capture the Notification Center."""


def _run_osascript(script: str) -> str:
    proc = subprocess.run(
        ["osascript", "-e", script], capture_output=True, text=True, timeout=15, check=False
    )
    if proc.returncode != 0:
        raise NcDumpError(f"osascript failed: {proc.stderr.strip()[:200]}")
    return proc.stdout.strip()


def open_notification_center() -> str:
    guards.ax_assert_allowed("click_menu_bar_clock")
    out = _run_osascript(guards.OSASCRIPT_CLICK_CLOCK)
    if not out.startswith("clicked:"):
        raise NcDumpError("找不到選單列時鐘（AX 無法定位 com.apple.menuextra.clock）")
    return out


def close_notification_center() -> None:
    guards.ax_assert_allowed("press_escape")
    _run_osascript(guards.OSASCRIPT_PRESS_ESC)


def dump_once(cfg: Config) -> list[NotificationItem]:
    """Open NC, OCR the panel, close it. Returns parsed notifications."""
    open_notification_center()
    time.sleep(float(cfg.nc_panel["capture_settle_s"]))
    try:
        img = capture.capture_nc_panel()
        items = recognize_cgimage(
            img, languages=cfg.ocr["recognition_languages"], min_confidence=0.4
        )
        return parse_notifications(items, float(image_size(img)[0]))
    finally:
        try:
            close_notification_center()
        except NcDumpError:
            pass  # panel may already be closed; never fail the dump for this
