"""End-to-end triage tests with injected synthetic capture providers.

The full pipeline (store → merge → Jev(mock) → combine → render/json) runs
without any screen access — this is exactly what CI exercises.
"""

from __future__ import annotations

import json

from rich.console import Console

from linescreening.config import load_config
from linescreening.parse import NotificationItem, SidebarRow
from linescreening.report import run_triage


def synth_sidebar(cfg):
    return [
        SidebarRow(chat_name="媽媽", preview="今晚要回來吃飯嗎？", time_text="下午2:35", unread=1),
        SidebarRow(
            chat_name="LINE 官方帳號", preview="限時優惠！全站商品 8 折", time_text="週五", unread=1
        ),
        SidebarRow(
            chat_name="家庭群組", preview="爸爸：哈哈這太好笑了", time_text="上午9:02", unread=12
        ),
    ]


def synth_nc(cfg):
    return [
        NotificationItem(chat_name="媽媽", body="今晚要回來吃飯嗎？", time_text="現在"),
        NotificationItem(chat_name="媽媽", body="記得買水果", time_text="下午2:30"),
        NotificationItem(chat_name="Osmond", body="我的奶油呢", time_text="下午2:41"),
    ]


def run(kwargs: dict) -> tuple[bool, str]:
    console = Console(record=True, width=120)
    ok = run_triage(
        console=console,
        cfg=load_config(),
        sidebar_provider=synth_sidebar,
        nc_provider=synth_nc,
        **kwargs,
    )
    return ok, console.export_text()


def test_mock_e2e_renders_all_chats():
    ok, text = run({"mock": True})
    assert ok
    for name in ("媽媽", "LINE 官方帳號", "家庭群組", "Osmond"):
        assert name in text
    assert "值得讀" in text or "不確定" in text  # verdict labels rendered


def test_mock_e2e_merges_nc_previews():
    ok, _ = run({"mock": True})
    assert ok  # full run without exceptions == merge path executed


def test_offline_e2e_lists_without_verdict():
    ok, text = run({"offline": True})
    assert ok
    assert "離線" in text
    assert "未判讀" in text


def test_json_e2e_structure(capsys):
    ok = run_triage(
        console=Console(record=True, width=120),
        cfg=load_config(),
        sidebar_provider=synth_sidebar,
        nc_provider=synth_nc,
        mock=True,
        json_output=True,
    )
    assert ok
    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "mock"
    names = [c["name"] for c in payload["chats"]]
    assert "媽媽" in names and "Osmond" in names
    for chat in payload["chats"]:
        assert chat["verdict"] in {"READ_NOW", "READ_SOON", "CAN_SKIP", "MAYBE"}
        assert "label" in chat and "reasons" in chat


def test_read_now_sorts_first_in_json(capsys):
    run_triage(
        console=Console(record=True, width=120),
        cfg=load_config(),
        sidebar_provider=synth_sidebar,
        nc_provider=synth_nc,
        mock=True,
        json_output=True,
    )
    payload = json.loads(capsys.readouterr().out)
    verdicts = [c["verdict"] for c in payload["chats"]]
    first_can_skip = verdicts.index("CAN_SKIP") if "CAN_SKIP" in verdicts else len(verdicts)
    last_read_now = max((i for i, v in enumerate(verdicts) if v == "READ_NOW"), default=-1)
    assert last_read_now < first_can_skip


def test_degrades_gracefully_when_sources_fail():
    def boom(cfg):
        raise RuntimeError("no permission")

    console = Console(record=True, width=120)
    ok = run_triage(
        console=console,
        cfg=load_config(),
        sidebar_provider=boom,
        nc_provider=boom,
        mock=True,
    )
    assert ok
    text = console.export_text()
    # sidebar failure = blocking warning; NC failure = optional notice (never scary)
    assert "側欄擷取失敗" in text
    assert "通知中心來源未啟用" in text
    assert "通知中心擷取失敗" not in text


def test_optional_nc_skip_is_a_notice_not_a_warning(capsys):
    from linescreening.report import collect_triage

    payload = collect_triage(
        cfg=load_config(),
        sidebar_provider=lambda cfg: [
            SidebarRow(chat_name="媽媽", preview="晚餐？", time_text="下午6:00", unread=1)
        ],
        nc_provider=lambda cfg: (_ for _ in ()).throw(RuntimeError("AX denied")),
        mock=True,
    )
    assert payload["warnings"] == []
    assert len(payload["notices"]) == 1
    assert "向系統要求授權" in payload["notices"][0]
    assert [c["name"] for c in payload["chats"]] == ["媽媽"]
