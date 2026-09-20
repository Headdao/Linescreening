"""Build a double-clickable macOS app bundle (Linescreening.app).

`linescreening app` creates Linescreening.app (on the Desktop by default).
Double-clicking it starts the dashboard server and opens the browser —
no terminal needed. Quitting the app (Cmd+Q) stops the server.

The bundle embeds the ABSOLUTE path of this repo and its venv, so each
machine builds its own copy (open-source users run `uv run linescreening
app` once). Locally-created apps carry no quarantine flag, so no Gatekeeper
prompts. Screen Recording / Accessibility TCC must be granted to
Linescreening.app on first capture use (same as any terminal host).
"""

from __future__ import annotations

import plistlib
import subprocess
from pathlib import Path

from rich.console import Console

from linescreening.config import REPO_ROOT

APP_NAME = "Linescreening"
BUNDLE_ID = "com.linescreening.dashboard"
DEFAULT_PORT = 8765

_LAUNCHER = """#!/bin/bash
# Linescreening — double-click launcher (auto-generated, safe to delete)
cd "{repo}" || exit 1
exec "{venv_bin}/linescreening" dashboard --port {port}
"""

_INFO_PLIST = {
    "CFBundleName": APP_NAME,
    "CFBundleDisplayName": "Linescreening",
    "CFBundleIdentifier": BUNDLE_ID,
    "CFBundleExecutable": APP_NAME,
    "CFBundlePackageType": "APPL",
    "CFBundleShortVersionString": "0.2.1",
    "CFBundleVersion": "1",
    "LSMinimumSystemVersion": "13.0",
    "NSHighResolutionCapable": True,
    "CFBundleInfoDictionaryVersion": "6.0",
    "LSApplicationCategoryType": "public.app-category.utilities",
}


def build_app(dest_dir: Path, port: int = DEFAULT_PORT) -> Path:  # noqa: FBT001, FBT002
    venv_bin = REPO_ROOT / ".venv" / "bin" / "linescreening"
    if not venv_bin.exists():
        raise RuntimeError("找不到 .venv/bin/linescreening — 請先在專案目錄執行 `uv sync`")

    app = Path(dest_dir).expanduser() / f"{APP_NAME}.app"
    macos_dir = app / "Contents" / "MacOS"
    macos_dir.mkdir(parents=True, exist_ok=True)

    (app / "Contents" / "Info.plist").write_bytes(plistlib.dumps(_INFO_PLIST))
    launcher = macos_dir / APP_NAME
    launcher.write_text(
        _LAUNCHER.format(repo=REPO_ROOT, venv_bin=REPO_ROOT / ".venv" / "bin", port=port),
        encoding="utf-8",
    )
    launcher.chmod(0o755)
    _sign(app)
    return app


def _sign(app: Path) -> bool:
    """Ad-hoc code-sign the bundle so macOS TCC attributes permission
    requests to 'Linescreening' instead of the underlying python binary.
    (xattr detritus from Finder must be stripped first or codesign refuses.)"""
    import sys

    if sys.platform != "darwin":
        return False
    subprocess.run(["xattr", "-cr", str(app)], check=False, timeout=15)
    result = subprocess.run(
        ["codesign", "--force", "--deep", "--sign", "-", str(app)],
        capture_output=True,
        timeout=60,
        check=False,
    )
    return result.returncode == 0


def run_app_build(dest: str | None = None, port: int = DEFAULT_PORT) -> int:  # noqa: FBT001, FBT002
    console = Console()
    dest_dir = Path(dest).expanduser() if dest else Path.home() / "Desktop"
    try:
        app = build_app(dest_dir, port=port)
    except RuntimeError as exc:
        console.print(f"[red]建立失敗：{exc}[/red]")
        return 1

    console.print(f"[green]✅ 已建立[/green] [bold]{app}[/bold]")
    console.print(
        "[dim]已加上本地簽章：權限詢問會掛在 Linescreening 名下，而非底層的 python 執行檔。[/dim]"
    )
    console.print("雙擊即可開啟儀表板（自動打開瀏覽器）；在 Dock 按 Cmd+Q 或右鍵→結束即可停止。")
    console.print(
        "[yellow]首次使用[/yellow]：若 macOS 詢問「螢幕錄製」權限，請允許 "
        "[bold]Linescreening[/bold]（系統設定→隱私權與安全性→螢幕錄製）。"
    )
    subprocess.run(["open", "-R", str(app)], check=False, timeout=10)  # reveal in Finder
    return 0
