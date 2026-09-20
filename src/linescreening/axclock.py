"""In-process Accessibility clock click — replaces the osascript approach.

Why: the embedded python (Homebrew framework build) re-execs as Python.app,
so osascript children attribute their AX needs to python — a permission the
user never granted. Calling the AX APIs IN-PROCESS attributes to the
responsible app (Linescreening), which already holds the grant for screen
capture. Falls back to osascript if in-process traversal finds nothing.
"""

from __future__ import annotations

import subprocess

from linescreening import guards

CLOCK_IDENTIFIER = "com.apple.menuextra.clock"
_CANDIDATE_PROCESSES = ("ControlCenter", "SystemUIServer")


def _pid_of(process_name: str) -> int | None:
    proc = subprocess.run(
        ["pgrep", "-x", process_name], capture_output=True, text=True, timeout=10, check=False
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    return int(proc.stdout.strip().splitlines()[0])


def find_clock_and_click() -> bool:
    """Traverse the menu-bar extras of the owning process and press the
    clock item. Returns True when the click was performed."""
    from ApplicationServices import (
        AXUIElementCopyAttributeValue,
        AXUIElementCreateApplication,
        kAXChildrenAttribute,
        kAXIdentifierAttribute,
    )

    for name in _CANDIDATE_PROCESSES:
        pid = _pid_of(name)
        if pid is None:
            continue
        app = AXUIElementCreateApplication(pid)
        # the menu bar is a child of the app element (kAXMenuBarAttribute
        # returns nothing useful on Tahoe)
        _err, children = AXUIElementCopyAttributeValue(app, kAXChildrenAttribute, None)
        for child in children or ():
            _e, extras = AXUIElementCopyAttributeValue(child, kAXChildrenAttribute, None)
            for extra in extras or ():
                _e2, ident = AXUIElementCopyAttributeValue(extra, kAXIdentifierAttribute, None)
                if ident and CLOCK_IDENTIFIER in str(ident):
                    if guards.ax_press_clock(extra, name):
                        return True
    return False


def open_notification_center_inprocess() -> bool:
    """True when the clock was clicked in-process."""
    return find_clock_and_click()


__all__ = ["open_notification_center_inprocess"]
