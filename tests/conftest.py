"""Shared test fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from linescreening.config import Config, load_config


@pytest.fixture()
def repo_root() -> Path:
    from linescreening.config import REPO_ROOT

    return REPO_ROOT


@pytest.fixture()
def config() -> Config:
    return load_config()
