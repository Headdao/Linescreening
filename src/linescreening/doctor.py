"""`linescreening doctor` — non-interactive health report.

With --privacy: a plain-language disclosure of everything the tool sees,
stores, and transmits (SECURITY.md in terminal form).
"""

from __future__ import annotations

import sys

from rich.console import Console
from rich.table import Table

from linescreening.checks import run_all
from linescreening.config import load_config

_ICON = {True: "[green]✅[/green]", False: "[red]❌[/red]", None: "[yellow]➖[/yellow]"}


def _privacy_report(console: Console) -> None:
    cfg = load_config()
    console.rule("[bold]資料流揭露 (privacy)[/bold]")
    lines = [
        ("看見（像素）", "僅限：LINE 視窗、通知中心面板（橫幅模式再加右上角）。永不整螢幕。"),
        (
            "儲存（本機）",
            f"~/.linescreening/linescreening.sqlite — 僅聊天名與預覽文字；"
            f"保留 {cfg.data['retention_days']} 天後自動刪除；`linescreening purge` 一鍵全刪。",
        ),
        (
            "離開這台機器",
            "只有「訊息預覽文字」會送到 api.typesafe.ai（Jev 判讀），且需您在精靈中同意；"
            "`triage --offline` 完全不外傳。無遙測、無崩潰回報、無自動更新。",
        ),
        ("系統權限", "螢幕錄製（擷圖用）、輔助使用（選用：開通知中心）。皆可隨時在系統設定撤銷。"),
        (
            "絕不做的事",
            "永不點擊 LINE 聊天列（不觸發已讀）；永不點擊 LINE 內任何元素；"
            "watcher（橫幅模式）永不連網。",
        ),
    ]
    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column(style="bold cyan", no_wrap=True)
    table.add_column()
    for label, text in lines:
        table.add_row(label, text)
    console.print(table)


def run_doctor(privacy: bool = False) -> int:  # noqa: FBT001, FBT002
    console = Console()
    results = run_all()

    table = Table(title="linescreening 健康檢查", show_lines=False)
    table.add_column("狀態", justify="center", width=4)
    table.add_column("檢查項目", style="bold")
    table.add_column("說明", overflow="fold")
    for r in results:
        table.add_row(_ICON[r.ok], r.name, r.detail)
    console.print(table)

    failed = [r for r in results if r.ok is False]
    if privacy:
        _privacy_report(console)

    if failed:
        console.print(
            f"[red]{len(failed)} 項未通過[/red] — 執行 [bold]linescreening setup[/bold] 逐項修復。"
        )
        return 1
    console.print("[green]全部必要項目通過[/green] 🎉")
    return 0


if __name__ == "__main__":
    sys.exit(run_doctor())
