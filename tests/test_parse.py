"""Parser tests with synthetic OCR fixtures (no real screenshots, no TCC)."""

from __future__ import annotations

from linescreening.ocr import OcrText
from linescreening.parse import (
    cluster_lines,
    join_tokens,
    looks_like_count,
    looks_like_time,
    parse_notifications,
    parse_sidebar,
)

SIDEBAR_W = 360.0


def tok(text: str, x: float, y: float, w: float = None, h: float = 22.0) -> OcrText:  # noqa: RUF013
    w = w if w is not None else max(18.0, 16.0 * len(text))
    return OcrText(text=text, confidence=0.95, x=x, y=y, w=w, h=h)


# --- a realistic sidebar: 3 chats, one with unread badge ---------------------
FIXTURE = [
    # row 1: 媽媽 (3 unread) — name line + time + preview line
    tok("媽媽", 64, 100),
    tok("下午2:35", 280, 100, w=60),
    tok("今晚要回來吃飯嗎？", 64, 128),
    tok("3", 330, 128, w=14, h=14),
    # row 2: LINE 官方帳號 (no badge)
    tok("LINE 官方帳號", 64, 190),
    tok("週五", 292, 190, w=30),
    tok("限時優惠 全站8折", 64, 218),
    # row 3: 專案群組, badge on its own line between rows
    tok("專案群組", 64, 280),
    tok("上午9:02", 280, 280, w=60),
    tok("我傳了新版的簡報，麻煩看一下", 64, 308),
    tok("12", 330, 308, w=16, h=14),
]


def test_looks_like_time():
    assert looks_like_time("下午2:35")
    assert looks_like_time("9:02")
    assert looks_like_time("週五")
    assert looks_like_time("昨天")
    assert looks_like_time("10/12")
    assert looks_like_time("3月5日")
    assert not looks_like_time("媽媽")
    assert not looks_like_time("123")
    assert not looks_like_time("優惠到 12/31 前有效")


def test_looks_like_count():
    assert looks_like_count("3")
    assert looks_like_count("47")
    assert not looks_like_count("3a")
    assert not looks_like_count("1234")


def test_join_tokens_respects_gap():
    a, b = tok("媽媽", 64, 100, w=32), tok("下午2:35", 280, 100, w=60)
    joined = join_tokens([a, b])
    assert " " in joined  # wide gap -> separator
    assert join_tokens([tok("AB", 0, 0, w=20), tok("CD", 22, 0, w=20)]) == "ABCD"


def test_cluster_lines_splits_by_y():
    items = [tok("A", 0, 0), tok("B", 0, 4), tok("C", 0, 60)]
    lines = cluster_lines(items)
    assert len(lines) == 2
    assert [ln.text for ln in lines] == ["AB", "C"]


def test_parse_sidebar_full_fixture():
    rows = parse_sidebar(FIXTURE, SIDEBAR_W)
    assert len(rows) == 3
    assert rows[0].chat_name == "媽媽"
    assert rows[0].preview == "今晚要回來吃飯嗎？3" or rows[0].preview == "今晚要回來吃飯嗎？"
    assert rows[0].unread == 3
    assert rows[0].time_text == "下午2:35"

    assert rows[1].chat_name == "LINE 官方帳號"
    assert rows[1].unread is None
    assert rows[1].preview == "限時優惠 全站8折"

    assert rows[2].chat_name == "專案群組"
    assert rows[2].unread == 12
    assert "簡報" in rows[2].preview


def test_parse_sidebar_caps_rows():
    cfg = {"row_max_count": 2}
    rows = parse_sidebar(FIXTURE, SIDEBAR_W, cfg)
    assert len(rows) == 2


def test_parse_sidebar_name_only_row():
    items = [tok("某人", 64, 100), tok("中午12:00", 270, 100, w=70)]
    rows = parse_sidebar(items, SIDEBAR_W)
    assert len(rows) == 1
    assert rows[0].chat_name == "某人"
    assert rows[0].preview == ""


def test_parse_notifications_basic():
    items = [
        tok("LINE", 40, 40, w=40),
        tok("媽媽", 40, 90),
        tok("現在", 280, 90, w=34),
        tok("晚餐煮好了，下來吃", 40, 118),
        tok("還有 2 則通知", 40, 170),
    ]
    notes = parse_notifications(items, 360.0)
    assert len(notes) == 1
    assert notes[0].chat_name == "媽媽"
    assert notes[0].body == "晚餐煮好了，下來吃"
    assert notes[0].time_text == "現在"


def test_parse_notifications_title_without_body():
    items = [tok("貼圖", 40, 90), tok("剛剛", 280, 90, w=30)]
    notes = parse_notifications(items, 360.0)
    assert len(notes) == 1
    assert notes[0].body == ""


def test_parse_notifications_drops_system_chrome():
    items = [
        tok("通知中心", 40, 20),
        tok("還有 3 則通知", 40, 60),
        tok("媽媽", 40, 110),
        tok("現在", 280, 110, w=30),
        tok("晚餐好了", 40, 138),
    ]
    notes = parse_notifications(items, 360.0)
    assert len(notes) == 1
    assert notes[0].chat_name == "媽媽"


def test_parse_notifications_folds_wrapped_body():
    items = [
        tok("Microsoft Outlook", 40, 90),
        tok("52分鐘前", 268, 90, w=50),
        tok("我們歡迎您的意見反應！", 40, 118),
        tok("我們只需要您回答兩個問題。", 40, 146),
        tok("Osmond", 40, 220),
        tok("59分鐘前", 268, 220, w=50),
        tok("我的奶油呢", 40, 248),
    ]
    notes = parse_notifications(items, 360.0)
    assert len(notes) == 2
    assert notes[0].chat_name == "Microsoft Outlook"
    assert "意見反應" in notes[0].body and "兩個問題" in notes[0].body
    assert notes[1].chat_name == "Osmond"
    assert notes[1].body == "我的奶油呢"
