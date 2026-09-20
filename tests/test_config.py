"""Config loading tests."""

from __future__ import annotations

from linescreening.config import DEFAULTS, _deep_merge, load_config


def test_defaults_present():
    cfg = load_config()
    assert cfg.jev["model"] == "jev-latest"
    assert cfg.data["retention_days"] >= 1
    assert len(cfg.ocr["recognition_languages"]) >= 2


def test_repo_yaml_overrides_defaults(repo_root):
    cfg = load_config()
    # values from shipped config.yaml must have merged over DEFAULTS
    assert cfg.raw["weights"]["urgency"] == DEFAULTS["weights"]["urgency"]
    assert cfg.raw["thresholds"]["read_soon_priority"] == 0.35


def test_deep_merge_nested():
    base = {"a": {"b": 1, "c": 2}, "d": 3}
    override = {"a": {"b": 9}, "e": 4}
    merged = _deep_merge(base, override)
    assert merged == {"a": {"b": 9, "c": 2}, "d": 3, "e": 4}
    # originals untouched
    assert base["a"]["b"] == 1


def test_user_override_wins(tmp_path):
    (tmp_path / "config.yaml").write_text("data:\n  retention_days: 30\n")
    cfg = load_config(user_dir=tmp_path)
    assert cfg.data["retention_days"] == 30
    # untouched keys keep repo values
    assert cfg.jev["model"] == "jev-latest"
