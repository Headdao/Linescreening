"""Dashboard tests — server on an ephemeral port, offline mode only
(no screen access, no network, safe for CI)."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import pytest


@pytest.fixture()
def server():
    from linescreening.dashboard import make_server

    srv = make_server(port=0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def _get(url: str) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:  # noqa: S310 — 127.0.0.1 only
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_index_serves_self_contained_html(server):
    status, body = _get(server + "/")
    assert status == 200
    assert "未讀分級".encode() in body
    # fully self-contained: no external assets / CDNs / tracking
    assert b"https://" not in body
    assert b"http://" not in body.replace(b"http://127.0.0.1", b"")


def test_api_triage_offline(server, monkeypatch):
    fake = {
        "ran_at": "2026-09-20T00:00:00+00:00",
        "mode": "offline",
        "warnings": [],
        "chats": [
            {
                "name": "媽媽",
                "verdict": "READ_NOW",
                "label": "值得讀（現在）",
                "priority": 0.9,
                "reasons": ["時間敏感"],
                "low_confidence": False,
                "confidence": 0.9,
                "preview": "今晚吃飯？",
                "unread": 1,
            }
        ],
    }
    monkeypatch.setattr("linescreening.report.collect_triage", lambda **kw: fake)
    status, body = _get(server + "/api/triage?offline=1")
    assert status == 200
    payload = json.loads(body)
    assert payload["mode"] == "offline"
    assert payload["chats"][0]["name"] == "媽媽"
    assert payload["chats"][0]["preview"] == "今晚吃飯？"


def test_api_history_shape(server):
    status, body = _get(server + "/api/history")
    assert status == 200
    assert isinstance(json.loads(body), list)


def test_404(server):
    status, _ = _get(server + "/nope")
    assert status == 404


def test_server_binds_loopback_only():
    from linescreening.dashboard import make_server

    srv = make_server(port=0)
    try:
        assert srv.server_address[0] == "127.0.0.1"
    finally:
        srv.server_close()
