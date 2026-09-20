"""Health checks — shared by `linescreening doctor` (Phase 2) and the setup
wizard (Phase 3). Every check is read-only and safe: nothing here clicks,
types, or opens anything.
"""

from __future__ import annotations

import ctypes
import os
import plistlib
import subprocess
from dataclasses import dataclass
from typing import Any

from linescreening.cgimage import image_size
from linescreening.guards import LINE_BUNDLE_ID

# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool | None  # None = optional / skipped / unknown
    detail: str = ""


def _ok(name: str, detail: str = "") -> CheckResult:
    return CheckResult(name, True, detail)


def _fail(name: str, detail: str) -> CheckResult:
    return CheckResult(name, False, detail)


def _optional(name: str, detail: str) -> CheckResult:
    return CheckResult(name, None, detail)


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------


def check_line_running() -> CheckResult:
    proc = subprocess.run(["pgrep", "-x", "LINE"], capture_output=True, timeout=10, check=False)
    if proc.returncode == 0:
        return _ok("LINE 執行中")
    return _fail("LINE 執行中", "找不到 LINE 程序，請先開啟 LINE")


def find_line_window() -> dict[str, Any] | None:
    """Return the on-screen LINE window dict (Quartz), or None.

    NOTE: kCGWindowOwnerName may be unavailable without Screen Recording
    permission on recent macOS — in that case windows appear with empty
    owner names and we cannot identify LINE.
    """
    try:
        from Quartz import (
            CGWindowListCopyWindowInfo,
            kCGNullWindowID,
            kCGWindowListExcludeDesktopElements,
            kCGWindowListOptionOnScreenOnly,
        )
    except ImportError:
        return None

    infos = CGWindowListCopyWindowInfo(
        kCGWindowListOptionOnScreenOnly | kCGWindowListExcludeDesktopElements,
        kCGNullWindowID,
    )
    if infos is None:
        return None
    for info in infos:
        owner = info.get("kCGWindowOwnerName") or ""
        if owner == "LINE":
            layer = info.get("kCGWindowLayer", 0)
            bounds = info.get("kCGWindowBounds") or {}
            if layer == 0 and bounds.get("Width", 0) > 200:
                return dict(info)
    return None


def check_line_window() -> CheckResult:
    win = find_line_window()
    if win is None:
        return _fail(
            "LINE 視窗可見", "找不到畫面上的 LINE 視窗（可能被最小化，或尚無螢幕錄製權限）"
        )
    bounds = win.get("kCGWindowBounds", {})
    return _ok(
        "LINE 視窗可見",
        f"位置 ({int(bounds.get('X', 0))},{int(bounds.get('Y', 0))}) "
        f"大小 {int(bounds.get('Width', 0))}x{int(bounds.get('Height', 0))}",
    )


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------


def check_screen_recording() -> CheckResult:
    """Try capturing the LINE window; without TCC permission the capture
    returns None (macOS refuses rather than returning a wallpaper image on
    recent versions when window-scoped)."""
    win = find_line_window()
    try:
        from Quartz import (
            CGRectNull,
            CGWindowListCreateImage,
            kCGWindowImageNominalResolution,
            kCGWindowListOptionIncludingWindow,
        )
    except ImportError:
        return _optional("螢幕錄製權限", "pyobjc Quartz 不可用（CI 環境？）")

    wid = (win or {}).get("kCGWindowNumber")
    if wid is None:
        return _fail("螢幕錄製權限", "無法驗證：找不到 LINE 視窗")

    img = CGWindowListCreateImage(
        CGRectNull, kCGWindowListOptionIncludingWindow, wid, kCGWindowImageNominalResolution
    )
    if img is None:
        return _fail(
            "螢幕錄製權限", "擷取 LINE 視窗失敗 — 請在 系統設定→隱私權與安全性→螢幕錄製 授權終端機"
        )
    return _ok("螢幕錄製權限", f"成功擷取 {image_size(img)[0]}x{image_size(img)[1]} 視窗影像")


def check_accessibility() -> CheckResult:
    """Optional (Notification Center dump)."""
    try:
        lib = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
        )
        lib.AXIsProcessTrusted.restype = ctypes.c_bool
        trusted = lib.AXIsProcessTrusted()
    except OSError:
        return _optional("輔助使用權限", "無法查詢（非 macOS？）")

    if trusted:
        return _ok("輔助使用權限", "可開啟通知中心（C 來源可用）")
    return _optional("輔助使用權限", "未授權 — 通知中心 dump 將自動略過（不影響側欄擷取）")


