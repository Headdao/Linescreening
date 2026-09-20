"""Keychain round-trip tests — ISOLATED test service, never the production
`com.linescreening` entry (a regression here once deleted the user's real
key; the isolation below plus a guard test keeps that from recurring)."""

from __future__ import annotations

import sys

import pytest

from linescreening import keychain

TEST_SERVICE = "com.linescreening.test"


@pytest.fixture()
def clean_entry():
    keychain.delete_key(TEST_SERVICE)
    yield
    keychain.delete_key(TEST_SERVICE)


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS Keychain only")
def test_roundtrip(clean_entry):
    assert keychain.load_key(TEST_SERVICE) is None
    keychain.store_key("sk-test-abc123", TEST_SERVICE)
    assert keychain.load_key(TEST_SERVICE) == "sk-test-abc123"


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS Keychain only")
def test_upsert(clean_entry):
    keychain.store_key("first", TEST_SERVICE)
    keychain.store_key("second", TEST_SERVICE)
    assert keychain.load_key(TEST_SERVICE) == "second"


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS Keychain only")
def test_delete_missing_returns_false():
    keychain.delete_key(TEST_SERVICE)
    assert keychain.delete_key(TEST_SERVICE) is False


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS Keychain only")
def test_services_are_isolated(clean_entry):
    keychain.store_key("test-only", TEST_SERVICE)
    # a test entry must never leak into the production service lookup
    prod = keychain.load_key()  # service default = com.linescreening
    assert prod != "test-only"
