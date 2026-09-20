"""App-bundle builder tests — structure only, never launches the app."""

from __future__ import annotations

import plistlib

import pytest

from linescreening.makeapp import APP_NAME, BUNDLE_ID, build_app


def test_build_app_structure(tmp_path):
    app = build_app(tmp_path, port=8799)
    assert app.name == f"{APP_NAME}.app"
    launcher = app / "Contents" / "MacOS" / APP_NAME
    assert launcher.is_file()
    assert launcher.stat().st_mode & 0o111, "launcher must be executable"
    # launcher points at the repo venv and the dashboard with our port
    text = launcher.read_text(encoding="utf-8")
    assert "dashboard" in text and "--port 8799" in text
    assert "linescreening" in text


def test_info_plist_content(tmp_path):
    app = build_app(tmp_path)
    plist = plistlib.loads((app / "Contents" / "Info.plist").read_bytes())
    assert plist["CFBundleIdentifier"] == BUNDLE_ID
    assert plist["CFBundleExecutable"] == APP_NAME
    assert plist["CFBundlePackageType"] == "APPL"


def test_build_is_idempotent(tmp_path):
    build_app(tmp_path)
    build_app(tmp_path)  # overwrite without error


def test_missing_venv_raises(tmp_path, monkeypatch):
    from linescreening import makeapp

    monkeypatch.setattr(makeapp, "REPO_ROOT", tmp_path)
    with pytest.raises(RuntimeError, match="uv sync"):
        build_app(tmp_path / "out")
