"""Decision-model tests: battery shape, state building, combination verdicts."""

from __future__ import annotations

import pytest

from linescreening.config import load_config
from linescreening.decision import (
    QUESTION_BATTERY,
    Verdict,
    build_state,
    combine,
    sort_triages,
    state_from_sources,
)
from linescreening.parse import NotificationItem, SidebarRow


@pytest.fixture()
def cfg():
    return load_config()


def answers(**over) -> dict:
    base = {
        "expects_reply": {"type": "noul", "noul": 0.1},
        "time_sensitive": {"type": "noul", "noul": 0.1},
        "asks_action": {"type": "noul", "noul": 0.1},
        "automated_broadcast": {"type": "noul", "noul": 0.05},
        "casual_social": {"type": "noul", "noul": 0.1},
        "importance": {"type": "score", "score": 1.0, "confidence": 0.9},
        "urgency": {"type": "score", "score": 0.0, "confidence": 0.9},
        "message_kind": {"type": "choice", "choice": "info_share", "confidence": 0.9},
    }
    base.update(over)
    return base


# --- battery ----------------------------------------------------------------


def test_battery_shape():
    types = {k: v["type"] for k, v in QUESTION_BATTERY.items()}
    assert types == {
        "expects_reply": "noul",
        "time_sensitive": "noul",
        "asks_action": "noul",
        "automated_broadcast": "noul",
        "casual_social": "noul",
        "importance": "score",
        "urgency": "score",
        "message_kind": "choice",
    }
    assert len(QUESTION_BATTERY["importance"]["criteria"]) == 4
    assert len(QUESTION_BATTERY["urgency"]["criteria"]) == 3
    assert "unclear" in QUESTION_BATTERY["message_kind"]["criteria"]


# --- state building ---------------------------------------------------------


def test_build_state_group_heuristic():
    s = build_state("家庭群組", None, "爸爸：晚餐七點", ["媽媽：記得買水果"])
    assert s["chat"]["is_group"] is True
    assert s["chat"]["previews_since_last_check"] == ["媽媽：記得買水果"]
    assert s["user_context"]["language"] == "zh-TW"


def test_build_state_private_chat():
    s = build_state("媽媽", 1, "今晚要回來吃飯嗎？")
    assert s["chat"]["is_group"] is False
    assert s["chat"]["unread_count"] == 1


def test_state_from_sources_merges_by_name():
    row = SidebarRow(chat_name="Osmond", preview="我的奶油呢", time_text="下午2:41", unread=2)
    nc = [
        NotificationItem(chat_name="Osmond", body="等等", time_text="下午2:30"),
        NotificationItem(chat_name="Osmond", body="我的奶油呢", time_text="下午2:41"),
        NotificationItem(chat_name="別人", body="無關", time_text="下午2:00"),
    ]
    s = state_from_sources(row, nc)
    assert s is not None
    assert s["chat"]["name"] == "Osmond"
    assert s["chat"]["latest_preview"] == "我的奶油呢"
    assert "等等" in s["chat"]["previews_since_last_check"]
    assert s["chat"]["unread_count"] == 2


def test_state_from_nc_only():
    nc = [NotificationItem(chat_name="新聊天", body="在嗎", time_text="現在")]
    s = state_from_sources(None, nc)
    assert s["chat"]["name"] == "新聊天"
    assert s["chat"]["unread_count"] is None


# --- combination ------------------------------------------------------------


def test_family_dinner_read_now(cfg):
    t = combine(
        "媽媽",
        answers(
            expects_reply={"type": "noul", "noul": 0.91},
            time_sensitive={"type": "noul", "noul": 0.88},
            urgency={"type": "score", "score": 2.0, "confidence": 0.9},
            importance={"type": "score", "score": 3.0, "confidence": 0.88},
        ),
        cfg,
    )
    assert t.verdict is Verdict.READ_NOW
    assert any("時間敏感" in r for r in t.reasons)


def test_coupon_can_skip_even_if_urgent(cfg):
    t = combine(
        "LINE 官方帳號",
        answers(
            automated_broadcast={"type": "noul", "noul": 0.95},
            time_sensitive={"type": "noul", "noul": 0.7},
            urgency={"type": "score", "score": 2.0, "confidence": 0.9},
        ),
        cfg,
    )
    assert t.verdict is Verdict.CAN_SKIP
    assert any("官方" in r for r in t.reasons)


def test_casual_can_skip(cfg):
    t = combine(
        "朋友",
        answers(
            casual_social={"type": "noul", "noul": 0.9},
            importance={"type": "score", "score": 0.0, "confidence": 0.9},
        ),
        cfg,
    )
    assert t.verdict is Verdict.CAN_SKIP


def test_plain_info_maybe_or_soon(cfg):
    t = combine("同事", answers(), cfg)
    assert t.verdict in {Verdict.MAYBE, Verdict.READ_SOON}


def test_mid_priority_read_soon(cfg):
    t = combine(
        "同事",
        answers(
            importance={"type": "score", "score": 2.0, "confidence": 0.9},
            urgency={"type": "score", "score": 1.0, "confidence": 0.9},
            expects_reply={"type": "noul", "noul": 0.4},
        ),
        cfg,
    )
    assert t.verdict is Verdict.READ_SOON


def test_important_but_no_urgency_is_not_read_now(cfg):
    t = combine(
        "同事",
        answers(
            importance={"type": "score", "score": 3.0, "confidence": 0.9},
            expects_reply={"type": "noul", "noul": 0.3},
        ),
        cfg,
    )
    assert t.verdict in {Verdict.READ_SOON, Verdict.MAYBE}


def test_low_confidence_downgrades_soft_verdicts(cfg):
    t = combine(
        "同事",
        answers(
            casual_social={"type": "noul", "noul": 0.9},
            importance={"type": "score", "score": 0.0, "confidence": 0.2},
            urgency={"type": "score", "score": 0.0, "confidence": 0.3},
        ),
        cfg,
    )
    assert t.verdict is Verdict.MAYBE
    assert t.low_confidence is True


def test_low_confidence_never_downgrades_read_now(cfg):
    t = combine(
        "媽媽",
        answers(
            urgency={"type": "score", "score": 2.0, "confidence": 0.2},
            importance={"type": "score", "score": 3.0, "confidence": 0.3},
        ),
        cfg,
    )
    assert t.verdict is Verdict.READ_NOW
    assert t.low_confidence is True


def test_sort_order(cfg):
    now = combine("a", answers(urgency={"type": "score", "score": 2.0, "confidence": 0.9}), cfg)
    skip = combine("b", answers(automated_broadcast={"type": "noul", "noul": 0.95}), cfg)
    maybe = combine("c", answers(), cfg)
    ordered = sort_triages([skip, maybe, now])
    assert [x.verdict for x in ordered] == [Verdict.READ_NOW, Verdict.MAYBE, Verdict.CAN_SKIP]
