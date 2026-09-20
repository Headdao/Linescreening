"""Keychain round-trip tests (uses a dedicated test entry, cleans up after)."""

from __future__ import annotations

import sys

import pytest

from linescreening import keychain


@pytest.fixture()
def clean_entry():
    keychain.delete_key()
    yield
    keychain.delete_key()


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS Keychain only")
def test_roundtrip(clean_entry):
    assert keychain.load_key() is None
    keychain.store_key("sk-test-abc123")
    assert keychain.load_key() == "sk-test-abc123"


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS Keychain only")
def test_upsert(clean_entry):
    keychain.store_key("first")
    keychain.store_key("second")
    assert keychain.load_key() == "second"


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS Keychain only")
def test_delete_missing_returns_false():
    keychain.delete_key()
    assert keychain.delete_key() is False
