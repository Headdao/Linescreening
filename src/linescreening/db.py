"""Local storage — data minimisation by design.

Stores only what triage needs: chat names, preview text, timestamps.
Purged automatically after `retention_days`. `purge_all()` wipes everything.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS notifications (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_name   TEXT NOT NULL,
    body        TEXT NOT NULL,
    source      TEXT NOT NULL,           -- 'nc' | 'watcher'
    captured_at TEXT NOT NULL            -- ISO-8601 UTC
);
CREATE INDEX IF NOT EXISTS idx_notifications_captured
    ON notifications(captured_at);
CREATE INDEX IF NOT EXISTS idx_notifications_chat
    ON notifications(chat_name);

CREATE TABLE IF NOT EXISTS triage_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ran_at      TEXT NOT NULL,
    chats_seen  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Store:
    def __init__(self, db_path: Path) -> None:
        db_path = Path(db_path).expanduser()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)

    # -- notifications -------------------------------------------------
    def add_notification(self, chat_name: str, body: str, source: str) -> None:
        self._conn.execute(
            "INSERT INTO notifications (chat_name, body, source, captured_at) VALUES (?, ?, ?, ?)",
            (chat_name, body, source, _utcnow()),
        )
        self._conn.commit()

    def notifications_since(self, iso_since: str | None = None) -> list[sqlite3.Row]:
        if iso_since is None:
            cur = self._conn.execute(
                "SELECT * FROM notifications ORDER BY captured_at DESC, id DESC"
            )
        else:
            cur = self._conn.execute(
                "SELECT * FROM notifications WHERE captured_at > ? "
                "ORDER BY captured_at DESC, id DESC",
                (iso_since,),
            )
        return cur.fetchall()

    # -- triage log ----------------------------------------------------
    def record_triage(self, chats_seen: int) -> None:
        self._conn.execute(
            "INSERT INTO triage_log (ran_at, chats_seen) VALUES (?, ?)",
            (_utcnow(), chats_seen),
        )
        self._conn.commit()

    # -- meta ----------------------------------------------------------
    def set_meta(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self._conn.commit()

    def get_meta(self, key: str) -> str | None:
        cur = self._conn.execute("SELECT value FROM meta WHERE key = ?", (key,))
        row = cur.fetchone()
        return row["value"] if row else None

    # -- lifecycle -----------------------------------------------------
    def purge_older_than(self, retention_days: int) -> int:
        """Delete rows older than `retention_days`. Returns deleted count."""
        cutoff = (datetime.now(UTC) - timedelta(days=retention_days)).isoformat(timespec="seconds")
        cur = self._conn.execute("DELETE FROM notifications WHERE captured_at < ?", (cutoff,))
        self._conn.commit()
        return cur.rowcount

    def purge_all(self) -> None:
        """Wipe every stored row (used by `linescreening purge`)."""
        self._conn.executescript(
            "DELETE FROM notifications; DELETE FROM triage_log; DELETE FROM meta;"
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
