from __future__ import annotations

import hashlib
import hmac
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


class Role(str, Enum):
    ADMIN = "admin"
    TRADER = "trader"
    RISK_MANAGER = "risk_manager"
    VIEWER = "viewer"
    STRATEGY_DEV = "strategy_dev"


class Permission(str, Enum):
    TRADE_EXECUTE = "trade:execute"
    TRADE_CANCEL = "trade:cancel"
    TRADE_VIEW = "trade:view"
    STRATEGY_DEPLOY = "strategy:deploy"
    STRATEGY_STOP = "strategy:stop"
    STRATEGY_VIEW = "strategy:view"
    RISK_CONFIGURE = "risk:configure"
    RISK_VIEW = "risk:view"
    PORTFOLIO_MANAGE = "portfolio:manage"
    PORTFOLIO_VIEW = "portfolio:view"
    ADMIN_USERS = "admin:users"
    ADMIN_SYSTEM = "admin:system"


ROLE_PERMISSIONS: dict[Role, set[Permission]] = {
    Role.ADMIN: set(Permission),
    Role.TRADER: {
        Permission.TRADE_EXECUTE,
        Permission.TRADE_CANCEL,
        Permission.TRADE_VIEW,
        Permission.STRATEGY_VIEW,
        Permission.RISK_VIEW,
        Permission.PORTFOLIO_VIEW,
    },
    Role.RISK_MANAGER: {
        Permission.TRADE_VIEW,
        Permission.RISK_CONFIGURE,
        Permission.RISK_VIEW,
        Permission.PORTFOLIO_VIEW,
        Permission.STRATEGY_VIEW,
    },
    Role.VIEWER: {
        Permission.TRADE_VIEW,
        Permission.STRATEGY_VIEW,
        Permission.RISK_VIEW,
        Permission.PORTFOLIO_VIEW,
    },
    Role.STRATEGY_DEV: {
        Permission.STRATEGY_DEPLOY,
        Permission.STRATEGY_STOP,
        Permission.STRATEGY_VIEW,
        Permission.TRADE_VIEW,
        Permission.RISK_VIEW,
        Permission.PORTFOLIO_VIEW,
    },
}


@dataclass
class User:
    user_id: str
    username: str
    roles: set[Role]
    api_key_hash: str = ""
    is_active: bool = True

    def has_permission(self, permission: Permission) -> bool:
        if not self.is_active:
            return False
        return any(permission in ROLE_PERMISSIONS.get(role, set()) for role in self.roles)

    def has_any_permission(self, permissions: set[Permission]) -> bool:
        return any(self.has_permission(p) for p in permissions)


class RBACManager:
    def __init__(self) -> None:
        self._users: dict[str, User] = {}

    def create_user(
        self,
        user_id: str,
        username: str,
        roles: set[Role],
        api_key: str = "",
    ) -> User:
        api_key_hash = ""
        if api_key:
            api_key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        user = User(
            user_id=user_id,
            username=username,
            roles=roles,
            api_key_hash=api_key_hash,
        )
        self._users[user_id] = user
        logger.info("User created: %s with roles %s", username, [r.value for r in roles])
        return user

    def get_user(self, user_id: str) -> Optional[User]:
        return self._users.get(user_id)

    def authenticate(self, user_id: str, api_key: str) -> Optional[User]:
        user = self._users.get(user_id)
        if user is None or not user.is_active:
            return None
        expected = hashlib.sha256(api_key.encode()).hexdigest()
        if not hmac.compare_digest(user.api_key_hash, expected):
            return None
        return user

    def check_permission(self, user_id: str, permission: Permission) -> bool:
        user = self._users.get(user_id)
        if user is None:
            return False
        return user.has_permission(permission)

    def deactivate_user(self, user_id: str) -> bool:
        user = self._users.get(user_id)
        if user is None:
            return False
        user.is_active = False
        logger.info("User deactivated: %s", user.username)
        return True


@dataclass
class AuditEntry:
    entry_id: str
    user_id: str
    action: str
    resource_type: str
    resource_id: str
    details: dict[str, Any]
    timestamp_ns: int
    ip_address: str = ""
    success: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "user_id": self.user_id,
            "action": self.action,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "details": self.details,
            "timestamp_ns": self.timestamp_ns,
            "ip_address": self.ip_address,
            "success": self.success,
        }


class AuditLogger:
    def __init__(self, max_entries: int = 100_000) -> None:
        self._entries: list[AuditEntry] = []
        self._max_entries = max_entries

    def log(
        self,
        user_id: str,
        action: str,
        resource_type: str,
        resource_id: str,
        details: Optional[dict[str, Any]] = None,
        ip_address: str = "",
        success: bool = True,
    ) -> AuditEntry:
        import uuid

        entry = AuditEntry(
            entry_id=uuid.uuid4().hex,
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details or {},
            timestamp_ns=int(time.time() * 1e9),
            ip_address=ip_address,
            success=success,
        )
        self._entries.append(entry)
        if len(self._entries) > self._max_entries:
            self._entries = self._entries[-self._max_entries // 2 :]
        logger.info(
            "AUDIT: user=%s action=%s resource=%s/%s success=%s",
            user_id,
            action,
            resource_type,
            resource_id,
            success,
        )
        return entry

    def query(
        self,
        user_id: Optional[str] = None,
        action: Optional[str] = None,
        resource_type: Optional[str] = None,
        since_ns: Optional[int] = None,
        limit: int = 100,
    ) -> list[AuditEntry]:
        results = self._entries
        if user_id is not None:
            results = [e for e in results if e.user_id == user_id]
        if action is not None:
            results = [e for e in results if e.action == action]
        if resource_type is not None:
            results = [e for e in results if e.resource_type == resource_type]
        if since_ns is not None:
            results = [e for e in results if e.timestamp_ns >= since_ns]
        return results[-limit:]


class APISigner:
    def __init__(self, secret_key: str) -> None:
        self._secret_key = secret_key.encode("utf-8")

    def sign(self, method: str, path: str, timestamp_ns: int, body: str = "") -> str:
        message = f"{method.upper()}\n{path}\n{timestamp_ns}\n{body}"
        return hmac.new(self._secret_key, message.encode("utf-8"), hashlib.sha256).hexdigest()

    def verify(
        self,
        method: str,
        path: str,
        timestamp_ns: int,
        signature: str,
        body: str = "",
        max_drift_ns: int = 300_000_000_000,
    ) -> bool:
        now_ns = int(time.time() * 1e9)
        if abs(now_ns - timestamp_ns) > max_drift_ns:
            return False
        expected = self.sign(method, path, timestamp_ns, body)
        return hmac.compare_digest(expected, signature)


__all__ = [
    "Role",
    "Permission",
    "ROLE_PERMISSIONS",
    "User",
    "RBACManager",
    "AuditEntry",
    "AuditLogger",
    "APISigner",
]