# ---------------------------------------------------------------------------
# Notifications (best-effort reading of com.apple.ncprefs)
# ---------------------------------------------------------------------------


def _ncprefs_line_entry() -> dict[str, Any] | None:
    try:
        proc = subprocess.run(
            ["defaults", "export", "com.apple.ncprefs", "-"],
            capture_output=True,
            timeout=10,
            check=False,
        )
        if proc.returncode != 0:
            return None
        xml = subprocess.run(
            ["plutil", "-convert", "xml1", "-o", "-", "--", "-"],
            input=proc.stdout,
            capture_output=True,
            timeout=10,
            check=False,
        )
        if xml.returncode != 0:
            return None
        data = plistlib.loads(xml.stdout)
    except Exception:  # noqa: BLE001 — best-effort by design
        return None
    for app in data.get("apps", []):
        if app.get("bundle-id") == LINE_BUNDLE_ID:
            return app
    return None


def check_notifications() -> CheckResult:
    """Best-effort. The ncprefs flags bitfield is undocumented and has changed
    across macOS versions, so we only report whether LINE has a notification
    config at all — the wizard (step 3) verifies behaviour with a real test
    message, which is the only reliable check."""
    entry = _ncprefs_line_entry()
    if entry is None:
        return _optional("LINE 通知設定", "無法讀取通知設定（ncprefs）— 精靈第 3 步會實測驗證")
    flags = entry.get("flags", 0)
    return _optional("LINE 通知設定", f"ncprefs 存在（flags={flags}）；細節由精靈實測確認")


# ---------------------------------------------------------------------------
# API key + Jev connectivity
# ---------------------------------------------------------------------------


def check_api_key() -> CheckResult:
    import sys

    if sys.platform == "darwin":
        try:
            from linescreening import keychain

            if keychain.has_key():
                return _ok("API key", "已存放於 Keychain（com.linescreening）")
        except Exception as exc:  # noqa: BLE001
            return _fail("API key", f"Keychain 查詢失敗：{exc}")
    if os.environ.get("TYPESAFE_API_KEY"):
        return _ok("API key", "由環境變數 TYPESAFE_API_KEY 提供（CI 模式）")
    return _fail("API key", "找不到 API key — 請執行 `linescreening setup`（存在 Keychain）")


def check_jev_api() -> CheckResult:
    """Live ping. Only runs when a key is available."""
    import sys

    key = None
    if sys.platform == "darwin":
        try:
            from linescreening import keychain as kc

            key = kc.load_key()
        except Exception:  # noqa: BLE001
            key = None
    key = key or os.environ.get("TYPESAFE_API_KEY")
    if not key:
        return _optional("Jev API 連線", "沒有 key，略過連線測試")

    try:
        from typesafe_sdk import TypeSafeClient

        client = TypeSafeClient(api_key=key)
        listing = client.models.list()
        ids = [m.name for m in listing.models]
        return _ok("Jev API 連線", f"可用模型：{', '.join(ids[:3])}")
    except Exception as exc:  # noqa: BLE001
        return _fail("Jev API 連線", f"呼叫失敗：{exc}")


# ---------------------------------------------------------------------------
# Watcher (banner mode only)
# ---------------------------------------------------------------------------


def check_watcher_installed() -> CheckResult:
    proc = subprocess.run(
        ["launchctl", "list"], capture_output=True, timeout=10, check=False, text=True
    )
    if proc.returncode != 0:
        return _optional("watcher 常駐", "launchctl 查詢失敗")
    if "com.linescreening.watcher" in proc.stdout:
        return _ok("watcher 常駐", "launchd agent 已載入（橫幅模式）")
    return _optional("watcher 常駐", "未安裝（安靜模式不需要；橫幅模式由精靈第 5 步安裝）")


ALL_CHECKS = [
    ("env", [check_line_running, check_line_window]),
    ("permissions", [check_screen_recording, check_accessibility]),
    ("notifications", [check_notifications]),
    ("api", [check_api_key, check_jev_api]),
    ("watcher", [check_watcher_installed]),
]


def run_all() -> list[CheckResult]:
    results: list[CheckResult] = []
    for _, checks in ALL_CHECKS:
        for check in checks:
            try:
                results.append(check())
            except Exception as exc:  # noqa: BLE001 — doctor never crashes
                results.append(_fail(check.__name__.replace("check_", ""), f"檢查發生錯誤：{exc}"))
    return results
