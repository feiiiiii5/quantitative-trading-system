from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)

_VAULT_ADDR = os.environ.get("VAULT_ADDR", "http://vault:8200")
_VAULT_TOKEN = os.environ.get("VAULT_TOKEN", "")
_VAULT_ROLE = os.environ.get("VAULT_ROLE", "quantcore-service")
_SECRET_MOUNT = os.environ.get("VAULT_SECRET_MOUNT", "quantcore")


@dataclass
class VaultSecret:
    path: str
    data: dict[str, Any]
    version: int = 1
    lease_id: str = ""
    lease_duration: int = 0


class VaultClient:
    def __init__(
        self,
        addr: str = _VAULT_ADDR,
        token: str = _VAULT_TOKEN,
        role: str = _VAULT_ROLE,
        mount: str = _SECRET_MOUNT,
    ) -> None:
        self._addr = addr.rstrip("/")
        self._token = token
        self._role = role
        self._mount = mount
        self._session: Any = None

    def _get_session(self) -> Any:
        if self._session is None:
            try:
                import requests
                self._session = requests.Session()
                self._session.headers.update({"X-Vault-Token": self._token})
            except ImportError:
                raise RuntimeError("requests library required for Vault client") from None
        return self._session

    def _url(self, path: str) -> str:
        return f"{self._addr}/v1/{self._mount}/data/{path}"

    def _meta_url(self, path: str) -> str:
        return f"{self._addr}/v1/{self._mount}/metadata/{path}"

    def read_secret(self, path: str, version: int = 0) -> Optional[VaultSecret]:
        session = self._get_session()
        url = self._url(path)
        params = {}
        if version > 0:
            params["version"] = version
        try:
            resp = session.get(url, params=params)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()
            secret_data = data.get("data", {}).get("data", {})
            metadata = data.get("data", {}).get("metadata", {})
            return VaultSecret(
                path=path,
                data=secret_data,
                version=metadata.get("version", 1),
                lease_id=data.get("lease_id", ""),
                lease_duration=data.get("lease_duration", 0),
            )
        except Exception as e:
            logger.error("Vault read error for %s: %s", path, e)
            return None

    def write_secret(self, path: str, data: dict[str, Any]) -> bool:
        session = self._get_session()
        url = self._url(path)
        payload = {"data": data}
        try:
            resp = session.post(url, json=payload)
            resp.raise_for_status()
            logger.info("Vault secret written: %s", path)
            return True
        except Exception as e:
            logger.error("Vault write error for %s: %s", path, e)
            return False

    def delete_secret(self, path: str) -> bool:
        session = self._get_session()
        url = self._meta_url(path)
        try:
            resp = session.delete(url)
            if resp.status_code in (200, 204):
                logger.info("Vault secret deleted: %s", path)
                return True
            return False
        except Exception as e:
            logger.error("Vault delete error for %s: %s", path, e)
            return False

    def list_secrets(self, path: str = "") -> list[str]:
        session = self._get_session()
        url = f"{self._addr}/v1/{self._mount}/metadata/{path}"
        try:
            resp = session.get(url)
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            keys = resp.json().get("data", {}).get("keys", [])
            return keys
        except Exception as e:
            logger.error("Vault list error for %s: %s", path, e)
            return []

    def get_database_credentials(self, role: str = "quantcore-readonly") -> Optional[dict[str, str]]:
        url = f"{self._addr}/v1/database/creds/{role}"
        session = self._get_session()
        try:
            resp = session.get(url)
            resp.raise_for_status()
            data = resp.json().get("data", {})
            return {
                "username": data.get("username", ""),
                "password": data.get("password", ""),
            }
        except Exception as e:
            logger.error("Vault DB credential error: %s", e)
            return None


def load_secrets_from_vault(paths: list[str]) -> dict[str, Any]:
    client = VaultClient()
    secrets: dict[str, Any] = {}
    for path in paths:
        secret = client.read_secret(path)
        if secret is not None:
            secrets[path] = secret.data
        else:
            logger.warning("Secret not found in Vault: %s", path)
    return secrets


def inject_env_from_vault(prefix: str = "QUANTCORE_") -> None:
    client = VaultClient()
    keys = client.list_secrets()
    for key in keys:
        if key.endswith("/"):
            continue
        secret = client.read_secret(key)
        if secret is not None:
            for k, v in secret.data.items():
                env_key = f"{prefix}{key.replace('/', '_').upper()}_{k.upper()}"
                os.environ.setdefault(env_key, str(v))


__all__ = [
    "VaultClient",
    "VaultSecret",
    "load_secrets_from_vault",
    "inject_env_from_vault",
]
