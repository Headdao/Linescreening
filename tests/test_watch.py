"""Auto-watcher tests — fakes everywhere; no capture, no network, no osascript."""

from __future__ import annotations

from linescreening.config import load_config
from linescreening.parse import SidebarRow
from linescreening.watch import Watcher, sidebar_signature


def _row(name="媽媽", preview="晚餐？", unread=1):
    return SidebarRow(chat_name=name, preview=preview, time_text="下午6:00", unread=unread)


def test_signature_stable_under_reorder_and_sensitive_to_content():
    a = [_row("A", "嗨"), _row("B", "好")]
    b = [_row("B", "好"), _row("A", "嗨")]
    assert sidebar_signature(a) == sidebar_signature(b)
    changed = [_row("A", "嗨"), _row("B", "不好")]
    assert sidebar_signature(a) != sidebar_signature(changed)
    unread_bump = [_row("A", "嗨"), _row("B", "好", unread=2)]
    assert sidebar_signature(a) != sidebar_signature(unread_bump)


def _watcher_with(rows_sequence, payloads, notified):
    """Build a Watcher whose pipeline steps replay canned data."""
    w = Watcher(load_config(), notify=lambda t, b: notified.append((t, b)))
    rows_iter = iter(rows_sequence)
    payload_iter = iter(payloads)
    w._poll_sidebar = lambda: next(rows_iter)  # type: ignore[method-assign]
    w._full_triage = lambda: next(payload_iter)  # type: ignore[method-assign]
    return w


def test_first_cycle_runs_full_triage_and_notifies_read_now():
    notified: list = []
    payload = {
        "chats": [
            {"name": "媽媽", "preview": "爸爸摔倒送醫", "verdict": "READ_NOW"},
            {"name": "廣告", "preview": "限時優惠", "verdict": "CAN_SKIP"},
        ]
    }
    w = _watcher_with([[_row()]], [payload], notified)
    res = w.step()
    assert res.changed is True
    assert [c["name"] for c in res.read_now] == ["媽媽"]
    assert len(notified) == 1  # CAN_SKIP stays silent
    assert "媽媽" in notified[0][0] and "爸爸" in notified[0][1]


def test_steady_state_skips_full_triage_and_api():
    notified: list = []
    payload = {"chats": [{"name": "媽媽", "preview": "晚餐？", "verdict": "READ_NOW"}]}
    w = _watcher_with([[_row()], [_row()]], [payload], notified)
    assert w.step().changed is True
    res2 = w.step()
    assert res2.changed is False
    assert res2.read_now == []
    assert len(notified) == 1  # no duplicate ping for the same message


def test_new_message_triggers_again_but_dedupes_same_content():
    notified: list = []
    p1 = {"chats": [{"name": "A", "preview": "第一則", "verdict": "READ_NOW"}]}
    p2 = {"chats": [
        {"name": "A", "preview": "第一則", "verdict": "READ_NOW"},  # already pinged
        {"name": "B", "preview": "第二則", "verdict": "READ_NOW"},  # new
    ]}
    w = _watcher_with([[_row("A", "第一則")], [_row("A", "第一則"), _row("B", "第二則")]],
                      [p1, p2], notified)
    w.step()
    w.step()
    assert len(notified) == 2
    assert notified[1][0].startswith("LINE：B")


def test_pipeline_error_never_raises():
    notified: list = []
    w = _watcher_with([], [], notified)

    def boom():
        raise RuntimeError("capture failed")

    w._poll_sidebar = boom  # type: ignore[method-assign]
    res = w.step()
    assert res.error and "capture failed" in res.error
    assert w.status_payload()["last_error"] == res.error


def test_status_payload_shape():
    w = Watcher(load_config(), notify=lambda t, b: None)
    payload = w.status_payload()
    assert set(payload) >= {
        "enabled", "interval_s", "running", "cycles", "full_runs",
        "last_scan_at", "last_change_at", "last_error",
    }
    assert payload["enabled"] is True
    assert payload["interval_s"] >= 30
