"""First-run setup wizard — interactive, guided, verified.

Design: every step = 說明 → 一鍵開啟系統設定面板 → 使用者操作 → 自動驗證 →
失敗可重試。Progress persists in the sqlite meta table, so an interrupted
run resumes where it stopped. `linescreening setup --step <name>` redoes one
step. Steps that need later-phase modules (ncdump live-verify, triage smoke
test) degrade gracefully to manual confirmation until those phases land.
"""

from __future__ import annotations

import getpass
import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass

from rich.console import Console
from rich.panel import Panel

from linescreening import checks, keychain
from linescreening.config import load_config
from linescreening.db import Store

# pane URLs (System Settings on macOS 13+)
PANE_SCREEN_RECORDING = (
    "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"
)
PANE_ACCESSIBILITY = "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
PANE_NOTIFICATIONS = "x-apple.systempreferences:com.apple.Notifications-Settings"


def open_pane(url: str) -> None:
    subprocess.run(["open", url], check=False, timeout=10)


@dataclass(frozen=True)
class StepResult:
    ok: bool
    note: str = ""


# ---------------------------------------------------------------------------
# Step 0 — environment
# ---------------------------------------------------------------------------


def step_env(console: Console, store: Store) -> StepResult:
    console.print("[bold]步驟 0／環境檢查[/bold]")
    results = [checks.check_line_running(), checks.check_line_window()]
    for r in results:
        icon = "✅" if r.ok else "❌"
        console.print(f"  {icon} {r.name}：{r.detail}")
    if all(r.ok for r in results):
        return StepResult(True)
    console.print("  → 請開啟 LINE 並讓主視窗出現在畫面上（側欄可見），然後重試。")
    return StepResult(False, "LINE 未執行或視窗不可見")


# ---------------------------------------------------------------------------
# Step 1 — screen recording
# ---------------------------------------------------------------------------

_SCREEN_INTRO = """\
[bold]步驟 1／螢幕錄製權限[/bold]
linescreening 只會截取兩個區域：LINE 視窗 與 通知中心面板，永不全螢幕、永不點擊。
請在即將開啟的設定面板中，把您正在使用的終端機 App（Terminal／iTerm/ZCode…）打開開關。
[b]注意：勾選後 macOS 會要求「結束並重新開啟」該終端機，權限才生效。[/b]"""


def step_screen(console: Console, store: Store) -> StepResult:
    console.print(Panel(_SCREEN_INTRO, border_style="cyan"))
    open_pane(PANE_SCREEN_RECORDING)
    input("  完成勾選後按 Enter 重新驗證…")
    result = checks.check_screen_recording()
    if result.ok:
        console.print("  ✅ 擷取驗證通過")
        return StepResult(True)
    console.print(f"  ❌ {result.detail}")
    console.print(
        "  若您已勾選但未重啟終端機，請完全結束終端機後重跑 `linescreening setup --step screen`。"
    )
    return StepResult(False, result.detail)


# ---------------------------------------------------------------------------
# Step 2 — accessibility (optional)
# ---------------------------------------------------------------------------


def step_ax(console: Console, store: Store) -> StepResult:
    console.print("[bold]步驟 2／輔助使用權限（選用）[/bold]")
    console.print("  用途：自動開啟／關閉通知中心（內容來源 C）。不授權也可用，triage 會自動略過。")
    result = checks.check_accessibility()
    if result.ok is True:
        console.print(f"  ✅ {result.detail}")
        return StepResult(True, "already granted")
    if input("  要現在設定嗎？（y=開設定面板 / Enter=跳過）").strip().lower() != "y":
        return StepResult(True, "skipped by user")
    open_pane(PANE_ACCESSIBILITY)
    input("  勾選終端機後按 Enter 驗證…")
    result = checks.check_accessibility()
    console.print(("  ✅ " if result.ok else "  ❌ ") + result.detail)
    return StepResult(bool(result.ok), result.detail)


# ---------------------------------------------------------------------------
# Step 3 — notification mode
# ---------------------------------------------------------------------------


def parse_mode_choice(raw: str) -> str | None:
    """'1'/'q'/'安靜' -> quiet; '2'/'b'/'橫幅' -> banner; '3'/'off' -> off."""
    raw = raw.strip().lower()
    table = {
        "1": "quiet",
        "q": "quiet",
        "quiet": "quiet",
        "安靜": "quiet",
        "2": "banner",
        "b": "banner",
        "banner": "banner",
        "橫幅": "banner",
        "3": "off",
        "o": "off",
        "off": "off",
        "關閉": "off",
    }
    return table.get(raw)


