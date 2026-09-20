"""Build a double-clickable macOS app bundle (Linescreening.app).

`linescreening app` creates Linescreening.app (on the Desktop by default).
Double-clicking it starts the dashboard server and opens the browser —
no terminal needed. Quitting the app (Cmd+Q) stops the server.

TCC attribution: a copy of the venv's python binary lives INSIDE the
bundle (Contents/MacOS/linescreening-bin) and is what actually executes,
so macOS attributes Screen Recording / Accessibility prompts to
"Linescreening" itself — not to Homebrew's python (the failure mode when
exec'ing the venv interpreter directly). The copied binary links Python.framework
by absolute path, so it keeps working from inside the bundle; venv packages
are supplied via PYTHONPATH.

The bundle embeds the ABSOLUTE paths of this repo, so each machine builds
its own copy (open-source users run `uv run linescreening app` once).
Locally-created apps carry no quarantine flag, so no Gatekeeper prompts.
"""

from __future__ import annotations

import plistlib
import shutil
import subprocess
from pathlib import Path

from rich.console import Console

from linescreening.config import REPO_ROOT

APP_NAME = "Linescreening"
BUNDLE_ID = "com.linescreening.dashboard"
DEFAULT_PORT = 8765

_LAUNCHER = """#!/bin/bash
# Linescreening — double-click launcher (auto-generated, safe to delete)
REPO="@REPO@"
if [ ! -d "$REPO/src/linescreening" ]; then
  MSG="找不到專案資料夾：$REPO\\nLinescreening 需要它才能執行；"
  MSG="$MSG\\n若已搬移或刪除，請重新執行 uv run linescreening app 產生 App。"
  osascript -e "display dialog \"$MSG\" with title \"Linescreening\" "
    -e "buttons {\"好\"} default button \"好\" with icon caution" >/dev/null 2>&1
    >/dev/null 2>&1
  exit 1
fi
SITE="$(echo "$REPO"/.venv/lib/python3*/site-packages)"
export PYTHONPATH="$REPO/src:$SITE${PYTHONPATH:+:$PYTHONPATH}"
cd "$REPO" || exit 1
exec "$(dirname "$0")/linescreening-bin" -m linescreening.cli dashboard --port @PORT@
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
    venv_python = REPO_ROOT / ".venv" / "bin" / "python3.13"
    if not venv_python.exists():
        raise RuntimeError("找不到 .venv — 請先在專案目錄執行 `uv sync`")

    app = Path(dest_dir).expanduser() / f"{APP_NAME}.app"
    macos_dir = app / "Contents" / "MacOS"
    macos_dir.mkdir(parents=True, exist_ok=True)

    (app / "Contents" / "Info.plist").write_bytes(plistlib.dumps(_INFO_PLIST))

    # Embed the interpreter: the process making TCC-relevant calls must run
    # a binary INSIDE the (signed) bundle for attribution to stick to it.
    real_python = venv_python.resolve()
    embedded = macos_dir / "linescreening-bin"
    shutil.copy2(real_python, embedded)
    embedded.chmod(0o755)

    launcher = macos_dir / APP_NAME
    launcher.write_text(
        _LAUNCHER.replace("@REPO@", str(REPO_ROOT)).replace("@PORT@", str(port)),
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
    # Default to /Applications: an iCloud-synced Desktop can materialize the
    # bundle lazily and break double-click launches right after a rebuild.
    dest_dir = Path(dest).expanduser() if dest else Path("/Applications")
    try:
        app = build_app(dest_dir, port=port)
    except RuntimeError as exc:
        console.print(f"[red]建立失敗：{exc}[/red]")
        return 1
    except OSError:
        dest_dir = Path.home() / "Desktop"
        console.print(
            "[yellow]/Applications 無法寫入，改放桌面"
            "（若桌面有 iCloud 同步，建議手動搬進 /Applications）[/yellow]"
        )
        app = build_app(dest_dir, port=port)

    console.print(f"[green]✅ 已建立[/green] [bold]{app}[/bold]")
    console.print(
        "[dim]直譯器已內嵌＋本地簽章：擷取權限會掛在 [bold]Linescreening[/bold] 名下，"
        "不會再問 python。[/dim]"
    )
    console.print("雙擊即可開啟儀表板（自動打開瀏覽器）；在 Dock 按 Cmd+Q 或右鍵→結束即可停止。")
    console.print(
        "[yellow]首次使用[/yellow]：macOS 詢問「螢幕錄製」時請允許 "
        "[bold]Linescreening[/bold]，然後結束並重開 App（權限在啟動時載入）。"
    )
    subprocess.run(["open", "-R", str(app)], check=False, timeout=10)  # reveal in Finder
    return 0
