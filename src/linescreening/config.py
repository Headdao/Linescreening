"""Configuration loading.

Resolution order (later wins):
1. Built-in defaults (DEFAULTS below)
2. <repo>/config.yaml  (shipped, tuned values)
3. ~/.linescreening/config.yaml (user overrides, optional)

All tunables live in YAML so they can be adjusted without touching code.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

# Repo root = .../src/linescreening/config.py -> parents[2]
REPO_ROOT = Path(__file__).resolve().parents[2]
USER_CONFIG_DIR = Path.home() / ".linescreening"

DEFAULTS: dict[str, Any] = {
    "jev": {"model": "jev-latest", "timeout_s": 5.0},
    "weights": {
        "urgency": 0.30,
        "importance": 0.30,
        "expects_reply": 0.20,
        "asks_action": 0.10,
        "time_sensitive": 0.10,
        "automated_broadcast_penalty": 0.25,
        "casual_social_penalty": 0.10,
    },
    "thresholds": {
        "read_now_urgency_norm": 0.50,
        "read_now_expects_reply": 0.60,
        "read_soon_priority": 0.35,
        "can_skip_automated": 0.70,
        "can_skip_casual": 0.80,
        "low_confidence": 0.50,
    },
    "ocr": {
        "recognition_languages": ["zh-Hant", "zh-Hans", "en-US"],
        "min_confidence": 0.3,
    },
    "sidebar": {"width_fraction": 0.98, "top_inset_fraction": 0.15, "row_max_count": 40},
    "nc_panel": {"width_fraction": 0.30, "capture_settle_s": 0.7},
    "data": {"retention_days": 3, "db_path": "~/.linescreening/linescreening.sqlite"},
    "watcher": {
        "interval_s": 0.6,
        "banner_region_fraction_w": 0.25,
        "banner_region_px_h": 260,
    },
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return data if isinstance(data, dict) else {}


@dataclass(frozen=True)
class Config:
    raw: dict[str, Any]

    @property
    def jev(self) -> dict[str, Any]:
        return self.raw["jev"]

    @property
    def weights(self) -> dict[str, float]:
        return self.raw["weights"]

    @property
    def thresholds(self) -> dict[str, float]:
        return self.raw["thresholds"]

    @property
    def ocr(self) -> dict[str, Any]:
        return self.raw["ocr"]

    @property
    def sidebar(self) -> dict[str, Any]:
        return self.raw["sidebar"]

    @property
    def nc_panel(self) -> dict[str, Any]:
        return self.raw["nc_panel"]

    @property
    def data(self) -> dict[str, Any]:
        return self.raw["data"]

    @property
    def watcher(self) -> dict[str, Any]:
        return self.raw["watcher"]

    @property
    def db_path(self) -> Path:
        return Path(str(self.data["db_path"])).expanduser()


def load_config(user_dir: Path | None = None) -> Config:
    """Merge defaults <- repo config.yaml <- user config.yaml."""
    user_dir = user_dir if user_dir is not None else USER_CONFIG_DIR
    merged = _deep_merge(DEFAULTS, _read_yaml(REPO_ROOT / "config.yaml"))
    merged = _deep_merge(merged, _read_yaml(user_dir / "config.yaml"))
    return Config(raw=merged)
