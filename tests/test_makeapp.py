"""App-bundle builder tests — structure only, never launches the app."""

from __future__ import annotations

import plistlib

import pytest

from linescreening.makeapp import APP_NAME, BUNDLE_ID, build_app


def test_build_app_structure(tmp_path):
    app = build_app(tmp_path, port=8799)
    assert app.name == f"{APP_NAME}.app"
    macos = app / "Contents" / "MacOS"
    launcher = macos / APP_NAME
    embedded = macos / "linescreening-bin"
    assert launcher.is_file() and launcher.stat().st_mode & 0o111
    # the embedded interpreter IS in the bundle (TCC attribution requirement)
    assert embedded.is_file() and embedded.stat().st_mode & 0o111
    text = launcher.read_text(encoding="utf-8")
    assert "linescreening-bin" in text
    assert "PYTHONPATH" in text
    assert "site-packages" in text
    assert "-m linescreening.cli dashboard" in text
    assert "--port 8799" in text


def test_launcher_never_execs_venv_interpreter_directly(tmp_path):
    """The old failure mode: exec'ing .venv python made TCC attribute to
    Homebrew's Python.app instead of Linescreening."""
    app = build_app(tmp_path)
    launcher = (app / "Contents" / "MacOS" / APP_NAME).read_text(encoding="utf-8")
    assert ".venv/bin/linescreening" not in launcher
    assert ".venv/bin/python" not in launcher


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
