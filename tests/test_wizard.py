"""Wizard unit tests — pure logic bits (no TCC, no interactivity)."""

from __future__ import annotations

from linescreening.db import Store
from linescreening.setup_wizard import STEPS, _load_progress, _save_progress, parse_mode_choice


def test_step_registry_covers_plan():
    keys = [s.key for s in STEPS]
    assert keys == ["env", "screen", "ax", "notify", "key", "watcher", "smoke", "summary"]


def test_mode_choice_aliases():
    for raw in ("1", "q", "quiet", "安靜", " Quiet "):
        assert parse_mode_choice(raw) == "quiet"
    for raw in ("2", "b", "banner", "橫幅"):
        assert parse_mode_choice(raw) == "banner"
    for raw in ("3", "o", "off", "關閉"):
        assert parse_mode_choice(raw) == "off"


def test_mode_choice_invalid():
    assert parse_mode_choice("") is None
    assert parse_mode_choice("banana") is None
    assert parse_mode_choice("12") is None


def test_progress_roundtrip(tmp_path):
    store = Store(tmp_path / "t.sqlite")
    assert _load_progress(store) == {}
    _save_progress(store, {"env": True, "screen": False})
    assert _load_progress(store) == {"env": True, "screen": False}
    store.close()


def test_progress_survives_corrupt_meta(tmp_path):
    store = Store(tmp_path / "t.sqlite")
    store.set_meta("setup_progress", "{not json")
    assert _load_progress(store) == {}
    store.close()