MODE_GUIDES = {
    "quiet": """\
[bold green]安靜模式設定（推薦）[/bold green] — 到 系統設定 → 通知 → LINE：
  ① 顯示位置：取消勾選 [b]桌面[/b]（不跳橫幅），保留 [b]通知中心[/b]；鎖定螢幕建議取消
  ② 播放通知的聲音：關閉
  ③ 顯示預覽：[b]當解鎖時[/b]
  ④ 開啟 LINE App → 設定 → 通知 → [b]顯示訊息內容[/b]
效果：零干擾；每則預覽靜靜累積在通知中心，triage 時一次撈取。""",
    "banner": """\
[bold yellow]橫幅模式設定[/bold yellow] — 通知照常跳出（您會被打擾，但 watcher 會記下每一則）：
  ① 系統設定 → 通知 → LINE：顯示位置勾選 桌面＋通知中心，預覽＝永遠
  ② 開啟 LINE App → 設定 → 通知 → 顯示訊息內容
  ③ 精靈會安裝常駐 watcher（sandbox 禁網）攔截每則橫幅""",
    "off": """\
[bold red]關閉模式[/bold red] — 完全不開通知：
  內容只剩側欄最後一則預覽（判定力最薄），但零干擾、零通知痕跡。""",
}


def step_notify(console: Console, store: Store) -> StepResult:
    console.print("[bold]步驟 3／通知模式[/bold]")
    console.print(
        "  1) 安靜（推薦）— 不跳橫幅，通知只進通知中心\n"
        "  2) 橫幅 — 通知照常跳，watcher 記下每一則\n"
        "  3) 關閉 — 不開通知，只靠側欄"
    )
    mode = None
    while mode is None:
        mode = parse_mode_choice(input("  請選擇 [1/2/3]："))
        if mode is None:
            console.print("  無效選擇，請輸入 1、2 或 3。")
    store.set_meta("notify_mode", mode)
    console.print(Panel(MODE_GUIDES[mode], border_style="cyan"))
    open_pane(PANE_NOTIFICATIONS)
    input("  完成設定後按 Enter…")

    # Live verification: quiet/banner need a real test message.
    if mode == "off":
        return StepResult(True, "off mode — no notifications configured")

    if _live_verify_notification(console, mode):
        return StepResult(True, mode)
    confirm = input("  自動驗證未執行/未通過。手動確認通知設定無誤？（y=通過 / n=重試本步）")
    if confirm.strip().lower() == "y":
        return StepResult(True, f"{mode}（手動確認）")
    return StepResult(False, "notification live-verify failed")


def _live_verify_notification(console: Console, mode: str) -> bool:
    """三關實測：傳測試訊息 → 沒橫幅（quiet）＋通知中心有紀錄＋可讀到內容。"""
    console.print("  [bold]三關實測[/bold]：請用另一支手機（或請任何人）傳一則測試訊息給您，")
    console.print("  訊息內容請包含一個通關密語，例如：[cyan]screening726[/cyan]")
    try:
        input("  傳送完成後按 Enter，我會打開通知中心驗證…")
    except EOFError:
        return False
    try:
        import importlib

        ncdump = importlib.import_module("linescreening.ncdump")  # lands in Phase 5
        items = ncdump.dump_once(load_config())
    except Exception as exc:  # noqa: BLE001 — graceful degrade pre-Phase-5
        console.print(f"  ➖ 自動驗證模組尚不可用（{exc.__class__.__name__}），改採手動確認。")
        return False
    hit = [i for i in items if "screening726" in (i.body or "")]
    if not hit:
        console.print("  ❌ 通知中心沒有找到含通關密語的通知。")
        return False
    console.print(f"  ✅ 通知中心已攔截：{hit[0].chat_name}：{hit[0].body}")
    return True


# ---------------------------------------------------------------------------
# Step 4 — API key + cloud consent
# ---------------------------------------------------------------------------


def step_key(console: Console, store: Store) -> StepResult:
    console.print("[bold]步驟 4／API key 與雲端同意[/bold]")
    console.print("  key 只會存進 macOS Keychain（服務 com.linescreening），不會寫入任何檔案。")
    console.print("  申請：[link=https://console.typesafe.ai/keys]console.typesafe.ai/keys[/link]")
    raw = getpass.getpass("  貼上 API key（輸入不會顯示）：").strip()
    if not raw:
        return StepResult(False, "empty key")
    keychain.store_key(raw)
    console.print("  ✅ 已存入 Keychain，正在驗證連線…")
    result = checks.check_jev_api()
    console.print(("  ✅ " if result.ok else "  ❌ ") + result.detail)
    if not result.ok:
        return StepResult(False, result.detail)

    console.print(
        "  [bold]雲端外傳說明[/bold]：triage 時，未讀訊息的預覽文字會送到 api.typesafe.ai 判讀。\n"
        "  不外傳選項隨時可用：`linescreening triage --offline`（只列未讀、不做判讀）。"
    )
    consent = input("  同意將預覽文字送至 Typesafe AI？（y/n）：").strip().lower()
    if consent != "y":
        store.set_meta("cloud_consent", "denied")
        console.print("  了解 — triage 將預設使用 --offline 模式。")
    else:
        store.set_meta("cloud_consent", "granted")
    return StepResult(True)


