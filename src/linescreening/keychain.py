"""API key storage — macOS Keychain via pyobjc Security bindings.

The Typesafe API key never touches the filesystem in plaintext: it lives in
the user's login Keychain under service `com.linescreening`, account
`linescreening`. CI falls back to the TYPESAFE_API_KEY env var.

Tests MUST pass an isolated `service=` (e.g. com.linescreening.test) —
never the production service.
"""

from __future__ import annotations

from typing import Any

from CoreFoundation import kCFBooleanTrue
from Security import (
    SecItemAdd,
    SecItemCopyMatching,
    SecItemDelete,
    kSecAttrAccount,
    kSecAttrService,
    kSecClass,
    kSecClassGenericPassword,
    kSecMatchLimit,
    kSecMatchLimitOne,
    kSecReturnData,
    kSecValueData,
)

from linescreening.guards import KEYCHAIN_SERVICE

_ACCOUNT = "linescreening"
_ERR_SEC_ITEM_NOT_FOUND = -25300


def _base_query(service: str) -> dict[Any, Any]:
    return {
        kSecClass: kSecClassGenericPassword,
        kSecAttrService: service,
        kSecAttrAccount: _ACCOUNT,
    }


def store_key(api_key: str, service: str = KEYCHAIN_SERVICE) -> None:
    """Create or update the Keychain entry (delete + add)."""
    delete_key(service)
    # pyobjc: out-param is None -> returns (status, itemRef)
    outcome = SecItemAdd(
        {**_base_query(service), kSecValueData: api_key.encode("utf-8")},
        None,
    )
    status = outcome[0] if isinstance(outcome, tuple) else outcome
    if status != 0:  # errSecSuccess
        raise RuntimeError(f"SecItemAdd failed with status {status}")


def load_key(service: str = KEYCHAIN_SERVICE) -> str | None:
    """Return the stored key, or None when absent."""
    outcome = SecItemCopyMatching(
        {
            **_base_query(service),
            kSecReturnData: kCFBooleanTrue,
            kSecMatchLimit: kSecMatchLimitOne,
        },
        None,
    )
    outcome = outcome if isinstance(outcome, tuple) else (outcome, None)
    status, data = outcome
    if status == _ERR_SEC_ITEM_NOT_FOUND:
        return None
    if status != 0:
        raise RuntimeError(f"SecItemCopyMatching failed with status {status}")
    return bytes(data).decode("utf-8")


def delete_key(service: str = KEYCHAIN_SERVICE) -> bool:
    """Remove the entry. Returns True when something was deleted."""
    status = SecItemDelete(_base_query(service))
    if status == 0:
        return True
    if status == _ERR_SEC_ITEM_NOT_FOUND:
        return False
    raise RuntimeError(f"SecItemDelete failed with status {status}")


def has_key(service: str = KEYCHAIN_SERVICE) -> bool:
    try:
        return load_key(service) is not None
    except RuntimeError:
        return False
