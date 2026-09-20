"""Jev decision model — question battery, composite scoring, verdicts.

Design follows docs.typesafe.ai guidance:
- one request per chat, fan-out all atomic questions in that request
- the model judges situations (rubrics), never counts or does date math
- code combines answers: normalised weighted priority + thresholds +
  confidence gates; the report ALWAYS lists every unread chat (verdicts
  only rank and annotate, they never hide)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from linescreening.config import Config
from linescreening.parse import NotificationItem, SidebarRow

# ---------------------------------------------------------------------------
# Question battery (atomic, English instructions — Jev's primary language)
# ---------------------------------------------------------------------------

QUESTION_BATTERY: dict[str, dict] = {
    "expects_reply": {
        "type": "noul",
        "instructions": (
            "The latest messages contain a question or request directed at the "
            "user personally that expects a reply."
        ),
    },
    "time_sensitive": {
        "type": "noul",
        "instructions": (
            "The messages involve something time-critical: something happening "
            "today or tonight, a deadline, a schedule change, or words like "
            "now / today / tonight / 幾點."
        ),
    },
    "asks_action": {
        "type": "noul",
        "instructions": (
            "The sender asks the user to do a concrete task: send something, "
            "confirm, book, pay, transfer, vote, or check something."
        ),
    },
    "automated_broadcast": {
        "type": "noul",
        "instructions": (
            "The messages look automated or mass-sent: an official-account "
            "notice, coupon, newsletter, campaign blast, or system alert."
        ),
    },
    "casual_social": {
        "type": "noul",
        "instructions": (
            "The messages are casual social chatter: greetings, stickers, "
            "laughter, short reactions with no specific content."
        ),
    },
    "importance": {
        "type": "score",
        "instructions": "How much the content matters to the user personally.",
        "criteria": [
            "Casual chatter, a reaction or sticker, or a content-free greeting",
            "General FYI, social update, or broadcast with mild personal relevance",
            "Information about plans, people, or topics the user personally knows",
            "Needs the user's attention or reply: a question, request, or "
            "decision affecting the user",
        ],
    },
    "urgency": {
        "type": "score",
        "instructions": "How soon the content becomes stale or acts on a clock.",
        "criteria": [
            "No time element; can be read whenever",
            "Relevant within the next few days",
            "Time-critical today or right now: something scheduled, changing, "
            "or expiring imminently",
        ],
    },
    "message_kind": {
        "type": "choice",
        "instructions": "What kind of message is this, at its core?",
        "criteria": {
            "direct_request": "Asks the user to do a concrete task",
            "question": "Asks the user something expecting an answer",
            "plan_or_schedule": "About plans, timing, meetings, logistics",
            "info_share": "Shares information for awareness, no reply needed",
            "social": "Greeting, sticker, reaction, small talk",
            "automated_notice": "Machine-generated or mass-sent content",
            "unclear": None,
        },
    },
}

# ---------------------------------------------------------------------------
# State building
# ---------------------------------------------------------------------------


def _group_heuristic(name: str, preview: str, unread: int | None) -> bool:
    """Group chats often show 'sender: message' previews or pile up unread."""
    if (unread or 0) >= 5:
        return True
    head = preview[:24]
    return ("：" in head and head.index("：") <= 12) or (":" in head and head.index(":") <= 12)


def build_state(
    chat_name: str,
    unread: int | None,
    latest_preview: str,
    extra_previews: list[str] | None = None,
    received_at_text: str = "",
) -> dict:
    previews = [p for p in (extra_previews or []) if p and p != latest_preview][-10:]
    return {
        "chat": {
            "name": chat_name,
            "is_group": _group_heuristic(chat_name, latest_preview, unread),
            "unread_count": unread,
            "latest_preview": latest_preview,
            "previews_since_last_check": previews,
            "received_at_text": received_at_text,
        },
        "user_context": {"language": "zh-TW"},
    }


def state_from_sources(row: SidebarRow | None, nc_items: list[NotificationItem]) -> dict | None:
    """Merge sidebar row (authoritative unread count) + NC items by chat name."""
    if row is None and not nc_items:
        return None
    if row is None:
        first = nc_items[0]
        return build_state(
            first.chat_name,
            None,
            nc_items[-1].body,
            [n.body for n in nc_items[:-1]],
            nc_items[-1].time_text,
        )
    nc_bodies = [n.body for n in nc_items if n.chat_name == row.chat_name and n.body]
    latest = nc_bodies[-1] if nc_bodies else row.preview
    earlier = ([row.preview] if row.preview and row.preview != latest else []) + nc_bodies[:-1]
    return build_state(row.chat_name, row.unread, latest, earlier, row.time_text)


# ---------------------------------------------------------------------------
# Combination & verdicts
# ---------------------------------------------------------------------------


class Verdict(StrEnum):
    READ_NOW = "READ_NOW"
    READ_SOON = "READ_SOON"
    CAN_SKIP = "CAN_SKIP"
    MAYBE = "MAYBE"


VERDICT_LABEL = {
    Verdict.READ_NOW: "值得讀（現在）",
    Verdict.READ_SOON: "可稍後讀",
    Verdict.CAN_SKIP: "可略過",
    Verdict.MAYBE: "不確定",
}


@dataclass
class Triage:
    chat_name: str
    verdict: Verdict
    priority: float
    reasons: list[str] = field(default_factory=list)
    low_confidence: bool = False
    detail: dict = field(default_factory=dict)  # full answers, for --json


def _noul(answers: dict, key: str) -> float:
    a = answers.get(key) or {}
    return float(a.get("noul", 0.5))


def _score(answers: dict, key: str) -> tuple[float, float]:
    """Return (raw score, normalised 0-1) for a score answer."""
    a = answers.get(key) or {}
    raw = float(a.get("score", 1.0))
    levels = len(QUESTION_BATTERY[key]["criteria"]) - 1
    return raw, min(1.0, max(0.0, raw / levels))


def _min_confidence(answers: dict) -> float:
    confs = [
        float(a.get("confidence"))
        for a in answers.values()
        if a.get("type") in {"score", "choice"} and a.get("confidence") is not None
    ]
    return min(confs) if confs else 1.0


def combine(chat_name: str, answers: dict, cfg: Config) -> Triage:
    """Weighted priority + threshold verdicts + confidence gate (all in YAML)."""
    w = cfg.weights
    t = cfg.thresholds

    urgency_raw, urgency_n = _score(answers, "urgency")
    importance_raw, importance_n = _score(answers, "importance")
    expects_reply = _noul(answers, "expects_reply")
    time_sensitive = _noul(answers, "time_sensitive")
    asks_action = _noul(answers, "asks_action")
    automated = _noul(answers, "automated_broadcast")
    casual = _noul(answers, "casual_social")

    priority = (
        w["urgency"] * urgency_n
        + w["importance"] * importance_n
        + w["expects_reply"] * expects_reply
        + w["asks_action"] * asks_action
        + w["time_sensitive"] * time_sensitive
        - w["automated_broadcast_penalty"] * automated
        - w["casual_social_penalty"] * casual
    )

    reasons: list[str] = []
    verdict: Verdict

    # Automated spam is skippable even when it shouts "today only!".
    if automated > t["can_skip_automated"]:
        verdict = Verdict.CAN_SKIP
        reasons.append(f"官方/大量發送訊號強（{automated:.2f}）")
    elif urgency_n > t["read_now_urgency_norm"] or (
        expects_reply > t["read_now_expects_reply"] and importance_raw >= 2
    ):
        verdict = Verdict.READ_NOW
        if urgency_n > t["read_now_urgency_norm"]:
            reasons.append(f"時間敏感（urgency {urgency_raw:.1f}/2）")
        if expects_reply > t["read_now_expects_reply"] and importance_raw >= 2:
            reasons.append(f"期待回覆（{expects_reply:.2f}）且重要度高")
    elif casual > t["can_skip_casual"]:
        verdict = Verdict.CAN_SKIP
        reasons.append(f"純閒聊訊號強（{casual:.2f}）")
    elif priority >= t["read_soon_priority"]:
        verdict = Verdict.READ_SOON
        reasons.append(f"綜合優先度 {priority:.2f}")
    else:
        verdict = Verdict.MAYBE
        reasons.append(f"綜合優先度 {priority:.2f}（訊號不明確）")

    confidence = _min_confidence(answers)
    low_conf = confidence < t["low_confidence"]
    if low_conf and verdict in {Verdict.READ_SOON, Verdict.CAN_SKIP}:
        # never downgrade READ_NOW — an urgent-looking message stays visible;
        # soft verdicts with shaky evidence become MAYBE instead.
        verdict = Verdict.MAYBE
        reasons.append(f"模型信心不足（{confidence:.2f}）")

    return Triage(
        chat_name=chat_name,
        verdict=verdict,
        priority=round(priority, 3),
        reasons=reasons,
        low_confidence=low_conf,
        detail={
            "answers": answers,
            "urgency": urgency_raw,
            "importance": importance_raw,
            "confidence": round(confidence, 3),
        },
    )


VERDICT_ORDER = {
    Verdict.READ_NOW: 0,
    Verdict.MAYBE: 1,
    Verdict.READ_SOON: 2,
    Verdict.CAN_SKIP: 3,
}


def sort_triages(items: list[Triage]) -> list[Triage]:
    return sorted(items, key=lambda x: (VERDICT_ORDER[x.verdict], -x.priority))