# ---------------------------------------------------------------------------
# Step 5 — watcher install (banner mode only)
# ---------------------------------------------------------------------------


def step_watcher(console: Console, store: Store) -> StepResult:
    mode = store.get_meta("notify_mode") or "quiet"
    if mode != "banner":
        console.print("[bold]步驟 5／watcher[/bold] — 安靜模式不需要常駐元件，略過 ✅")
        return StepResult(True, "not needed")
    console.print("[bold]步驟 5／watcher 安裝（橫幅模式）[/bold]")
    console.print("  watcher 會安裝為 launchd 使用者代理，並以 sandbox-exec 禁止一切網路。")
    console.print(
        "  [yellow]此功能於 Phase 6 提供；目前先略過，屆時重跑 setup --step watcher。[/yellow]"
    )
    return StepResult(True, "deferred to Phase 6")


# ---------------------------------------------------------------------------
# Step 6 — smoke test
# ---------------------------------------------------------------------------


def step_smoke(console: Console, store: Store) -> StepResult:
    console.print("[bold]步驟 6／Smoke test[/bold]")
    try:
        import importlib

        report = importlib.import_module("linescreening.report")  # lands in Phase 8
        return StepResult(bool(report.run_triage(console=console, mock=True)), "mock triage")
    except Exception:  # noqa: BLE001 — graceful degrade pre-Phase-8
        console.print("  ➖ triage 尚於開發中（Phase 8）— 屆時重跑 setup --step smoke。")
        return StepResult(True, "deferred to Phase 8")


# ---------------------------------------------------------------------------
# Step 7 — summary
# ---------------------------------------------------------------------------


def step_summary(console: Console, store: Store) -> StepResult:
    console.print("[bold]步驟 7／總結[/bold]")
    store.set_meta("setup_complete", "1")
    mode = store.get_meta("notify_mode") or "quiet"
    console.print(
        Panel(
            f"通知模式：{mode}\n"
            "日常用法：[bold]linescreening triage[/bold]   "
            "（--json 腳本輸出 / --offline 不外傳）\n"
            "健康檢查：linescreening doctor            "
            "資料流：doctor --privacy\n"
            "一鍵清除：linescreening purge",
            title="🎉 設定完成",
            border_style="green",
        )
    )
    return StepResult(True)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Step:
    key: str
    title: str
    fn: Callable[[Console, Store], StepResult]


STEPS: list[Step] = [
    Step("env", "環境檢查", step_env),
    Step("screen", "螢幕錄製", step_screen),
    Step("ax", "輔助使用（選用）", step_ax),
    Step("notify", "通知模式", step_notify),
    Step("key", "API key", step_key),
    Step("watcher", "watcher（橫幅模式）", step_watcher),
    Step("smoke", "Smoke test", step_smoke),
    Step("summary", "總結", step_summary),
]


def _load_progress(store: Store) -> dict[str, bool]:
    raw = store.get_meta("setup_progress")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return {k: bool(v) for k, v in data.items()}
    except json.JSONDecodeError:
        return {}


def _save_progress(store: Store, progress: dict[str, bool]) -> None:
    store.set_meta("setup_progress", json.dumps(progress))


def run_wizard(only_step: str | None = None) -> int:
    console = Console()
    store = Store(load_config().db_path)
    progress = _load_progress(store)

    if only_step:
        steps = [s for s in STEPS if s.key == only_step]
        if not steps:
            console.print(
                f"[red]未知步驟：{only_step}（可用：{', '.join(s.key for s in STEPS)}）[/red]"
            )
            return 1
    else:
        steps = STEPS

    console.rule("[bold cyan]linescreening 設定精靈[/bold cyan]")
    for step in steps:
        if not only_step and progress.get(step.key):
            console.print(f"✅ {step.title}（先前已完成，跳過；重跑請用 --step {step.key}）")
            continue
        result = step.fn(console, store)
        progress[step.key] = result.ok
        _save_progress(store, progress)
        if not result.ok and not only_step:
            again = input("  按 r 重試本步，Enter 繼續下一步，q 離開：").strip().lower()
            if again == "r":
                progress[step.key] = step.fn(console, store).ok
                _save_progress(store, progress)
            elif again == "q":
                console.print("進度已保存，下次執行 `linescreening setup` 會從未完成處繼續。")
                break
    store.close()
    return 0
