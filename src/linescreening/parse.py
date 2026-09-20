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

_NUM_RE = re.compile(r"^\d{1,3}$")
# OCR often glues stray edge punctuation onto clean text
_EDGE_PUNCT = "）)」』】］>》..,,、;；-—_·"
_TRAILING_TIME = re.compile(r"\s*((上午|下午|晚上|中午|凌晨)?\s*\d{1,2}\s*[:：]?\s*\d{2})$")


def normalize_text(text: str) -> str:
    """Strip OCR edge punctuation so regex checks see the real content."""
    t = text.strip()
    while t and t[0] in _EDGE_PUNCT:
        t = t[1:].lstrip()
    while t and t[-1] in _EDGE_PUNCT:
        t = t[:-1].rstrip()
    return t


def split_trailing_time(name_text: str) -> tuple[str, str]:
    """OCR sometimes merges '名字 時間' into one token — pull the trailing
    time (colon optional: '下午450' == 下午4:50) out of a name."""
    m = _TRAILING_TIME.search(name_text.strip())
    if not m or not m.group(2):
        return name_text, ""
    time_part = m.group(1).replace(" ", "")
    rest = name_text[: m.start()].strip()
    if not rest:
        return name_text, ""
    return rest, time_part


def looks_like_time(text: str) -> bool:
    t = normalize_text(text)
    if not t or len(t) > 10:
        return False
    return bool(
        # with a 上午/下午-style prefix the colon may be OCR-dropped (下午450)
        re.fullmatch(r"(上午|下午|晚上|中午|凌晨)\s*\d{1,2}\s*[:：]?\s*\d{2}", t)
        # without the prefix a colon is required (else '1003' looks like a time)
        or re.fullmatch(r"\d{1,2}\s*[:：]\s*\d{2}", t)
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


def _badge_value(text: str) -> int | None:
    """'3' -> 3, '999+' -> 999, else None."""
    m = re.fullmatch(r"(\d{1,3})\+?", text.strip())
    return int(m.group(1)) if m else None


def _name_column_x(items: list[OcrText]) -> float | None:
    """The chat-name/preview column anchors at a consistent left x. Find it
    as the widest-aligned bucket of NON-time, NON-badge tokens (a long
    timestamp must not steal the anchor)."""
    candidates = [t for t in items if not looks_like_time(t.text) and _badge_value(t.text) is None]
    if not candidates:
        return None
    buckets: dict[int, float] = {}
    for t in candidates:
        key = round(t.x / 10) * 10
        buckets[key] = buckets.get(key, 0.0) + t.w
    best = max(buckets, key=lambda k: buckets[k])
    return float(best)


_SIDEBAR_NOISE = re.compile(
    r"^(AD|廣告)$|LINE TODAY|VOOM|即時戰報|廣告|贊助|搜尋聊天", re.IGNORECASE
)


def _merge_orphan_time_lines(lines: list[Line]) -> list[Line]:
    """When OCR misses a chat NAME but still reads its timestamp, the time
    token forms an orphan line. Merge such lines into the nearest content
    line below/above (within ~1.5 rows) so the row keeps its timestamp."""
    out: list[Line] = []
    for line in lines:
        time_only = bool(line.tokens) and all(looks_like_time(t.text) for t in line.tokens)
        if not time_only:
            out.append(line)
            continue
        tok0 = line.tokens[0]
        best_idx, best_dist = None, 1e9
        for idx, other in enumerate(out):
            dist = abs(tok0.cy - (other.y + other.h / 2))
            if dist < best_dist and dist < max(34.0, other.h * 2.0):
                best_idx, best_dist = idx, dist
        if best_idx is not None:
            merged = out[best_idx]
            out[best_idx] = Line(
                y=min(merged.y, line.y),
                h=max(merged.h, line.h),
                tokens=sorted(merged.tokens + line.tokens, key=lambda t: t.x),
            )
        # else: stray time far from any row — drop it
    return out


def parse_sidebar(
    items: list[OcrText],
    img_width: float,
    cfg: dict | None = None,
) -> list[SidebarRow]:
    """OCR observations (full LINE window, top-inset cropped) -> rows.

    Real LINE Mac layout (calibrated 2026-09): avatar column on the left
    (unread badge sits ON the avatar, e.g. '999+'), name+time line, and a
    preview line that may WRAP to a second line; VOOM/ad rows at the bottom.
    """
    cfg = cfg or {}
    max_rows = int(cfg.get("row_max_count", 40))

    name_x = _name_column_x(items)
    if name_x is None:
        return []

    # Split tokens: avatar/badge zone (left of the name column), name column,
    # right zone (timestamps). The sidebar's right boundary sits just past
    # the right-aligned timestamp column — anything beyond belongs to the
    # chat pane and is dropped.
    badge_tokens = [t for t in items if t.x < name_x - 20 and _badge_value(t.text)]
    time_rights = [t.x + t.w for t in items if looks_like_time(t.text)]
    boundary = (max(time_rights) + 25) if time_rights else img_width * 0.98
    column = [t for t in items if t.x >= name_x - 20 and t.x + t.w <= boundary]
    lines = cluster_lines(column)
    if not lines:
        return []
    lines = _merge_orphan_time_lines(lines)

    # attach badge tokens to the line whose y-span they overlap
    unread_by_line: dict[int, int] = {}
    for badge in badge_tokens:
        best_idx, best_dist = None, 1e9
        for idx, line in enumerate(lines):
            # a mid-list badge centers INSIDE its row's vertical span;
            # a badge at the very top of the crop belongs to a half-clipped
            # row above (whose name line was never OCR'd) — attaching it to
            # the row below produced the "999 未讀 on the wrong chat" bug,
            # so badges no line covers are dropped instead.
            if not (line.y - 18 <= badge.cy <= line.y + line.h + 8):
                continue
            center = line.y + line.h / 2
            dist = abs(badge.cy - center)
            if dist < best_dist:
                best_idx, best_dist = idx, dist
        if best_idx is not None:
            unread_by_line.setdefault(best_idx, _badge_value(badge.text) or 0)

    rows: list[SidebarRow] = []
    i = 0
    while i < len(lines) and len(rows) < max_rows:
        line = lines[i]
        time_toks = [t for t in line.tokens if looks_like_time(t.text)]
        rest = [t for t in line.tokens if t not in time_toks]
        if not rest:
            i += 1
            continue
        name = join_tokens(rest)
        time_text = " ".join(normalize_text(t.text) for t in time_toks)
        # OCR may have glued '名字 時間' into one token — split it back out
        name, trailing_time = split_trailing_time(name)
        if trailing_time and not time_text:
            time_text = trailing_time
        unread = unread_by_line.get(i)

        preview_parts: list[str] = []
        consumed = 1
        # A preview line follows the name; WRAPPED continuations sit ~16-18px
        # below the previous line's top, while the next chat's row starts
        # ~28px+ lower — the top-pitch test keeps folds inside one row even
        # when OCR misses the next row's timestamp.
        j = i + 1
        first = True
        while j < len(lines):
            window = 2.0 if first else 1.1
            if not _is_preview_line(lines[j - 1], lines[j], window=window):
                break
            if not first:
                pitch = lines[j].y - lines[j - 1].y
                if pitch > max(24.0, lines[j - 1].h * 1.7):
                    break
            nxt = lines[j]
            nxt_time = [t for t in nxt.tokens if looks_like_time(t.text)]
            preview_parts.append(join_tokens([t for t in nxt.tokens if t not in nxt_time]))
            unread = unread or unread_by_line.get(j)
            consumed += 1
            j += 1
            first = False

        i += consumed
        if not name or _SIDEBAR_NOISE.search(name) or _SIDEBAR_NOISE.search("".join(preview_parts)):
            continue
        rows.append(
            SidebarRow(
                chat_name=name,
                preview="".join(preview_parts),
                time_text=time_text,
                unread=unread,
                raw_texts=tuple(t.text for t in line.tokens),
            )
        )
    return rows


def _is_preview_line(name_line: Line, candidate: Line, window: float = 2.0) -> bool:
    """A preview sits directly below the name line, at a similar left edge,
    and is not itself a name+time line (no right-aligned timestamp)."""
    dy = candidate.y - (name_line.y + name_line.h)
    if not -name_line.h * 0.5 <= dy <= name_line.h * window:
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
    if not -title_line.h * 0.5 <= dy <= title_line.h * 1.6:
        return False
    if candidate.left > title_line.left + 30:
        return False
    has_time = any(looks_like_time(t.text) for t in candidate.tokens)
    return not has_time
