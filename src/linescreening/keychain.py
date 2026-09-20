"""API key storage — macOS Keychain via pyobjc Security bindings.

The Typesafe API key never touches the filesystem in plaintext: it lives in
the user's login Keychain under service `com.linescreening`, account
`linescreening`. CI falls back to the TYPESAFE_API_KEY env var.
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


def _base_query() -> dict[Any, Any]:
    return {
        kSecClass: kSecClassGenericPassword,
        kSecAttrService: KEYCHAIN_SERVICE,
        kSecAttrAccount: _ACCOUNT,
    }


def store_key(api_key: str) -> None:
    """Create or update the Keychain entry (delete + add)."""
    delete_key()
    # pyobjc: out-param is None -> returns (status, itemRef)
    outcome = SecItemAdd(
        {**_base_query(), kSecValueData: api_key.encode("utf-8")},
        None,
    )
    status = outcome[0] if isinstance(outcome, tuple) else outcome
    if status != 0:  # errSecSuccess
        raise RuntimeError(f"SecItemAdd failed with status {status}")


def load_key() -> str | None:
    """Return the stored key, or None when absent."""
    outcome = SecItemCopyMatching(
        {
            **_base_query(),
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


def delete_key() -> bool:
    """Remove the entry. Returns True when something was deleted."""
    status = SecItemDelete(_base_query())
    if status == 0:
        return True
    if status == _ERR_SEC_ITEM_NOT_FOUND:
        return False
    raise RuntimeError(f"SecItemDelete failed with status {status}")


def has_key() -> bool:
    try:
        return load_key() is not None
    except RuntimeError:
        return False
