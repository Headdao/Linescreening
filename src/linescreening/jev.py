"""Jev (TypeSafe AI) client wrapper + deterministic mock.

One request per unread chat (fan-out: all questions in a single call).
Questions arrive as raw dicts shaped for the SDK / REST API:

    {"expects_reply": {"type": "noul", "instructions": "..."}, ...}

Answers normalise to plain dicts:
    noul   -> {"type": "noul", "noul": 0.91}
    score  -> {"type": "score", "score": 2.0, "confidence": 0.88, ...}
    choice -> {"type": "choice", "choice": "question", "confidence": 0.8, ...}

The mock never touches the network — it powers `--mock`, CI and offline dev.
"""

from __future__ import annotations

from typing import Any, Protocol

# ---------------------------------------------------------------------------
# Heuristics shared by the mock (keywords cover zh-TW / ja-lite / en patterns)
# ---------------------------------------------------------------------------
_TIME_SENSITIVE = (
    "今晚",
    "今天",
    "明天",
    "現在",
    "幾點",
    "急",
    "urgent",
    "asap",
    "today",
    "tonight",
    "tomorrow",
    "deadline",
)
_EXPECTS_REPLY = ("？", "?", "嗎", "能不能", "可以嗎", "要不要", "回我", "回覆")
_ASKS_ACTION = ("幫我", "記得", "麻煩", "請你", "幫忙", "send", "confirm", "book", "transfer")
_AUTOMATED = (
    "優惠",
    "折扣",
    "coupon",
    "官方帳號",
    "line voom",
    "newsletter",
    "促銷",
    "活動通知",
    "首刷禮",
)
_TRANSACTIONAL = (
    "消費",
    "扣款",
    "刷卡",
    "帳單",
    "繳費",
    "到貨",
    "提醒",
    "警示",
    "登入",
    "驗證",
    "交易",
    "欠費",
    "已核准",
    "charge",
    "billing",
    "delivery",
)
_REDIRECT = (
    "登入",
    "點擊",
    "詳情",
    "查看詳細",
    "請至",
    "前往",
    "log in",
    "click here",
    "see details",
)
_CASUAL = ("哈哈", "嘿嘿", "貼圖", "早安", "晚安", "hi", "hello", "xd", "lol", "ok", "OK")


def _hits(text: str, needles: tuple[str, ...]) -> int:
    text = text.lower()
    return sum(1 for n in needles if n.lower() in text)


def _join_previews(state: dict[str, Any]) -> str:
    chat = state.get("chat", state)
    parts: list[str] = [str(chat.get("name", ""))]
    if chat.get("latest_preview"):
        parts.append(str(chat["latest_preview"]))
    parts.extend(str(p) for p in chat.get("previews_since_last_check", []) or [])
    return "\n".join(parts)


def mock_answer(
    state: dict[str, Any], question_id: str, question: dict[str, Any]
) -> dict[str, Any]:
    """Deterministic keyword-based fake answer — good enough to exercise the pipeline."""
    text = _join_previews(state)
    qtype = question.get("type")

    if qtype == "noul":
        table = {
            "time_sensitive": _TIME_SENSITIVE,
            "expects_reply": _EXPECTS_REPLY,
            "asks_action": _ASKS_ACTION,
            "automated_broadcast": _AUTOMATED,
            "is_transactional": _TRANSACTIONAL,
            "is_redirect_ping": _REDIRECT,
            "casual_social": _CASUAL,
        }
        needles = table.get(question_id)
        if needles is None:  # unknown noul — lean unsure
            return {"type": "noul", "noul": 0.5}
        n = _hits(text, needles)
        value = min(0.95, 0.08 + 0.45 * n)
        return {"type": "noul", "noul": round(value, 2)}

    if qtype == "score":
        if question_id == "urgency":
            score = (
                2.0
                if _hits(text, _TIME_SENSITIVE)
                else (1.0 if _hits(text, _EXPECTS_REPLY) else 0.0)
            )
            return {"type": "score", "score": score, "confidence": 0.9}
        if question_id == "importance":
            score = 1.0
            if _hits(text, _ASKS_ACTION) or _hits(text, _EXPECTS_REPLY):
                score = 3.0
            elif _hits(text, _TIME_SENSITIVE):
                score = 2.0
            elif _hits(text, _CASUAL) or _hits(text, _AUTOMATED):
                score = 0.0
            return {"type": "score", "score": score, "confidence": 0.9}
        return {"type": "score", "score": 1.0, "confidence": 0.5}

    if qtype == "choice":
        if _hits(text, _AUTOMATED):
            pick = "automated_notice"
        elif _hits(text, _EXPECTS_REPLY):
            pick = "question"
        elif _hits(text, _ASKS_ACTION):
            pick = "direct_request"
        elif _hits(text, _TIME_SENSITIVE):
            pick = "plan_or_schedule"
        elif _hits(text, _CASUAL):
            pick = "social"
        else:
            pick = "unclear"
        return {"type": "choice", "choice": pick, "confidence": 0.82}

    raise ValueError(f"unknown question type: {qtype!r}")


class JevClient(Protocol):
    def ask(
        self, state: dict[str, Any], questions: dict[str, dict[str, Any]]
    ) -> dict[str, dict[str, Any]]: ...


class MockJevClient:
    """Offline stand-in. Same interface as the real client."""

    def ask(
        self, state: dict[str, Any], questions: dict[str, dict[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        return {qid: mock_answer(state, qid, q) for qid, q in questions.items()}


class RealJevClient:
    """Thin wrapper around typesafe-sdk. API key comes from the Keychain
    (keychain.py, Phase 2) with a TYPESAFE_API_KEY env fallback for CI."""

    def __init__(self, api_key: str | None = None, model: str = "jev-latest") -> None:
        from typesafe_sdk import TypeSafeClient

        self._client = TypeSafeClient(api_key=api_key) if api_key else TypeSafeClient()
        self._model = model

    def ask(
        self, state: dict[str, Any], questions: dict[str, dict[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        response = self._client.system_one(
            state=state,
            questions=questions,  # type: ignore[arg-type]  # raw dicts accepted by SDK
            model=self._model,
        )
        answers: dict[str, dict[str, Any]] = {}
        for qid, answer in response.answers.items():
            payload: dict[str, Any] = {"type": answer.type}
            if answer.type == "noul":
                payload["noul"] = answer.noul
            elif answer.type == "score":
                payload["score"] = answer.score
                payload["confidence"] = answer.confidence
            elif answer.type == "choice":
                payload["choice"] = answer.choice
                payload["confidence"] = answer.confidence
            answers[qid] = payload
        return answers


def make_client(mock: bool, model: str = "jev-latest") -> JevClient:  # noqa: FBT001
    if mock:
        return MockJevClient()
    import os
    import sys

    api_key = None
    if sys.platform == "darwin":
        try:
            from linescreening import keychain

            api_key = keychain.load_key()
        except Exception:  # noqa: BLE001 — keychain locked/unavailable
            api_key = None
    api_key = api_key or os.environ.get("TYPESAFE_API_KEY")
    if api_key:
        return RealJevClient(api_key=api_key, model=model)
    raise RuntimeError(
        "No API key available. Run `linescreening setup` (stores the key in the "
        "Keychain) or set TYPESAFE_API_KEY for CI use."
    )
