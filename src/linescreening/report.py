"""Triage orchestration + rich report + JSON output.

run_triage() merges sources A (sidebar) and C (Notification Center), asks
Jev one fan-out request per unread chat, and prints a grouped report.
ALL unread chats are always listed — verdicts rank and annotate, never hide.

Capture providers are injectable so tests (and CI) run the whole pipeline
against synthetic data without any screen access.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from linescreening.config import Config, load_config
from linescreening.db import Store
from linescreening.decision import (
    QUESTION_BATTERY,
    VERDICT_LABEL,
    Triage,
    Verdict,
    combine,
    sort_triages,
    state_from_sources,
)
from linescreening.jev import make_client
from linescreening.parse import NotificationItem, SidebarRow

# capture providers (patched in tests; real ones hit the screen)
SidebarProvider = Callable[[Config], list[SidebarRow]]
NcProvider = Callable[[Config], list[NotificationItem]]


def _real_sidebar(cfg: Config) -> list[SidebarRow]:
    from linescreening import capture
    from linescreening.cgimage import image_size
    from linescreening.ocr import recognize_cgimage
    from linescreening.parse import parse_sidebar

    img = capture.capture_sidebar(cfg)
    width = float(image_size(img)[0])
    items = recognize_cgimage(
        img,
        languages=cfg.ocr["recognition_languages"],
        min_confidence=float(cfg.ocr["min_confidence"]),
    )
    return parse_sidebar(items, width, cfg.sidebar)


def _real_nc(cfg: Config) -> list[NotificationItem]:
    from linescreening import ncdump

    return ncdump.dump_once(cfg)


# ---------------------------------------------------------------------------
# Triage flow
# ---------------------------------------------------------------------------


def run_triage(
    console: Console | None = None,
    mock: bool = False,  # noqa: FBT001, FBT002
    offline: bool = False,  # noqa: FBT001, FBT002
    json_output: bool = False,  # noqa: FBT001, FBT002
    cfg: Config | None = None,
    sidebar_provider: SidebarProvider = _real_sidebar,
    nc_provider: NcProvider = _real_nc,
) -> bool:
    console = console or Console()
    cfg = cfg or load_config()
    store = Store(cfg.db_path)
    store.purge_older_than(int(cfg.data["retention_days"]))

    warnings: list[str] = []
    sidebar_rows: list[SidebarRow] = []
    nc_items: list[NotificationItem] = []
    try:
        sidebar_rows = sidebar_provider(cfg)
    except Exception as exc:  # noqa: BLE001 — degrade, never crash the report
        warnings.append(f"側欄擷取失敗：{exc}")
    try:
        nc_items = nc_provider(cfg)
        store.set_meta("nc_last_ok", datetime.now(UTC).isoformat(timespec="seconds"))
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"通知中心擷取失敗：{exc}")

    # consent: no key consent -> offline unless mock
    if not offline and not mock and (store.get_meta("cloud_consent") == "denied"):
        offline = True
        warnings.append("未同意雲端判讀 — 自動切換 --offline（僅列未讀）")

    # merge sources into one state per chat
    nc_names = {n.chat_name for n in nc_items}
    states: list[tuple[dict, bool]] = []  # (state, unread_flag)
    for row in sidebar_rows:
        st = state_from_sources(row, [n for n in nc_items if n.chat_name == row.chat_name])
        if st is not None:
            states.append((st, True))
    for name in nc_names - {r.chat_name for r in sidebar_rows}:
        st = state_from_sources(None, [n for n in nc_items if n.chat_name == name])
        if st is not None:
            states.append((st, False))  # NC-only: may already be read

    if not states:
        console.print(Panel("目前沒有可見的未讀聊天 🎉", title="linescreening triage"))
        for w in warnings:
            console.print(f"[yellow]⚠ {w}[/yellow]")
        store.record_triage(0)
        store.close()
        return True

    # ask Jev
    triages: list[Triage] = []
    if offline or mock:
        client = make_client(mock=True)  # offline uses mock only to fill detail
    else:
        try:
            client = make_client(mock=False, model=cfg.jev["model"])
        except RuntimeError as exc:
            warnings.append(f"{exc} — 改用 --offline")
            offline = True
            client = make_client(mock=True)

    for st, unread_flag in states:
        name = st["chat"]["name"]
        if offline:
            triages.append(Triage(name, Verdict.MAYBE, 0.0, ["未判讀（離線模式）"]))
            continue
        answers = client.ask(st, QUESTION_BATTERY)
        t = combine(name, answers, cfg)
        if not unread_flag and t.verdict is Verdict.READ_NOW:
            t.reasons.append("（此聊天側欄未顯示未讀，可能已讀）")
        triages.append(t)

    triages = sort_triages(triages)

    if json_output:
        payload = {
            "ran_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "mode": "offline" if offline else ("mock" if mock else "live"),
            "warnings": warnings,
            "chats": [
                {
                    "name": t.chat_name,
                    "verdict": t.verdict.value,
                    "label": VERDICT_LABEL[t.verdict],
                    "priority": t.priority,
                    "reasons": t.reasons,
                    "low_confidence": t.low_confidence,
                    "confidence": t.detail.get("confidence"),
                }
                for t in triages
            ],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))  # noqa: T201 - clean stdout for --json
    else:
        _render(console, triages, offline, warnings)

    store.record_triage(len(triages))
    store.close()
    return True


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

_VERDICT_STYLE = {
    Verdict.READ_NOW: ("red", "🔴"),
    Verdict.MAYBE: ("yellow", "🟡"),
    Verdict.READ_SOON: ("cyan", "🔵"),
    Verdict.CAN_SKIP: ("dim", "⚪"),
}


def _render(console: Console, triages: list[Triage], offline: bool, warnings: list[str]) -> None:  # noqa: FBT001
    mode = "離線（未判讀）" if offline else "Jev 判讀"
    table = Table(title=f"LINE 未讀分級 — {mode}", show_lines=False)
    table.add_column("", width=2)
    table.add_column("聊天", style="bold")
    table.add_column("判定")
    table.add_column("原因／訊號", overflow="fold")

    for t in triages:
        style, icon = _VERDICT_STYLE[t.verdict]
        label = VERDICT_LABEL[t.verdict]
        if t.low_confidence:
            label += "（低信心）"
        reasons = "；".join(t.reasons) or "—"
        table.add_row(icon, t.chat_name, f"[{style}]{label}[/{style}]", reasons)
    console.print(table)
    for w in warnings:
        console.print(f"[yellow]⚠ {w}[/yellow]")
    console.print(
        "[dim]排序：🔴 值得讀 → 🟡 不確定 → 🔵 可稍後 → ⚪ 可略過；所有未讀皆列出，不隱藏。[/dim]"
    )
