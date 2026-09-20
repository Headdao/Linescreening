# Contributing to linescreening

Thanks for helping! This project touches private messages, so the bar for
privacy-preserving behaviour is deliberately high.

## Hard rules (CI-enforced)

- **Never send `AXPress`/clicks to elements inside the LINE app.**
  Reading the chat list must stay side-effect free (no read receipts).
  All AX calls go through `src/linescreening/guards.py`.
- **Screenshots are bounded.** Capture only the LINE window rect, the
  Notification Center panel, or (banner mode) the top-right banner region.
  No arbitrary coordinates.
- **The watcher must stay network-free.** No network imports in
  `watcher.py`, no exceptions. It also runs under a no-network sandbox.
- **No real message data in the repo.** Tests use synthetic fixtures only.
  `.env`, sqlite files, and screenshots are gitignored — keep it that way.
- **Subprocess calls:** list-argv only (`shell=True` is forbidden), and
  osascript payloads must be static constants.
- No telemetry, crash reporting, or auto-update code.

## Development setup

```bash
uv sync                 # create venv + install locked deps
uv run pytest           # run the test suite
uv run ruff check .     # lint
uv run mypy             # type check
uv run linescreening --help
```

To try the first-run wizard: `uv run linescreening setup`
(requires the LINE desktop app to be running).

## Commits / style

- Conventional-ish commit subjects, small commits, keep CI green.
- Type-hint new code; run `ruff` + `mypy` before pushing.
