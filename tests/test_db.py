"""Store (sqlite) tests — schema, retention purge, meta round-trip."""

from __future__ import annotations

import sqlite3

from linescreening.db import Store


def test_add_and_query_notifications(tmp_path):
    store = Store(tmp_path / "t.sqlite")
    store.add_notification("媽媽", "今晚要回來吃飯嗎？", source="nc")
    rows = store.notifications_since(None)
    assert len(rows) == 1
    assert rows[0]["chat_name"] == "媽媽"
    assert rows[0]["source"] == "nc"
    store.close()


def test_notifications_since_filters(tmp_path):
    from datetime import UTC, datetime, timedelta

    store = Store(tmp_path / "t.sqlite")
    store.add_notification("a", "x", "nc")
    future = (datetime.now(UTC) + timedelta(days=1)).isoformat(timespec="seconds")
    assert store.notifications_since(future) == []
    past = (datetime.now(UTC) - timedelta(days=1)).isoformat(timespec="seconds")
    assert len(store.notifications_since(past)) == 1
    store.close()


def test_purge_older_than(tmp_path):
    from datetime import UTC, datetime, timedelta

    store = Store(tmp_path / "t.sqlite")
    store.add_notification("old", "old row", "nc")
    # backdate it
    store._conn.execute(
        "UPDATE notifications SET captured_at = ?",
        ((datetime.now(UTC) - timedelta(days=10)).isoformat(timespec="seconds"),),
    )
    store._conn.commit()
    store.add_notification("new", "new row", "nc")

    deleted = store.purge_older_than(retention_days=3)
    rows = store.notifications_since(None)
    assert deleted == 1
    assert [r["chat_name"] for r in rows] == ["new"]
    store.close()


def test_meta_roundtrip(tmp_path):
    store = Store(tmp_path / "t.sqlite")
    assert store.get_meta("cloud_consent") is None
    store.set_meta("cloud_consent", "2026-09-20")
    assert store.get_meta("cloud_consent") == "2026-09-20"
    store.set_meta("cloud_consent", "2026-09-21")  # upsert
    assert store.get_meta("cloud_consent") == "2026-09-21"
    store.close()


def test_purge_all(tmp_path):
    store = Store(tmp_path / "t.sqlite")
    store.add_notification("a", "b", "nc")
    store.record_triage(3)
    store.set_meta("k", "v")
    store.purge_all()
    assert store.notifications_since(None) == []
    assert store.get_meta("k") is None
    cur: sqlite3.Cursor = store._conn.execute("SELECT COUNT(*) FROM triage_log")
    assert cur.fetchone()[0] == 0
    store.close()


def test_schema_idempotent(tmp_path):
    p = tmp_path / "t.sqlite"
    s1 = Store(p)
    s1.close()
    s2 = Store(p)  # must not raise on existing file
    s2.close()
