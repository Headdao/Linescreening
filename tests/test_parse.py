"""Parser tests with synthetic OCR fixtures (no real screenshots, no TCC)."""

from __future__ import annotations

from linescreening.ocr import OcrText
from linescreening.parse import (
    cluster_lines,
    join_tokens,
    looks_like_time,
    normalize_text,
    parse_notifications,
    parse_sidebar,
    split_trailing_time,
)


def tok(text: str, x: float, y: float, w: float = None, h: float = 22.0) -> OcrText:  # noqa: RUF013
    w = w if w is not None else max(18.0, 16.0 * len(text))
    return OcrText(text=text, confidence=0.95, x=x, y=y, w=w, h=h)


# --- realistic sidebar (calibrated against real LINE Mac 2026-09) ------------
# geometry: badge on avatar column (x≈80), names/previews x≈200, times x≈460
SIDEBAR_W = 590.0
FIXTURE = [
    # row 1: 媽媽 (3 unread on avatar) — name + time + wrapped preview
    tok("3", 80, 160, w=16, h=16),
    tok("媽媽", 200, 160),
    tok("下午4:50", 460, 160, w=54),
    tok("先約10/3下午，你中午來永和姐家吃午飯，", 200, 186),
    tok("我煮，姐去法國", 200, 204),
    # row 2: LINE 官方帳號 (no badge, 999+ on the row above is separate)
    tok("LINE 官方帳號", 200, 240),
    tok("週五", 460, 240, w=30),
    tok("限時優惠 全站8折 coupon", 200, 266),
    # row 3: 專案群組 (12 unread on avatar)
    tok("12", 80, 320, w=18, h=16),
    tok("專案群組", 200, 320),
    tok("上午9:02", 460, 320, w=54),
    tok("Kevin：我傳了新版的簡報，麻煩看一下", 200, 346),
    # bottom noise: VOOM row + ad label
    tok("AD", 120, 660, w=18, h=10),
    tok("即時戰報看 LINE TODAY", 200, 692),
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


def test_join_tokens_respects_gap():
    a, b = tok("媽媽", 200, 100, w=32), tok("下午2:35", 460, 100, w=60)
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
    assert "永和姐家" in rows[0].preview and "法國" in rows[0].preview  # wrapped
    assert rows[0].unread == 3
    assert rows[0].time_text == "下午4:50"

    assert rows[1].chat_name == "LINE 官方帳號"
    assert rows[1].unread is None
    assert "coupon" in rows[1].preview

    assert rows[2].chat_name == "專案群組"
    assert rows[2].unread == 12
    assert "簡報" in rows[2].preview


def test_parse_sidebar_drops_noise_rows():
    rows = parse_sidebar(FIXTURE, SIDEBAR_W)
    names = [r.chat_name for r in rows]
    assert "AD" not in names
    assert not any("LINE TODAY" in n for n in names)


def test_parse_sidebar_badge_midlist_attaches():
    """中段列的徽章（對齊列跨距內）正確歸屬。"""
    items = [
        tok("媽媽", 202, 100, w=32, h=12),
        tok("下午3:00", 467, 100, w=54, h=12),
        tok("999+", 78, 112, w=30, h=12),  # cy 118 within 周鳳珠 span [140,142]... see next row
        tok("周鳳珠", 202, 160, w=50, h=22),
        tok("下午4:50", 467, 160, w=54, h=22),
    ]
    # fix badge to sit inside 周鳳珠's span instead (y 168 → cy 174)
    items[2] = tok("999+", 78, 168, w=30, h=12)
    rows = parse_sidebar(items, SIDEBAR_W)
    names = {r.chat_name: r.unread for r in rows}
    assert names["周鳳珠"] == 999
    assert names["媽媽"] is None


def test_badge_never_drifts_to_row_below():
    """999+ whose own row (name line) was not OCR-recognized must NOT be
    attached to the next row below (the 'Osmond has 999 unread' bug)."""
    items = [
        tok("999+", 78, 12, w=26, h=12),  # true row above has no OCR text
        tok("Osmond", 184, 48, w=46, h=12),
        tok("下午 3:39", 385, 48, w=46, h=12),
        tok("拿一下衣服", 184, 64, w=80, h=12),
    ]
    rows = parse_sidebar(items, 590.0)
    assert len(rows) == 1
    assert rows[0].chat_name == "Osmond"
    assert rows[0].unread is None  # badge dropped, not misattached


def test_parse_sidebar_caps_rows():
    cfg = {"row_max_count": 2}
    rows = parse_sidebar(FIXTURE, SIDEBAR_W, cfg)
    assert len(rows) == 2


def test_parse_sidebar_name_only_row():
    items = [tok("某人", 200, 100), tok("中午12:00", 450, 100, w=70)]
    rows = parse_sidebar(items, SIDEBAR_W)
    assert len(rows) == 1
    assert rows[0].chat_name == "某人"
    assert rows[0].preview == ""


# --- OCR normalization helpers ----------------------------------------------


def test_normalize_text_strips_edge_punct():
    assert normalize_text("）下午 3:44") == "下午 3:44"
    assert normalize_text("周鳳珠..") == "周鳳珠"


def test_split_trailing_time_variants():
    assert split_trailing_time("周鳳珠 下午450") == ("周鳳珠", "下午450")
    assert split_trailing_time("媽媽 下午 8:30") == ("媽媽", "下午8:30")
    assert split_trailing_time("下午4:50") == ("下午4:50", "")  # no name -> keep whole
    assert split_trailing_time("先約1003下午") == ("先約1003下午", "")


def test_looks_like_time_colonless_needs_prefix():
    assert looks_like_time("下午450")
    assert not looks_like_time("1003")  # bare numbers are NOT times
    assert looks_like_time("12:30")
    assert not looks_like_time("1230")


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


def test_parse_notifications_glued_time_and_orphan_time_rows():
    """Real-world NC dump (2026-09-20): OCR split '晚上8:30' across tokens and
    fullwidth-colon times glued to names — per-token checks missed them, so
    timed titles folded into the previous body and everything cascaded into
    one giant item."""
    items = [
        tok("Microsoft Outlook", 40, 101, h=14),
        tok("21分鐘前", 300, 101, w=50, h=14),
        tok("26E Multiple runs failed", 40, 113, h=14),
        tok("ci.yml, no jobs were run", 40, 133, h=14),  # wrapped body line (real gap)
        tok("昨天", 40, 213, h=14),
        tok("晚上8", 78, 213, w=34, h=14),
        tok(":30", 118, 213, w=18, h=14),  # time split across tokens → whole row is time
        tok("2027秋季 翩然登場～", 40, 245, h=14),  # title-missed notification body
        tok("Microsoft Outlook", 40, 309, h=14),
        tok("下午2：47", 240, 309, w=52, h=14),  # fullwidth colon glued after the name
        tok("我們歡迎您的意見反應！", 40, 323, h=14),
        tok("我們只需要您回答兩個問題。", 40, 339, h=14),
    ]
    notes = parse_notifications(items, 460.0)
    # three separate notifications — never one merged blob, never a time row
    assert len(notes) == 3
    assert [n.chat_name for n in notes] == [
        "Microsoft Outlook",
        "2027秋季 翩然登場～",
        "Microsoft Outlook",
    ]
    assert "ci.yml" in notes[0].body  # close-gap wrap still folds
    assert "2:47" in notes[2].time_text or "2：47" in notes[2].time_text
    assert "兩個問題" in notes[2].body
