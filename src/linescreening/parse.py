"""Parse OCR observations into structured sidebar rows / notification items.

Pure logic — no macOS APIs — so everything here is unit-testable with
synthetic observation fixtures. Geometry numbers are heuristics tuned for
the LINE Mac sidebar (row = chat-name line + preview line); they live in
config.yaml so a LINE redesign only changes YAML, not code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from linescreening.ocr import OcrText

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SidebarRow:
    chat_name: str
    preview: str
    time_text: str
    unread: int | None = None  # None = badge not detected (may still be unread)
    raw_texts: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class NotificationItem:
    chat_name: str
    body: str
    time_text: str = ""


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_TIME_RE = re.compile(
    r"^(剛剛|剛才|上午|下午|晚上|中午)?\s*\d{1,2}[:：]\d{2}$"
    r"|^\d{1,2}/\d{1,2}$"
    r"|^\d{1,2}月\d{1,2}日?$"
    r"|^(昨天|今天|週[一二三四五六日天]|星期[一二三四五六日天])$"
    r"^(剛剰)?",
)
_NUM_RE = re.compile(r"^\d{1,3}$")


def looks_like_time(text: str) -> bool:
    t = text.strip()
    if not t or len(t) > 10:
        return False
    return bool(
        re.fullmatch(r"(上午|下午|晚上|中午|凌晨)?\s*\d{1,2}[:：]\d{2}", t)
        or re.fullmatch(r"\d{1,2}/\d{1,2}", t)
        or re.fullmatch(r"\d{1,2}月\d{1,2}日?", t)
        or re.fullmatch(r"昨天|今天|現在|剛剛", t)
        or re.fullmatch(r"\d{1,3}\s*(秒|分鐘|小時|天)前", t)
        or re.fullmatch(r"(週|星期)[一二三四五六日天]", t)
    )


def looks_like_count(text: str) -> bool:
    return bool(_NUM_RE.fullmatch(text.strip()))


# ---------------------------------------------------------------------------
# Line clustering
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Line:
    y: float
    h: float
    tokens: list[OcrText]  # sorted by x

    @property
    def text(self) -> str:
        return join_tokens(self.tokens)

    @property
    def left(self) -> float:
        return self.tokens[0].x if self.tokens else 0.0

    @property
    def right(self) -> float:
        return self.tokens[-1].x + self.tokens[-1].w if self.tokens else 0.0


def join_tokens(tokens: list[OcrText], max_gap: float = 14.0) -> str:
    """Merge horizontally adjacent tokens; insert space for wide gaps."""
    parts: list[str] = []
    prev: OcrText | None = None
    for tok in sorted(tokens, key=lambda t: t.x):
        if prev is not None and tok.x - (prev.x + prev.w) > max_gap:
            parts.append(" ")
        parts.append(tok.text)
        prev = tok
    return "".join(parts)


def cluster_lines(items: list[OcrText], y_tolerance: float | None = None) -> list[Line]:
    """Group observations whose vertical centers are close into text lines."""
    if not items:
        return []
    heights = sorted(o.h for o in items)
    median_h = heights[len(heights) // 2]
    tol = y_tolerance if y_tolerance is not None else max(6.0, median_h * 0.55)
    ordered = sorted(items, key=lambda o: o.cy)
    lines: list[Line] = []
    bucket: list[OcrText] = [ordered[0]]
    for tok in ordered[1:]:
        prev_cy = bucket[-1].cy
        if abs(tok.cy - prev_cy) <= tol:
            bucket.append(tok)
        else:
            lines.append(
                Line(
                    y=min(t.y for t in bucket),
                    h=max(t.h for t in bucket),
                    tokens=sorted(bucket, key=lambda t: t.x),
                )
            )
            bucket = [tok]
    lines.append(
        Line(
            y=min(t.y for t in bucket),
            h=max(t.h for t in bucket),
            tokens=sorted(bucket, key=lambda t: t.x),
        )
    )
    return lines


# ---------------------------------------------------------------------------
# Sidebar parsing
# ---------------------------------------------------------------------------


def parse_sidebar(
    items: list[OcrText],
    img_width: float,
    cfg: dict | None = None,
) -> list[SidebarRow]:
    """OCR observations from the sidebar crop -> one SidebarRow per chat."""
    cfg = cfg or {}
    max_rows = int(cfg.get("row_max_count", 40))
    rows: list[SidebarRow] = []

    lines = cluster_lines(items)
    if not lines:
        return []

    # Unread badges: small numeric tokens near the right edge, own cluster
    badge_by_line_idx: dict[int, int] = {}
    content_lines: list[Line] = []
    right_edge = img_width * 0.995
    for line in lines:
        numeric = [t for t in line.tokens if looks_like_count(t.text)]
        others = [t for t in line.tokens if t not in numeric]
        if numeric and not others and numeric[0].x > img_width * 0.80:
            badge_by_line_idx[len(content_lines)] = int(numeric[0].text)
            continue  # badge line consumed
        if numeric and others:
            # e.g. "3" sitting on the time line right side
            for n in numeric:
                if n.x > img_width * 0.80 and n.x + n.w >= right_edge - 40:
                    badge_by_line_idx[len(content_lines)] = int(n.text)
                    line = Line(y=line.y, h=line.h, tokens=[t for t in others])
        content_lines.append(line)

    # Walk lines in pairs: (name+time line) followed by preview line.
    i = 0
    while i < len(content_lines) and len(rows) < max_rows:
        line = content_lines[i]
        time_toks = [t for t in line.tokens if looks_like_time(t.text)]
        rest = [t for t in line.tokens if t not in time_toks]
        if not rest:
            i += 1
            continue
        name = join_tokens(rest)
        time_text = " ".join(t.text for t in time_toks)
        unread = badge_by_line_idx.get(i)

        preview = ""
        nxt = content_lines[i + 1] if i + 1 < len(content_lines) else None
        if nxt is not None and _is_preview_line(line, nxt):
            nxt_time = [t for t in nxt.tokens if looks_like_time(t.text)]
            preview = join_tokens([t for t in nxt.tokens if t not in nxt_time])
            # badge often sits on the preview line (right edge) — claim it too
            unread = unread or badge_by_line_idx.get(i + 1)
            i += 2
        else:
            i += 1

        if name:
            nxt_texts = tuple(t.text for t in nxt.tokens) if (preview and nxt is not None) else ()
            rows.append(
                SidebarRow(
                    chat_name=name,
                    preview=preview,
                    time_text=time_text,
                    unread=unread,
                    raw_texts=tuple(t.text for t in line.tokens) + nxt_texts,
                )
            )
    return rows


def _is_preview_line(name_line: Line, candidate: Line) -> bool:
    """A preview sits directly below the name line, at a similar left edge,
    and is not itself a name+time line (no right-aligned timestamp)."""
    dy = candidate.y - (name_line.y + name_line.h)
    if not -2 <= dy <= name_line.h * 2.0:
        return False
    if candidate.left > name_line.left + 40:
        return False
    has_time = any(looks_like_time(t.text) for t in candidate.tokens)
    return not has_time


# ---------------------------------------------------------------------------
# Notification Center parsing
# ---------------------------------------------------------------------------


_NC_NOISE_TITLE = re.compile(
    r"通知中心|Notification Center|顯示更多|Show More|清除|Clear|編輯小工具|Edit Widgets",
    re.IGNORECASE,
)


def parse_notifications(items: list[OcrText], img_width: float) -> list[NotificationItem]:
    """OCR observations from the NC panel -> notification items (best effort).

    NC layout per LINE notification: title (chat/sender name, bold) with a
    timestamp on the right, body preview below, grouped with a header like
    「LINE」 + 還有 N 則通知. We keep it deliberately simple: a line without
    a body below is still emitted (body=''), so triage never drops a chat.
    Wrapped body lines are folded into the preceding item, and system chrome
    (panel title, 還有 N 則, buttons) is dropped.
    """
    lines = cluster_lines(items)
    raw: list[NotificationItem] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.text.strip()
        # App group header ("LINE" alone / 「還有 N 則…」 / chrome buttons)
        if (
            re.fullmatch(r"LINE|還有\s*\d+\s*(則|個).*", stripped)
            or not stripped
            or _NC_NOISE_TITLE.fullmatch(stripped)
        ):
            i += 1
            continue
        time_toks = [t for t in line.tokens if looks_like_time(t.text)]
        rest = [t for t in line.tokens if t not in time_toks]
        if not rest:
            i += 1
            continue
        title = join_tokens(rest)
        time_text = " ".join(t.text for t in time_toks)
        body = ""
        nxt = lines[i + 1] if i + 1 < len(lines) else None
        if nxt is not None and _nc_is_body(line, nxt):
            body = nxt.text.strip()
            i += 2
        else:
            i += 1
        if _NC_NOISE_TITLE.fullmatch(title):
            continue
        raw.append(NotificationItem(chat_name=title, body=body, time_text=time_text))

    # Fold continuation lines: an item with no time and empty-ish profile is a
    # wrapped body of the previous item when the previous one has a body.
    out: list[NotificationItem] = []
    for item in raw:
        if out and not item.time_text and out[-1].body and not _looks_like_new_title(out[-1], item):
            prev = out[-1]
            out[-1] = NotificationItem(
                chat_name=prev.chat_name,
                body=(prev.body + item.chat_name).strip(" "),
                time_text=prev.time_text,
            )
        else:
            out.append(item)
    return out


def _looks_like_new_title(prev: NotificationItem, candidate: NotificationItem) -> bool:
    """Heuristic: a new notification title usually follows a blank gap; here we
    treat a candidate as a new title when it carries its own timestamp."""
    return bool(candidate.time_text)


def _nc_is_body(title_line: Line, candidate: Line) -> bool:
    dy = candidate.y - (title_line.y + title_line.h)
    if not -2 <= dy <= title_line.h * 1.6:
        return False
    if candidate.left > title_line.left + 30:
        return False
    has_time = any(looks_like_time(t.text) for t in candidate.tokens)
    return not has_time
