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


def _real_sidebar(cfg: Config, activate: bool = True) -> list[SidebarRow]:  # noqa: FBT001, FBT002
    from linescreening import capture
    from linescreening.cgimage import image_size
    from linescreening.ocr import recognize_cgimage
    from linescreening.parse import parse_sidebar

    img = capture.capture_sidebar(cfg, activate=activate)
    width = float(image_size(img)[0])
    items = recognize_cgimage(
        img,
        languages=cfg.ocr["recognition_languages"],
        min_confidence=float(cfg.ocr["min_confidence"]),
        pixel_scale=capture.pixel_scale(),
    )
    return parse_sidebar(items, width / capture.pixel_scale(), cfg.sidebar)


def _real_nc(cfg: Config) -> list[NotificationItem]:
    from linescreening import ncdump

    return ncdump.dump_once(cfg)


# ---------------------------------------------------------------------------
# Triage flow
# ---------------------------------------------------------------------------


def collect_triage(
    mock: bool = False,  # noqa: FBT001, FBT002
    offline: bool = False,  # noqa: FBT001, FBT002
    cfg: Config | None = None,
    sidebar_provider: SidebarProvider = _real_sidebar,
    nc_provider: NcProvider = _real_nc,
    silent: bool = False,  # noqa: FBT001, FBT002
) -> dict:
    """Run the full pipeline and return the JSON payload (shared by the
    terminal report, --json output, and the local dashboard).

    silent=True (watcher): never activate LINE to capture — skip rather
    than steal focus."""
    cfg = cfg or load_config()
    if silent and sidebar_provider is _real_sidebar:
        sidebar_provider = lambda c: _real_sidebar(c, activate=False)  # noqa: E731
    store = Store(cfg.db_path)
    store.purge_older_than(int(cfg.data["retention_days"]))

    warnings: list[str] = []  # blocking problems (sidebar capture, consent)
    notices: list[str] = []  # optional-source skips — informational, never scary
    sidebar_rows: list[SidebarRow] = []
    nc_items: list[NotificationItem] = []
    try:
        sidebar_rows = sidebar_provider(cfg)
    except Exception as exc:  # noqa: BLE001 — degrade, never crash the report
        warnings.append(f"側欄擷取失敗：{exc}")
    try:
        nc_items = nc_provider(cfg)
        store.set_meta("nc_last_ok", datetime.now(UTC).isoformat(timespec="seconds"))
    except Exception as exc:  # noqa: BLE001 — optional source; skip without alarming
        notices.append(
            f"通知中心來源未啟用（選配）——{exc.__class__.__name__}: {str(exc)[:70]}。"
            "想用的話：到儀表板「第一次使用」按「向系統要求授權」，"
            "並打開清單新出現項目的開關。"
        )

    # consent: no key consent -> offline unless mock
    if not offline and not mock and (store.get_meta("cloud_consent") == "denied"):
        offline = True
        warnings.append("未同意雲端判讀 — 自動切換 --offline（僅列未讀）")

    # merge sources into one state per chat
    nc_names = {n.chat_name for n in nc_items}
    sidebar_names = {r.chat_name for r in sidebar_rows}
    states: list[tuple[dict, bool]] = []  # (state, unread_flag)
    read_skipped = 0
    for row in sidebar_rows:
        if row.unread is None or row.unread <= 0:
            # the unread badge column is parsed for every sidebar row; no
            # badge = already read. The report is unread-only — a read chat
            # must never surface (let alone get judged or notified).
            read_skipped += 1
            continue
        st = state_from_sources(row, [n for n in nc_items if n.chat_name == row.chat_name])
        if st is not None:
            states.append((st, True))
    if read_skipped:
        notices.append(f"側欄有 {read_skipped} 個已讀聊天未列入報表。")
    for name in nc_names - sidebar_names:
        st = state_from_sources(None, [n for n in nc_items if n.chat_name == name])
        if st is not None:
            states.append((st, False))  # NC-only: may already be read

    if not states:
        store.record_triage(0)
        store.close()
        return {
            "ran_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "mode": "offline" if offline else ("mock" if mock else "live"),
            "warnings": warnings,
            "notices": notices,
            "chats": [],
        }

    # ask Jev
    triages: list[Triage] = []
    previews: dict[str, tuple[str, int | None]] = {}
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
        previews[name] = (st["chat"].get("latest_preview") or "", st["chat"].get("unread_count"))
        if offline:
            triages.append(Triage(name, Verdict.MAYBE, 0.0, ["未判讀（離線模式）"]))
            continue
        answers = client.ask(st, QUESTION_BATTERY)
        t = combine(name, answers, cfg)
        if not unread_flag and t.verdict is Verdict.READ_NOW:
            t.reasons.append("（此聊天側欄未顯示未讀，可能已讀）")
        triages.append(t)

    triages = sort_triages(triages)
    store.record_triage(len(triages))
    store.close()

    return {
        "ran_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "mode": "offline" if offline else ("mock" if mock else "live"),
        "warnings": warnings,
        "notices": notices,
        "chats": [
            {
                "name": t.chat_name,
                "verdict": t.verdict.value,
                "label": VERDICT_LABEL[t.verdict],
                "priority": t.priority,
                "reasons": t.reasons,
                "low_confidence": t.low_confidence,
                "confidence": t.detail.get("confidence"),
                "preview": previews.get(t.chat_name, ("", None))[0],
                "unread": previews.get(t.chat_name, ("", None))[1],
            }
            for t in triages
        ],
    }


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
    payload = collect_triage(
        mock=mock,
        offline=offline,
        cfg=cfg,
        sidebar_provider=sidebar_provider,
        nc_provider=nc_provider,
    )
    triages = [
        Triage(
            chat_name=c["name"],
            verdict=Verdict(c["verdict"]),
            priority=c["priority"],
            reasons=list(c["reasons"]),
            low_confidence=c["low_confidence"],
        )
        for c in payload["chats"]
    ]

    if not triages:
        console.print(Panel("目前沒有可見的未讀聊天 🎉", title="linescreening triage"))
        for w in payload["warnings"]:
            console.print(f"[yellow]⚠ {w}[/yellow]")
        for n in payload.get("notices", []):
            console.print(f"[dim]ℹ {n}[/dim]")
    elif json_output:
        print(json.dumps(payload, ensure_ascii=False, indent=2))  # noqa: T201 - clean stdout for --json
    else:
        _render(console, triages, payload["mode"] == "offline", payload["warnings"])
        for n in payload.get("notices", []):
            console.print(f"[dim]ℹ {n}[/dim]")
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
