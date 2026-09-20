# linescreening

> Triage unread LINE chats on macOS — without triggering read receipts (不已讀).

`linescreening` runs when **you** choose to engage. It reads unread message
previews from the LINE chat-list sidebar (and, optionally, Notification
Center), asks the [Jev decision model](https://docs.typesafe.ai) a battery
of atomic questions about each chat, and prints a ranked terminal report:
**READ_NOW / READ_SOON / CAN_SKIP / MAYBE** — every unread chat is always
listed, verdicts rank and annotate but never hide.

Core idea: replace *reactive, real-time interruptions* with *proactive,
batch triage*. Keep notifications off, decide when to look, and when you
look, it's already sorted.

```
🔴 周鳳珠            值得讀（現在）   時間敏感（urgency 1.7/2）；期待回覆（0.64）且重要度高
🟡 AICoach講師共學營  不確定（低信心） 綜合優先度 0.20（訊號不明確）
⚪ Microsoft Outlook 可略過           官方/大量發送訊號強（0.86）
```

## How it works

1. **Capture A — sidebar (primary).** Locate the LINE window (across all
   Spaces; briefly focuses LINE if parked on another desktop and restores
   your previous app — no input is ever sent into LINE), capture *only*
   that window, run on-device OCR (Apple Vision, zh-Hant/zh-Hans/en), and
   parse chat rows: name, last-message preview (wrapped lines folded),
   timestamp, unread badge (read from the avatar column), VOOM/ads filtered.
2. **Capture C — Notification Center (optional).** If you let LINE deliver
   notifications quietly (no banners, no sound — they accumulate in
   Notification Center), triage also harvests per-message previews from
   the NC panel. Users who keep notifications hidden simply rely on A.
3. **Jev decision model.** One fan-out request per unread chat — 5 Nouls
   (`expects_reply`, `time_sensitive`, `asks_action`, `automated_broadcast`,
   `casual_social`) + a 4-level `importance` Score + a 3-level `urgency`
   Score + a 7-option `message_kind` Choice — combined in code with
   normalised weights, thresholds and a confidence gate (CJK-calibrated at
   0.35; low-confidence soft verdicts become MAYBE, READ_NOW is never
   downgraded). All weights/thresholds live in `config.yaml`.
4. **Report.** A `rich` terminal table grouped 🔴→🟡→🔵→⚪ with reasons and
   confidence; `--json` for scripting; `--offline` lists without any
   network call.

Calibration: `scripts/calibrate.py` runs an 11-scenario synthetic matrix
against the real API (11/11 at time of release).

## Install & setup

Requires macOS 13+, Python 3.11+, [uv](https://docs.astral.sh/uv/), the
LINE desktop app, and a Typesafe AI API key
([console.typesafe.ai/keys](https://console.typesafe.ai/keys)).

```bash
uv sync
uv run linescreening setup   # guided wizard: permissions, notifications, key
uv run linescreening app     # build Linescreening.app on the Desktop
```

**之後日常使用不需要終端機**：雙擊桌面上的 **Linescreening.app** 即可打開
儀表板（自動開瀏覽器）；在 Dock 上按 Cmd+Q 或右鍵→結束即可停止。首次用
App 擷取時，macOS 會要求把「螢幕錄製」權限授給 Linescreening.app。

The wizard verifies every step live (real capture probe, real test
message, real API ping). The API key is stored in the macOS **Keychain**
via clipboard (terminal pastes can corrupt keys) — never in a file.

## Daily use

```bash
uv run linescreening triage            # capture → Jev → ranked report
uv run linescreening triage --offline  # no network: list unreads only
uv run linescreening triage --json     # machine-readable
uv run linescreening dashboard         # local web dashboard (127.0.0.1:8765)
uv run linescreening doctor            # health check (--privacy: data flow)
uv run linescreening purge             # delete all local data + keychain + agent
```

The **dashboard** is a single self-contained page (no CDN, no external
assets) served on `127.0.0.1` only: grouped verdict cards with previews,
unread badges, reasons and confidence bars, a one-click re-triage button
and an offline toggle. Same data-flow rules as the CLI — the Jev call
happens only when you trigger it (and not at all in offline mode).

## Privacy & security posture

See [SECURITY.md](SECURITY.md). Highlights:

- **Never clicks into LINE.** AX automation is whitelisted (read attributes
  / click the menu-bar clock / press Esc); an `AXPress` inside LINE is
  blocked by `guards.py` and by CI tests. Viewing the chat list never marks
  messages as read — only opening a chat does.
- **Bounded capture.** Only the LINE window rect and the NC panel are ever
  captured — never the whole screen — enforced in code.
- **No daemon.** Quiet mode runs nothing in the background; capture happens
  only during the seconds `triage` runs. (An optional banner-mode watcher is
  a future item and will be sandboxed network-blind.)
- **Data minimisation.** Local sqlite stores only chat names/previews/
  timestamps; auto-purged after 3 days (`retention_days`); `purge` wipes
  everything.
- **Explicit cloud consent.** Message preview text (and only that) goes to
  `api.typesafe.ai`; `--offline` sends nothing. No telemetry, no crash
  reporting, no auto-update. 6 pinned runtime dependencies, `uv.lock`,
  no `shell=True`, static AppleScript payloads only.

## Limitations (honest list)

- OCR is heuristic. Vision's zh-Hant confidence often sits at 0.30; names
  are occasionally missed or garbled (the preview still carries the signal),
  timestamps sometimes lose their colon. Geometry/tolerances live in
  `config.yaml` and `parse.py` for a LINE redesign.
- Jev's CJK confidence runs lower than English; expect more MAYBE verdicts
  on ambiguous Chinese previews. Thresholds were calibrated so nothing
  urgent-looking is ever hidden.
- Only chats visible in the sidebar (~15–20 rows, no scrolling in v1).
  Chats muted inside LINE produce no notifications (irrelevant if you rely
  on source A).
- Messages that arrived while the Mac was asleep show only their last
  preview in the sidebar.
- Banner-mode watcher (source B) is not implemented yet — quiet mode +
  sidebar covers the primary use case. Contributions welcome.
- "Deep read" (full conversation contents without read receipts, the
  disconnect-network trick) is deliberately **not** automated: it requires
  logging out before reconnecting and can leak read receipts when any step
  fails. See SECURITY.md.

## Development

```bash
uv sync --dev
uv run pytest          # 79 tests incl. CI red-lines (guards, keychain isolation)
uv run ruff check . && uv run mypy
uv run linescreening dev sidebar   # live capture calibration helper
uv run python scripts/calibrate.py # scenario matrix vs real API
```

## License

MIT — see [LICENSE](LICENSE).
