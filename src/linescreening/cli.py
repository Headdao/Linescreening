"""Command-line entry point.

Subcommands land phase by phase; unimplemented ones explain what's coming.
"""

from __future__ import annotations

import argparse
import sys

from linescreening import __version__


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="linescreening",
        description="Triage unread LINE chats on macOS without triggering read receipts.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command")

    setup = sub.add_parser("setup", help="first-run guided setup wizard (interactive)")
    setup.add_argument(
        "--step",
        metavar="NAME",
        help="redo a single step (env/screen/ax/notify/key/watcher/smoke/summary)",
    )
    triage = sub.add_parser("triage", help="capture, ask Jev, print the ranked report")
    triage.add_argument("--mock", action="store_true", help="offline mock answers (no API call)")
    triage.add_argument("--offline", action="store_true", help="list unreads only, no cloud call")
    triage.add_argument("--json", action="store_true", help="machine-readable output")
    doctor = sub.add_parser("doctor", help="non-interactive health check")
    doctor.add_argument("--privacy", action="store_true", help="show what is seen/stored/sent")
    sub.add_parser("watch", help="foreground banner watcher (banner mode only)")
    sub.add_parser("check", help="verify Jev API connectivity")
    purge = sub.add_parser("purge", help="delete ALL local data, keychain entry, launchd agent")
    purge.add_argument("--yes", action="store_true", help="skip confirmation")
    dev = sub.add_parser("dev", help=argparse.SUPPRESS)  # calibration helpers
    dev.add_argument("what", choices=["sidebar", "nc", "ocr-file"])
    dev.add_argument("path", nargs="?", help="image path for ocr-file")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command in (None, "setup"):
        from linescreening.setup_wizard import run_wizard

        return run_wizard(only_step=getattr(args, "step", None))
    if args.command == "triage":
        from linescreening.report import run_triage

        ok = run_triage(
            mock=getattr(args, "mock", False),
            offline=getattr(args, "offline", False),
            json_output=getattr(args, "json", False),
        )
        return 0 if ok else 1
    if args.command == "doctor":
        from linescreening.doctor import run_doctor

        return run_doctor(privacy=getattr(args, "privacy", False))
    if args.command == "watch":
        print("Banner watcher lands in Phase 6 (banner mode only; quiet mode needs none).")
        return 0
    if args.command == "check":
        from rich.console import Console

        from linescreening.checks import check_jev_api

        result = check_jev_api()
        Console().print(f"{'✅' if result.ok else '❌'} {result.name}：{result.detail}")
        return 0 if result.ok else 1
    if args.command == "purge":
        from linescreening.purge import run_purge

        return run_purge(confirm=not getattr(args, "yes", False))
    if args.command == "dev":
        from linescreening.devtools import run_dev

        return run_dev(args.what, getattr(args, "path", None))
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
