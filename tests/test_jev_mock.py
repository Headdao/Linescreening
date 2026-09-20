"""Mock Jev client tests — deterministic heuristics, no network."""

from __future__ import annotations

import pytest

from linescreening.jev import MockJevClient, mock_answer

QUESTIONS = {
    "expects_reply": {"type": "noul", "instructions": "Expects a reply"},
    "time_sensitive": {"type": "noul", "instructions": "Time-sensitive"},
    "asks_action": {"type": "noul", "instructions": "Asks an action"},
    "automated_broadcast": {"type": "noul", "instructions": "Automated"},
    "casual_social": {"type": "noul", "instructions": "Casual social"},
    "importance": {"type": "score", "instructions": "Importance", "criteria": ["a", "b", "c", "d"]},
    "urgency": {"type": "score", "instructions": "Urgency", "criteria": ["a", "b", "c"]},
    "message_kind": {
        "type": "choice",
        "instructions": "Kind",
        "criteria": {"question": None, "social": None, "unclear": None},
    },
}


def state_for(preview: str, name: str = "媽媽") -> dict:
    return {"chat": {"name": name, "latest_preview": preview, "unread_count": 1}}


def test_deterministic():
    a1 = MockJevClient().ask(state_for("今晚要回來吃飯嗎？"), QUESTIONS)
    a2 = MockJevClient().ask(state_for("今晚要回來吃飯嗎？"), QUESTIONS)
    assert a1 == a2


def test_family_dinner_is_time_sensitive_and_expects_reply():
    answers = MockJevClient().ask(state_for("今晚要回來吃飯嗎？"), QUESTIONS)
    assert answers["time_sensitive"]["noul"] > 0.5
    assert answers["expects_reply"]["noul"] > 0.5
    assert answers["urgency"]["score"] == 2.0
    assert answers["importance"]["score"] == 3.0


def test_coupon_is_automated():
    answers = MockJevClient().ask(
        state_for("限時優惠！全站商品 8 折", name="LINE 官方帳號"), QUESTIONS
    )
    assert answers["automated_broadcast"]["noul"] > 0.5
    assert answers["message_kind"]["choice"] == "automated_notice"


def test_casual_chat():
    answers = MockJevClient().ask(state_for("哈哈", name="小明"), QUESTIONS)
    assert answers["casual_social"]["noul"] > 0.5
    assert answers["importance"]["score"] == 0.0


def test_plain_info_falls_to_maybes():
    answers = MockJevClient().ask(state_for("下次聚餐改到週五"), QUESTIONS)
    assert answers["time_sensitive"]["noul"] < 0.5
    assert answers["urgency"]["score"] == 0.0


def test_unknown_noul_is_unsure():
    answer = mock_answer(
        state_for("x"), "brand_new_question", {"type": "noul", "instructions": "?"}
    )
    assert answer["noul"] == 0.5


def test_every_answer_has_type():
    answers = MockJevClient().ask(state_for("隨便一句話"), QUESTIONS)
    for qid, payload in answers.items():
        assert payload["type"] in {"noul", "score", "choice"}, qid
        if payload["type"] == "score":
            assert 0.0 <= payload["score"] <= 3.0


def test_bad_question_type_raises():
    with pytest.raises(ValueError):
        mock_answer(state_for("x"), "q", {"type": "essay"})
