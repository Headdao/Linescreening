"""`linescreening purge` — one command to remove everything the tool created:

sqlite data, Keychain entry, launchd agent (banner mode). Screen Recording /
Accessibility TCC grants can only be revoked by the user in System Settings;
the summary reminds them how.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from rich.console import Console

from linescreening.config import load_config
from linescreening.db import Store

LAUNCHD_LABEL = "com.linescreening.watcher"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"


def run_purge(confirm: bool = True) -> int:  # noqa: FBT001, FBT002
    console = Console()

    if confirm:
        console.print(
            "[bold red]將刪除：[/bold red] sqlite 資料、Keychain API key、launchd watcher"
        )
        answer = input("確定？（y/N）：").strip().lower()
        if answer != "y":
            console.print("已取消。")
            return 0

    # 1. sqlite data
    cfg = load_config()
    store = Store(cfg.db_path)
    store.purge_all()
    store.close()
    console.print("✅ 本機資料庫已清空")

    # 2. Keychain entry (macOS only; ignore silently elsewhere)
    try:
        from linescreening import keychain

        if keychain.delete_key():
            console.print("✅ Keychain API key 已刪除")
        else:
            console.print("➖ Keychain 沒有存放 key")
    except Exception:  # noqa: BLE001 — non-macOS or keychain locked
        console.print("➖ Keychain 略過（非 macOS 或無法存取）")

    # 3. launchd agent (banner mode)
    if PLIST_PATH.exists():
        subprocess.run(
            ["launchctl", "unload", str(PLIST_PATH)], capture_output=True, timeout=15, check=False
        )
        PLIST_PATH.unlink()
        console.print("✅ launchd watcher 已移除")
    else:
        console.print("➖ launchd watcher 未安裝（安靜模式）")

    console.print(
        "[dim]系統權限（螢幕錄製／輔助使用）請自行到 系統設定→隱私權與安全性 撤銷。[/dim]"
    )
    return 0
