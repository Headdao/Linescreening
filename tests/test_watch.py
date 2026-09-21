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
    w._full_triage = lambda silent=True: next(payload_iter)  # type: ignore[method-assign]
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


def test_signature_ignores_ocr_noise_and_time_drift():
    # spacing/punct variance must not flip the signature
    a = [_row("媽媽", "晚餐？")]
    noisy = [SidebarRow(chat_name="媽 媽", preview="晚餐", time_text="5分鐘前", unread=1)]
    assert sidebar_signature(a) == sidebar_signature(noisy)
    # relative labels (剛剛 -> 5分鐘前) drift on their own — never a change
    t1 = [_row("A", "嗨")]
    t2 = [SidebarRow(chat_name="A", preview="嗨", time_text="剛剛", unread=1)]
    assert sidebar_signature(t1) == sidebar_signature(t2)


def test_hidden_line_skips_silently_then_heartbeats():
    from linescreening.capture import LineNotVisibleError

    notified: list = []
    payload = {"chats": [], "warnings": [], "notices": []}
    w = _watcher_with([[_row()]], [payload], notified)
    w.heartbeat_s = 0  # disable heartbeat for the skip phase
    calls = []

    def hidden():
        calls.append("poll")
        raise LineNotVisibleError("occluded")

    w._poll_sidebar = hidden  # type: ignore[method-assign]
    for _ in range(3):
        res = w.step()
        assert res.changed is False and res.error is None  # silent skip, no error spam
    assert w.status_payload()["line_state"] == "hidden"

    # heartbeat enabled: after enough blind cycles a deep (activating) scan runs
    w._hidden_streak = 0
    w.heartbeat_s = w.interval_s
    full_calls = []
    w._full_triage = lambda silent=True: (full_calls.append(silent), payload)[1]  # type: ignore[method-assign]
    res = w.step()  # streak 0 -> still skipping
    assert res.changed is False and full_calls == []
    res = w.step()  # streak 1 * interval >= heartbeat -> deep scan
    assert res.changed is True
    assert full_calls == [False]  # deep scan is NOT silent (allowed to activate)


def test_classify_line_visibility_pure():
    from linescreening.capture import classify_line_visibility

    line_win = {"kCGWindowOwnerName": "LINE", "kCGWindowLayer": 0,
                "kCGWindowBounds": {"X": 100, "Y": 100, "Width": 600, "Height": 400}}
    cover = {"kCGWindowOwnerName": "Finder", "kCGWindowLayer": 0,
             "kCGWindowBounds": {"X": 300, "Y": 200, "Width": 800, "Height": 600}}
    away = {"kCGWindowOwnerName": "Safari", "kCGWindowLayer": 0,
            "kCGWindowBounds": {"X": 0, "Y": 0, "Width": 90, "Height": 90}}
    floating = {"kCGWindowOwnerName": "系統", "kCGWindowLayer": 25,
                "kCGWindowBounds": {"X": 120, "Y": 120, "Width": 500, "Height": 300}}
    tiny_line = {"kCGWindowOwnerName": "LINE", "kCGWindowLayer": 0,
                 "kCGWindowBounds": {"X": 0, "Y": 0, "Width": 100, "Height": 80}}

    assert classify_line_visibility([away, line_win])[0] == "visible"
    # floating chrome above LINE does not count as occlusion
    assert classify_line_visibility([floating, away, line_win])[0] == "visible"
    assert classify_line_visibility([cover, line_win])[0] == "occluded"
    assert classify_line_visibility([cover, tiny_line])[0] == "hidden"
    assert classify_line_visibility([])[0] == "hidden"
