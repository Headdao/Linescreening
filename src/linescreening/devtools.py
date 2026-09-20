"""Calibration/dev helpers (`linescreening dev …`, hidden command).

sidebar : capture the LINE sidebar right now and print parsed rows
nc      : dump the Notification Center once and print parsed items
ocr-file: OCR any image file and print raw observations (fixture building)
"""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.table import Table

from linescreening.cgimage import image_size
from linescreening.config import load_config


def run_dev(what: str, path: str | None) -> int:
    console = Console()
    cfg = load_config()

    if what == "ocr-file":
        if not path:
            console.print("[red]usage: linescreening dev ocr-file <image.png>[/red]")
            return 1
        from linescreening.ocr import recognize_image

        items = recognize_image(path, languages=cfg.ocr["recognition_languages"])
        table = Table(title=f"OCR observations — {path}")
        for col in ("x", "y", "w", "h", "conf"):
            table.add_column(col)
        table.add_column("text", overflow="fold")
        for it in items:
            table.add_row(
                f"{it.x:.0f}",
                f"{it.y:.0f}",
                f"{it.w:.0f}",
                f"{it.h:.0f}",
                f"{it.confidence:.2f}",
                it.text,
            )
        console.print(table)
        console.print("Fixture snippet:")
        console.print(
            "    "
            + "    ".join(
                f'tok("{it.text}", {it.x:.0f}, {it.y:.0f}, w={it.w:.0f}, h={it.h:.0f}),'
                for it in items[:3]
            )
        )
        return 0

    if what == "sidebar":
        from linescreening import capture
        from linescreening.ocr import recognize_cgimage
        from linescreening.parse import parse_sidebar

        img = capture.capture_sidebar(cfg)
        dump = capture.save_png(img, Path("~/.linescreening/cache/sidebar_dev.png"))
        items = recognize_cgimage(img, languages=cfg.ocr["recognition_languages"])
        rows = parse_sidebar(items, float(image_size(img)[0]), cfg.sidebar)
        table = Table(title=f"Sidebar rows ({len(rows)}) — dump: {dump}")
        table.add_column("聊天", style="bold")
        table.add_column("未讀", justify="right")
        table.add_column("時間")
        table.add_column("預覽", overflow="fold")
        for r in rows:
            table.add_row(
                r.chat_name,
                "—" if r.unread is None else str(r.unread),
                r.time_text,
                r.preview or "（無預覽）",
            )
        console.print(table)
        return 0

    if what == "nc":
        import importlib

        ncdump = importlib.import_module("linescreening.ncdump")  # lands in Phase 5
        items = ncdump.dump_once(cfg)
        table = Table(title=f"Notification Center ({len(items)} items)")
        table.add_column("聊天", style="bold")
        table.add_column("時間")
        table.add_column("內容", overflow="fold")
        for it in items:
            table.add_row(it.chat_name, it.time_text, it.body or "（無內容）")
        console.print(table)
        return 0

    return 1
