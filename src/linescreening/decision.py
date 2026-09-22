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
            "user personally BY A PERSON, in a conversation, that expects a reply. "
            "Automated or system directives ('please pick up within 3 days') are "
            "NOT reply-expecting messages."
        ),
    },
    "time_sensitive": {
        "type": "noul",
        "instructions": (
            "The messages involve something time-critical the USER must act on "
            "or attend: happening today/tonight, a deadline, a schedule change, "
            "or words like now / today / tonight / 幾點. A mere timestamp of when "
            "something already happened (e.g. a charge at 2:15pm) is NOT "
            "time-sensitivity."
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
            "The messages look like PROMOTIONAL mass-sent marketing: a coupon, "
            "discount campaign, advertisement, newsletter, or promotional blast "
            "from an official account. (Factual notices about the user's own "
            "account do NOT count.)"
        ),
    },
    "is_transactional": {
        "type": "noul",
        "instructions": (
            "The message itself contains the actionable detail about something "
            "the user already did or must personally do — their delivery's pickup "
            "code, their appointment time, their payment. A notice that only says "
            "'please log in to view' does NOT count, and the parameters of a "
            "PROMOTIONAL OFFER (discount %, offer deadline) do NOT count either."
        ),
    },
    "is_redirect_ping": {
        "type": "noul",
        "instructions": (
            "The message tells the user to go somewhere else — log in, open an "
            "app, click a link, 'see details' — WITHOUT containing the actual "
            "information itself. It is an empty pointer, not a report."
        ),
        "criteria": {
            "true": (
                "The only substance is directing the user elsewhere, e.g. "
                "「您有新訊息，請登入查看」「詳情請點擊連結」"
            ),
            "false": (
                "The message itself reports the fact (amount, pickup code, "
                "appointment time) or is a human conversation"
            ),
        },
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
            "No clock at all; nothing is lost by reading it late",
            "Relevant within the next few days",
            "A real clock for the USER: something is scheduled, happens, or "
            "expires today or within hours, and acting later would be too "
            "late (a meeting today, a payment deadline tonight, a pickup "
            "window closing). NOTE: a status report that something already "
            "happened or is already broken — a CI/deploy failure, an alert "
            "digest, a crash log — has NO clock: fixing it tonight instead "
            "of now loses nothing.",
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
    transactional = _noul(answers, "is_transactional")
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

    # Promotional mass-sends are skippable even when they shout "today
    # only!" — but a strong TRANSACTIONAL signal (charge, security alert,
    # bill, delivery) means the official sender is reporting a fact about
    # the user's own account, and it must not sink to the bottom.
    redirect = _noul(answers, "is_redirect_ping")
    if automated > t["can_skip_automated"] and transactional < t["transactional_floor"]:
        verdict = Verdict.CAN_SKIP
        reasons.append(f"行銷/大量發送訊號強（{automated:.2f}）")
    elif redirect > t["redirect_ping"] and transactional < t["transactional_floor"]:
        verdict = Verdict.CAN_SKIP
        reasons.append(f"空導流通知（{redirect:.2f}）：內容在別處，訊息本身無資訊")
    elif urgency_n > t["read_now_urgency_norm"] or (
        expects_reply > t["read_now_expects_reply"] and importance_raw >= 2
    ):
        verdict = Verdict.READ_NOW
        if urgency_n > t["read_now_urgency_norm"]:
            reasons.append(f"時間敏感（urgency {urgency_raw:.1f}/2）")
        if expects_reply > t["read_now_expects_reply"] and importance_raw >= 2:
            reasons.append(f"期待回覆（{expects_reply:.2f}）且重要度高")
        # A machine is never waiting on the user the way a person is: CI /
        # deploy failures, monitoring and digests cap at READ_SOON. Only a
        # TRANSACTIONAL fact about the user's own account (fraud alert with
        # a reply-by clock, charge, bill due today) keeps READ_NOW.
        kind = answers.get("message_kind") or {}
        if (
            kind.get("choice") == "automated_notice"
            and float(kind.get("confidence") or 0) >= 0.8
            and transactional < t["transactional_floor"]
        ):
            verdict = Verdict.READ_SOON
            reasons.append("機器/系統通知（無人在等回覆）→ 最高為可稍後讀")
    elif casual > t["can_skip_casual"]:
        verdict = Verdict.CAN_SKIP
        reasons.append(f"純閒聊訊號強（{casual:.2f}）")
    elif priority >= t["read_soon_priority"]:
        verdict = Verdict.READ_SOON
        reasons.append(f"綜合優先度 {priority:.2f}")
    else:
        verdict = Verdict.MAYBE
        reasons.append(f"綜合優先度 {priority:.2f}（訊號不明確）")

    if transactional >= t["transactional_floor"] and automated > t["can_skip_automated"]:
        reasons.append(f"訊息本身含可直接行動內容（{transactional:.2f}）→ 不自動略過")

    confidence = _min_confidence(answers)
    low_conf = confidence < t["low_confidence"]
    # never downgrade READ_NOW; very strong marketing signals (>0.85) also
    # stay CAN_SKIP — a bank ad at low confidence metadata is still an ad.
    strong_marketing = verdict is Verdict.CAN_SKIP and automated > 0.85
    if low_conf and verdict in {Verdict.READ_SOON, Verdict.CAN_SKIP} and not strong_marketing:
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

# importance axis for human overrides (升級 = towards READ_NOW)
IMPORTANCE_AXIS: list[Verdict] = [
    Verdict.CAN_SKIP,
    Verdict.MAYBE,
    Verdict.READ_SOON,
    Verdict.READ_NOW,
]

QUESTION_LABEL = {
    "expects_reply": "期待回覆",
    "time_sensitive": "時間敏感",
    "asks_action": "要求行動",
    "automated_broadcast": "行銷大量發送",
    "is_transactional": "含交易事實",
    "is_redirect_ping": "空導流",
    "casual_social": "純閒聊",
    "importance": "重要度（0–3）",
    "urgency": "時效（0–2）",
    "message_kind": "訊息類型",
}


def scores_summary(answers: dict) -> dict[str, dict]:
    """Compact per-question value+confidence view for the dashboard."""
    out: dict[str, dict] = {}
    for key, spec in QUESTION_BATTERY.items():
        a = answers.get(key) or {}
        if spec["type"] == "noul":
            value = a.get("noul")
        elif spec["type"] == "score":
            value = a.get("score")
        else:
            value = a.get("choice")
        out[key] = {"v": value, "conf": a.get("confidence")}
    return out


def sort_triages(items: list[Triage]) -> list[Triage]:
    return sorted(items, key=lambda x: (VERDICT_ORDER[x.verdict], -x.priority))
