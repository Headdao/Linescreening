# linescreening

> Triage unread LINE chats on macOS — without triggering read receipts (不已讀).

`linescreening` runs when **you** choose to engage. It reads unread message
previews from the LINE chat-list sidebar and Notification Center (never by
opening a chat), asks the [Jev decision model](https://docs.typesafe.ai) a
battery of atomic questions about each chat, and prints a ranked terminal
report: **READ_NOW / READ_SOON / CAN_SKIP / MAYBE**.

Core idea: replace *reactive, real-time interruptions* with *proactive,
batch triage*.

## Status

🚧 Under active development (Phase 1 of 9). Setup wizard, capture pipeline,
Jev decision model and report are landing phase by phase.

## Quick start (once released)

```bash
uv sync
uv run linescreening        # first run: guided setup wizard
uv run linescreening triage # later: triage unread chats
```

## How it works

1. **Capture A — sidebar.** Locate the LINE window, capture *only* that
   window, crop the chat list, run on-device OCR (Apple Vision, zh-Hant/
   zh-Hans/ja/en). Viewing the list never marks messages as read.
2. **Capture C — Notification Center.** With macOS notifications configured
   in *quiet mode* (no banners, no sound, previews “when unlocked”), every
   message preview accumulates in Notification Center. triage dumps it
   on demand — zero interruption, no daemon.
3. **Jev decision model.** One API call per unread chat, 8 atomic questions
   (Noul/Score/Choice primitives), combined in code with confidence gates.
   Low confidence → flagged as MAYBE, never hidden. The report always lists
   **all** unread chats.
4. **Report.** A `rich` terminal table grouped by verdict, with reasons and
   confidence, plus `--json` for scripting.

It never clicks inside LINE, never opens a chat, and in quiet mode runs no
background process. See [SECURITY.md](SECURITY.md) for the full threat model.

## Notifications: quiet mode (recommended)

System Settings → Notifications → LINE:

- 顯示位置: uncheck **桌面** (no banners), keep **通知中心**; lock screen off
- 播放通知的聲音: off
- 顯示預覽: **當解鎖時** (hidden on lock screen, readable by triage)
- LINE app → 設定 → 通知 → 顯示訊息內容: on

The setup wizard configures and live-verifies all of this.

## Limitations

See the “已知限制” section in the docs (to be finalised with v0.1.0).
Key ones: chats muted inside LINE produce no notifications; messages that
arrived while the Mac was asleep are only visible via the sidebar preview;
CJK triage accuracy is lower than English (Jev), so thresholds are
conservative and nothing is ever hidden.

## License

MIT — see [LICENSE](LICENSE).
