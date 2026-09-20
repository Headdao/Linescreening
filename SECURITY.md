# Security Policy — linescreening

linescreening reads unread LINE message previews from your Mac's screen
(chat-list sidebar + Notification Center) and sends **preview text** to the
Typesafe AI (Jev) decision API to triage which chats are worth opening.
It never opens a chat room, so it never triggers read receipts (已讀).

## Security guarantees (enforced by tests in CI)

1. **No always-on component in quiet mode.** The default (quiet) mode has
   **no background daemon**. Screen capture happens only for the few seconds
   while `linescreening triage` runs, and only of two regions:
   the LINE window and the Notification Center panel.
2. **The banner-mode watcher (optional) is network-blind.** It never imports
   a networking library and runs under a launchd `sandbox-exec` profile that
   denies all network access. A CI test fails if a network import appears in
   `watcher.py`.
3. **No clicks into LINE.** All accessibility automation is whitelisted in
   `guards.py`: reading attributes, clicking the menu-bar clock, pressing Esc.
   An `AXPress` on any element inside the LINE app is forbidden and blocked.
   A CI test scans for violations.
4. **Secrets never touch disk in plaintext.** The Typesafe API key is stored
   in the macOS Keychain (service `com.linescreening`), never in the repo,
   never in logs.

## What this tool can see / store / transmit

| | Details |
|---|---|
| **Sees (pixels)** | LINE window contents; Notification Center panel; (banner mode only) top-right corner of the screen |
| **Dashboard** | `linescreening dashboard` binds **127.0.0.1 only** (loopback — nothing outside this Mac can connect), serves one self-contained page with no external assets; its /api/triage triggers the same capture+Jev flow as the CLI (no Jev call in offline mode) |
| **Stores locally** | `~/.linescreening/linescreening.sqlite` — chat names, preview text, timestamps. Auto-purged after `retention_days` (default 3). Deleted entirely by `linescreening purge`. |
| **Transmits** | Message preview text (and only that) to `api.typesafe.ai` when triage runs **with** your consent. `--offline` sends nothing. No telemetry, no crash reporting, no auto-update. |
| **Permissions (TCC)** | Screen Recording (capture). Accessibility (optional, Notification Center). Both revocable in System Settings at any time. |

## Threat model notes

- A malicious build could exfiltrate previews; mitigate by building from
  source (`uv sync && uv run linescreening`) and reviewing diffs — the
  dependency set is intentionally tiny (5 runtime dependencies) and locked
  in `uv.lock`.
- OCR runs fully on-device via Apple's Vision framework.
- macOS may periodically ask you to re-confirm Screen Recording permission;
  that is expected OS behaviour, not tampering. `linescreening doctor`
  verifies capture still works.

## Reporting a vulnerability

Please open a private security advisory on GitHub
(Security → Report a vulnerability) or contact the maintainer via the repo.
Do not open a public issue for security problems.
