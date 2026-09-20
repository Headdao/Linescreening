"""Security red lines — the architectural guarantees behind "never trigger 已讀".

Rules enforced here (and by tests/test_guards.py in CI):

1. Screen capture accepts only three named regions — never arbitrary rects:
     - "line_window": the LINE window rectangle
     - "nc_panel":    the Notification Center panel (right edge of a screen)
     - "banner_region": top-right banner corner (banner mode only)
2. Accessibility automation is whitelisted: reading attributes, clicking the
   menu-bar clock (to open Notification Center) and pressing Esc. An AXPress
   on any element inside the LINE app is refused.
3. osascript payloads are static module constants — no string building from
   runtime data.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

LINE_BUNDLE_ID: Final = "jp.naver.line.mac"
KEYCHAIN_SERVICE: Final = "com.linescreening"


class GuardError(RuntimeError):
    """A red-line rule was violated — the operation must not proceed."""


# ---------------------------------------------------------------------------
# 1. Bounded screen capture
# ---------------------------------------------------------------------------
CaptureKind = str  # literal: "line_window" | "nc_panel" | "banner_region"

ALLOWED_CAPTURE_KINDS: Final[frozenset[str]] = frozenset(
    {"line_window", "nc_panel", "banner_region"}
)


@dataclass(frozen=True)
class CaptureRect:
    """A validated capture region (points, top-left origin)."""

    kind: CaptureKind
    x: int
    y: int
    w: int
    h: int


def capture_rect(kind: CaptureKind, x: int, y: int, w: int, h: int) -> CaptureRect:
    if kind not in ALLOWED_CAPTURE_KINDS:
        raise GuardError(
            f"capture kind {kind!r} not allowed; use one of {sorted(ALLOWED_CAPTURE_KINDS)}"
        )
    if w <= 0 or h <= 0:
        raise GuardError("capture region must have positive size")
    if x < 0 or y < 0:
        raise GuardError("capture region must start at non-negative coordinates")
    # Safety cap: never allow a single capture bigger than 1/3 of a 6K screen
    # in both dimensions (LINE window / NC panel / banner corner are all far
    # smaller than this; a "capture everything" request cannot sneak through).
    if w > 2500 or h > 2000:
        raise GuardError("capture region too large — refusing to capture the whole screen")
    return CaptureRect(kind=kind, x=x, y=y, w=w, h=h)


def crop_to_kind(
    kind: CaptureKind, img_w: int, img_h: int, left_frac: float, top_frac: float = 0.0
) -> CaptureRect:
    """Compute a sub-rect of an already-captured allowed image (e.g. sidebar
    crop of the LINE window capture). Left fraction must stay sane."""
    if kind not in ALLOWED_CAPTURE_KINDS:
        raise GuardError(f"crop of kind {kind!r} not allowed")
    if not 0.0 < left_frac <= 1.0 or not 0.0 <= top_frac < 1.0:
        raise GuardError("crop fractions out of range")
    return CaptureRect(
        kind=kind,
        x=0,
        y=int(img_h * top_frac),
        w=int(img_w * left_frac),
        h=img_h,
    )


# ---------------------------------------------------------------------------
# 2. AX whitelist
# ---------------------------------------------------------------------------
ALLOWED_AX_ACTIONS: Final[frozenset[str]] = frozenset(
    {"read_attribute", "click_menu_bar_clock", "press_escape"}
)


def ax_assert_allowed(action: str, target_app: str | None = None) -> None:
    if action not in ALLOWED_AX_ACTIONS:
        raise GuardError(f"AX action {action!r} is not whitelisted")
    if target_app is not None and target_app == "LINE" and action != "read_attribute":
        raise GuardError(
            "AX actions other than read_attribute are forbidden inside the LINE app "
            "(would risk triggering read receipts)"
        )


# ---------------------------------------------------------------------------
# 3. Static osascript payloads (constants — never built from runtime data)
# ---------------------------------------------------------------------------
# Locale-independent: matches the clock by its AXIdentifier, tries both
# host processes (Tahoe: ControlCenter; older: SystemUIServer).
OSASCRIPT_CLICK_CLOCK: Final[str] = (
    'tell application "System Events"\n'
    '  repeat with procName in {"SystemUIServer", "ControlCenter"}\n'
    "    try\n"
    "      tell process procName\n"
    "        repeat with mb in menu bars\n"
    "          repeat with mbi in menu bar items of mb\n"
    "            try\n"
    '              if value of attribute "AXIdentifier" of mbi is '
    '"com.apple.menuextra.clock" then\n'
    "                click mbi\n"
    '                return "clicked:" & procName\n'
    "              end if\n"
    "            end try\n"
    "          end repeat\n"
    "        end repeat\n"
    "      end tell\n"
    "    end try\n"
    "  end repeat\n"
    "end tell\n"
    'return "notfound"'
)

OSASCRIPT_PRESS_ESC: Final[str] = 'tell application "System Events" to key code 53'
