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


def test_feedback_roundtrip_and_purge(tmp_path):
    p = tmp_path / "t.sqlite"
    s = Store(p)
    s.record_feedback(
        chat_name="Headdao/Linescreening",
        preview="Multiple runs failed for ci.yml",
        verdict_model="READ_NOW",
        verdict_user="READ_SOON",
        direction=-1,
        scores={
            "urgency": {"v": 1.7, "conf": 0.5},
            "message_kind": {"v": "automated_notice", "conf": 0.99},
        },
    )
    stats = s.feedback_stats()
    assert stats["count"] == 1 and stats["last_at"]
    recent = s.feedback_recent()
    assert recent[0]["chat_name"] == "Headdao/Linescreening"
    assert recent[0]["verdict_model"] == "READ_NOW" and recent[0]["verdict_user"] == "READ_SOON"
    s.purge_all()
    assert s.feedback_stats()["count"] == 0
    s.close()
