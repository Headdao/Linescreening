"""Security red-line tests.

These run in CI and fail the build if anyone weakens the guarantees:
bounded capture regions, AX whitelist (no clicks into LINE), no shell=True,
static osascript payloads, watcher stays network-free.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from linescreening.guards import (
    ALLOWED_AX_ACTIONS,
    GuardError,
    ax_assert_allowed,
    capture_rect,
    crop_to_kind,
)

SRC = Path(__file__).resolve().parents[1] / "src" / "linescreening"


# --- bounded capture -------------------------------------------------------


def test_capture_rect_allows_named_kinds():
    r = capture_rect("line_window", 10, 20, 800, 600)
    assert (r.x, r.y, r.w, r.h) == (10, 20, 800, 600)


def test_capture_rect_rejects_unknown_kind():
    with pytest.raises(GuardError):
        capture_rect("whole_screen", 0, 0, 5000, 3000)


def test_capture_rect_rejects_huge_region():
    with pytest.raises(GuardError):
        capture_rect("line_window", 0, 0, 4000, 3000)


def test_capture_rect_rejects_nonpositive():
    with pytest.raises(GuardError):
        capture_rect("nc_panel", 0, 0, 0, 100)


def test_crop_to_kind_sane():
    r = crop_to_kind("line_window", 1000, 800, left_frac=0.28, top_frac=0.06)
    assert r.w == 280
    assert r.y == 48


# --- AX whitelist -----------------------------------------------------------


def test_ax_whitelist_blocks_press_inside_line():
    with pytest.raises(GuardError):
        ax_assert_allowed("ax_press", "LINE")


def test_ax_whitelist_blocks_any_action_inside_line_except_read():
    with pytest.raises(GuardError):
        ax_assert_allowed("click_menu_bar_clock", "LINE")


def test_ax_whitelist_allows_read_inside_line():
    ax_assert_allowed("read_attribute", "LINE")  # must not raise


def test_ax_whitelist_allows_clock_and_esc():
    ax_assert_allowed("click_menu_bar_clock", "SystemUIServer")
    ax_assert_allowed("press_escape", None)


def test_ax_whitelist_rejects_unknown_action():
    with pytest.raises(GuardError):
        ax_assert_allowed("type_text", "Finder")


def test_press_not_in_whitelist_at_all():
    assert "ax_press" not in ALLOWED_AX_ACTIONS
    assert "AXPress" not in ALLOWED_AX_ACTIONS


# --- static source scans (CI red lines) -------------------------------------


def _sources() -> list[Path]:
    return sorted(SRC.glob("*.py"))


def test_no_shell_true_anywhere():
    offenders = [p.name for p in _sources() if "shell=True" in p.read_text(encoding="utf-8")]
    assert offenders == [], f"shell=True found in: {offenders}"


def test_tests_never_touch_production_keychain():
    """A test once deleted the user's real API key by calling delete_key()
    with the default service. Tests may only use an isolated service."""
    tests_dir = Path(__file__).resolve().parent
    for p in sorted(tests_dir.glob("*.py")):
        if p.name == "test_guards.py":
            continue  # the guard itself mentions the API names
        src = p.read_text(encoding="utf-8")
        if "keychain" not in src:
            continue
        for line in src.splitlines():
            stripped = line.strip()
            if stripped.startswith(("#", '"""', '"', "#")) or stripped.startswith("*"):
                continue  # comments / docstrings
            if "delete_key(" in line or "store_key(" in line:
                assert "TEST_SERVICE" in line or "service=" in line or "def " in line, (
                    f"{p.name}: keychain mutation without TEST_SERVICE: {line.strip()}"
                )


def test_no_axpress_outside_guards():
    # real AX press invocations (guarded wrapper calls are fine)
    pattern = re.compile(r"AXUIElementPerformAction|kAXPressAction|performAction_")
    offenders = [
        p.name
        for p in _sources()
        if p.name != "guards.py" and pattern.search(p.read_text(encoding="utf-8"))
    ]
    # tests reference the strings conceptually but never invoke AX
    assert offenders == [], f"AX press references outside guards.py: {offenders}"


def test_no_network_imports_in_watcher():
    watcher = SRC / "watcher.py"
    if not watcher.exists():  # Phase 6; enforce once it exists
        return
    text = watcher.read_text(encoding="utf-8")
    for banned in (
        "import socket",
        "import urllib",
        "import http",
        "import requests",
        "from http",
        "import ssl",
        "aiohttp",
        "httpx",
    ):
        assert banned not in text, f"network import '{banned}' in watcher.py"


def test_subprocess_calls_use_list_argv():
    pattern = re.compile(r"subprocess\.\w+\(\s*[\"']")
    offenders = [p.name for p in _sources() if pattern.search(p.read_text(encoding="utf-8"))]
    assert offenders == [], f"subprocess called with a string command in: {offenders}"


def test_osascript_payloads_are_constants():
    guards_src = (SRC / "guards.py").read_text(encoding="utf-8")
    assert "OSASCRIPT_CLICK_CLOCK" in guards_src
    assert "OSASCRIPT_PRESS_ESC" in guards_src
    # AppleScript payload TEXT may only live in guards.py; other modules may
    # invoke the osascript binary but must pass guards constants, never
    # hand-built scripts (no f-strings/format/concat into -e payloads).
    payload_markers = ('tell application "System Events"', "key code")
    offenders = [
        p.name
        for p in _sources()
        if p.name != "guards.py"
        and any(m in p.read_text(encoding="utf-8") for m in payload_markers)
    ]
    assert offenders == [], f"AppleScript payload text outside guards.py: {offenders}"
    # an osascript -e payload must be a variable traced to guards (never a
    # quoted string literal outside guards.py)
    import re as _re

    for p in _sources():
        for line in p.read_text(encoding="utf-8").splitlines():
            if _re.search(r'"osascript",\s*"-e",\s*f?"', line):
                raise AssertionError(
                    f"string-literal osascript payload in {p.name}: {line.strip()}"
                )


# --- notification sanitizer (auto-watcher READ_NOW alerts) -------------------

def test_notify_sanitize_strips_breakout_characters():
    from linescreening.guards import notify_sanitize

    for evil in ['說" + (do shell script "rm -rf ~") + "', "反斜線\\結尾", "換行\n注入",
                 "$(curl evil)", "back`tick`", "半形'quote"]:
        cleaned = notify_sanitize(evil)
        for ch in '"\'\\`$()\n':
            assert ch not in cleaned, f"{ch!r} survived sanitize: {cleaned!r}"


def test_notify_sanitize_keeps_readable_text_and_caps_length():
    from linescreening.guards import NOTIFY_BODY_MAX, notify_sanitize

    kept = notify_sanitize("媽媽：爸爸摔倒送醫，請回電！Room 402")
    assert "爸爸摔倒送醫" in kept and "402" in kept
    assert len(notify_sanitize("長" * 500)) <= NOTIFY_BODY_MAX
    assert notify_sanitize("") == ""
