"""Auto watcher — run triage continuously while the dashboard is up.

Philosophy: silence is the product. The poll loop is invisible (sidebar is
captured window-scoped, no UI disturbance, no API calls); only when the
unread signature CHANGES does it run the full pipeline (NC dump + Jev).
Steady state therefore costs nothing, and only READ_NOW verdicts ever
surface a macOS notification — lower tiers stay silent on purpose.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field

from linescreening import guards

log = logging.getLogger(__name__)


@dataclass
class WatchStatus:
    """Snapshot for the dashboard — also the /api/watch/status payload."""

    enabled: bool = True
    interval_s: float = 120.0
    running: bool = False
    cycles: int = 0
    full_runs: int = 0
    last_scan_at: str | None = None
    last_change_at: str | None = None
    last_error: str | None = None


@dataclass
class WatchResult:
    changed: bool = False
    read_now: list[dict] = field(default_factory=list)
    error: str | None = None


def sidebar_signature(rows: list) -> str:  # noqa: ANN001 — SidebarRow, avoid import cycle
    """Stable digest of the sidebar state — any new message, read or badge
    change alters it; identical sidebars across cycles hash equal."""
    parts = sorted(
        (r.chat_name, str(r.unread), r.preview, r.time_text) for r in rows
    )
    return "|".join("\x00".join(p) for p in parts)


class Watcher:
    """Owns the poll loop. Inject `providers` for tests; production uses the
    real capture pipeline (never touches LINE beyond reading its pixels)."""

    def __init__(self, cfg, notify=None) -> None:  # noqa: ANN001 — Config, avoid cycle
        self.cfg = cfg
        watch = cfg.raw.get("watch", {})
        self.interval_s = max(30.0, float(watch.get("interval_s", 120.0)))
        self.enabled = bool(watch.get("enabled", True))
        self.notify = notify or guards.send_notification
        self._notified: set[tuple[str, str]] = set()
        self._last_sig: str | None = None
        self.status = WatchStatus(interval_s=self.interval_s, enabled=self.enabled)
        self._lock = threading.Lock()

    # -- one poll step (sidebar-only; cheap, invisible) ----------------------
    def _poll_sidebar(self) -> list:
        from linescreening.report import _real_sidebar

        return _real_sidebar(self.cfg)

    # -- full triage (NC dump + Jev) ----------------------------------------
    def _full_triage(self) -> dict:
        from linescreening.report import collect_triage

        return collect_triage(cfg=self.cfg)

    def step(self) -> WatchResult:
        """One watcher cycle. Never raises — errors land in status/result."""
        with self._lock:
            self.status.running = True
        result = WatchResult()
        try:
            rows = self._poll_sidebar()
            sig = sidebar_signature(rows)
            with self._lock:
                self.status.cycles += 1
                self.status.last_scan_at = _now_iso()
            if sig == self._last_sig:
                return result
            self._last_sig = sig
            payload = self._full_triage()
            with self._lock:
                self.status.full_runs += 1
                self.status.last_change_at = _now_iso()
                self.status.last_error = None
            result.changed = True
            for chat in payload.get("chats", []):
                if chat.get("verdict") == "READ_NOW":
                    result.read_now.append(chat)
                    self._notify_read_now(chat)
        except Exception as exc:  # noqa: BLE001 — watcher must never die
            result.error = f"{exc.__class__.__name__}: {exc}"[:200]
            with self._lock:
                self.status.last_error = result.error
            log.warning("watch cycle failed: %s", result.error)
        finally:
            with self._lock:
                self.status.running = False
        return result

    def _notify_read_now(self, chat: dict) -> None:
        name = str(chat.get("name") or "訊息")
        preview = str(chat.get("preview") or "")
        key = (name, preview)
        if key in self._notified:
            return
        self._notified.add(key)
        try:
            self.notify(f"LINE：{name}", preview or "有值得立即讀的訊息")
        except Exception:  # noqa: BLE001 — notification must not break cycles
            log.warning("notification failed", exc_info=True)

    # -- background loop ------------------------------------------------------
    def _loop(self, stop: threading.Event) -> None:
        while not stop.wait(self.interval_s):
            if not self.enabled:
                continue
            self.step()

    def start(self) -> threading.Thread:
        stop = threading.Event()
        thread = threading.Thread(
            target=self._loop, args=(stop,), daemon=True, name="linescreening-watch"
        )
        thread.start()
        return thread

    def status_payload(self) -> dict:
        with self._lock:
            st = self.status
            return {
                "enabled": self.enabled,
                "interval_s": st.interval_s,
                "running": st.running,
                "cycles": st.cycles,
                "full_runs": st.full_runs,
                "last_scan_at": st.last_scan_at,
                "last_change_at": st.last_change_at,
                "last_error": st.last_error,
            }


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat(timespec="seconds")
