"""Calibration: run the question battery against the REAL Jev API with a
matrix of synthetic chat scenarios, and check verdicts match expectations.

Privacy: scenarios below are synthetic (no real messages). This is the only
place besides triage that talks to the network — run with:
    uv run python scripts/calibrate.py          (uses Keychain / env key)
    uv run python scripts/calibrate.py --mock   (offline sanity only)

NOTE: --mock uses the keyword MockJevClient — verdict mismatches are
EXPECTED there; the scenario matrix is tuned against the real model.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rich.console import Console  # noqa: E402
from rich.table import Table  # noqa: E402

from linescreening.config import load_config  # noqa: E402
from linescreening.decision import (  # noqa: E402
    QUESTION_BATTERY,
    Verdict,
    build_state,
    combine,
)
from linescreening.jev import make_client  # noqa: E402

# (name, unread, preview, extra previews, expected verdict, why)
SCENARIOS = [
    ("媽媽", 1, "今晚要回來吃飯嗎？", [], Verdict.READ_NOW, "家庭＋時間敏感＋期待回覆"),
    ("老闆", 2, "明天早上九點的會議改到十點，記得提前到", [], Verdict.READ_NOW, "上級＋行程變動"),
    ("托育老師", 1, "小孩有點發燒，方便現在來接嗎？", [], Verdict.READ_NOW, "緊急照護"),
    (
        "同事 Kevin",
        1,
        "這份簡報你看完跟我說一聲",
        ["簡報已更新到共享資料夾"],
        Verdict.READ_SOON,
        "有任務但非今日",
    ),
    ("大學同學", 1, "下週同學會要參加嗎？統計人數中", [], Verdict.READ_SOON, "計畫型、可稍後回"),
    (
        "家庭群組",
        12,
        "爸爸：哈哈這太好笑了",
        ["媽媽：貼圖", "爸爸：貼圖"],
        Verdict.CAN_SKIP,
        "群組閒聊",
    ),
    ("LINE 官方帳號", 1, "限時優惠！全站商品 8 折只到今天", [], Verdict.CAN_SKIP, "官方推播"),
    ("朋友", 1, "哈哈哈哈", [], Verdict.CAN_SKIP, "純閒聊"),
    ("朋友", 1, "[貼圖]", [], Verdict.CAN_SKIP, "貼圖"),
    ("社團群組", 30, "王大明：有人知道哪邊可以修車嗎？", [], Verdict.MAYBE, "群組無關訊息，訊號弱"),
    ("銀行通知", 1, "您的刷卡消費 3,500 元已核准", [], Verdict.MAYBE, "重要但非對話"),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mock", action="store_true", help="offline run (MockJevClient)")
    args = parser.parse_args()

    console = Console()
    cfg = load_config()
    client = make_client(mock=args.mock, model=cfg.jev["model"])

    table = Table(title=f"Jev calibration — {'MOCK' if args.mock else 'REAL API'}")
    table.add_column("聊天", style="bold")
    table.add_column("期望", justify="center")
    table.add_column("實際", justify="center")
    table.add_column("priority", justify="right")
    table.add_column("conf", justify="right")
    table.add_column("說明", overflow="fold")

    hits = 0
    for name, unread, preview, extras, expected, why in SCENARIOS:
        state = build_state(name, unread, preview, extras)
        answers = client.ask(state, QUESTION_BATTERY)
        t = combine(name, answers, cfg)
        ok = t.verdict == expected
        hits += ok
        icon = "✅" if ok else "❌"
        table.add_row(
            name,
            f"{icon} {expected.value}",
            t.verdict.value,
            f"{t.priority:.2f}",
            f"{t.detail['confidence']:.2f}",
            why + ("" if ok else f"  ← MISMATCH: {'；'.join(t.reasons)}"),
        )
    console.print(table)
    console.print(f"[bold]{hits}/{len(SCENARIOS)} 符合期望[/bold]")
    if args.mock:
        console.print("[dim]（mock 模式：關鍵字模擬，判定偏差屬預期，僅供管線驗證）[/dim]")
        return 0
    return 0 if hits >= len(SCENARIOS) - 2 else 1


if __name__ == "__main__":
    sys.exit(main())
