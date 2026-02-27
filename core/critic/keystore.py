# core/critic/keystore.py — Keyring + env var key storage

from __future__ import annotations

import os
from typing import List, Optional


class CriticKeystore:
    """Resolution order: keyring -> env var -> None."""

    def __init__(self, default_service: str = "judais-lobi"):
        self._default_service = default_service
        self._keyring = _load_keyring()

    def get_key(
        self,
        provider: str,
        env_var: str,
        keyring_key: str,
        keyring_service: Optional[str] = None,
    ) -> Optional[str]:
        service = keyring_service or self._default_service
        if self._keyring is not None and keyring_key:
            try:
                value = self._keyring.get_password(service, keyring_key)
                if value:
                    return value
            except Exception:
                pass
        if env_var:
            return os.getenv(env_var) or None
        return None

    def set_key(self, keyring_key: str, value: str,
                keyring_service: Optional[str] = None) -> bool:
        if self._keyring is None:
            return False
        service = keyring_service or self._default_service
        try:
            self._keyring.set_password(service, keyring_key, value)
            return True
        except Exception:
            return False

    def delete_key(self, keyring_key: str,
                   keyring_service: Optional[str] = None) -> bool:
        if self._keyring is None:
            return False
        service = keyring_service or self._default_service
        try:
            self._keyring.delete_password(service, keyring_key)
            return True
        except Exception:
            return False

    def list_providers_with_keys(self, providers) -> List[str]:
        names: List[str] = []
        for p in providers:
            key = self.get_key(
                p.provider,
                p.api_key_env_var,
                p.keyring_key,
                p.keyring_service,
            )
            if key:
                names.append(p.provider)
        return names


def _load_keyring():
    try:
        import keyring
        return keyring
    except Exception:
        return None
