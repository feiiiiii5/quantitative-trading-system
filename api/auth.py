import hmac
import logging
import os
import secrets
import threading
import time
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)

JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 24

_SECRET_FILE = os.path.join(os.path.dirname(__file__), "..", "data", ".jwt_secret")


def _load_or_create_secret() -> str:
    env_secret = os.environ.get("JWT_SECRET")
    if env_secret and len(env_secret) >= 32:
        return env_secret

    try:
        os.makedirs(os.path.dirname(_SECRET_FILE), exist_ok=True)
        if os.path.exists(_SECRET_FILE):
            with open(_SECRET_FILE) as f:
                stored = f.read().strip()
            if stored and len(stored) >= 32:
                return stored

        new_secret = secrets.token_hex(32)
        with open(_SECRET_FILE, "w") as f:
            f.write(new_secret)
        os.chmod(_SECRET_FILE, 0o600)
        logger.info("Generated new JWT secret and saved to %s", _SECRET_FILE)
        return new_secret
    except OSError as e:
        logger.warning("Could not persist JWT secret to file: %s. Using ephemeral secret.", e)
        return secrets.token_hex(32)


JWT_SECRET = _load_or_create_secret()

_bearer = HTTPBearer(auto_error=False)

try:
    import bcrypt

    def _hash_password(password: str) -> str:
        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")

    def _verify_password(password: str, password_hash: str) -> bool:
        try:
            return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
        except (ValueError, TypeError):
            return False

    _HAS_BCRYPT = True
    logger.info("bcrypt available — using secure password hashing")
except ImportError:
    import hashlib

    _PEPPER = os.environ.get("PASSWORD_PEPPER") or secrets.token_hex(32)
    _PBKDF2_ITERATIONS = 600_000

    def _hash_password(password: str) -> str:
        salt = secrets.token_hex(16)
        h = hashlib.pbkdf2_hmac(
            "sha256",
            f"{salt}{password}{_PEPPER}".encode(),
            salt.encode(),
            _PBKDF2_ITERATIONS,
        ).hex()
        return f"{salt}${h}"

    def _verify_password(password: str, password_hash: str) -> bool:
        try:
            salt, h = password_hash.split("$", 1)
            computed = hashlib.pbkdf2_hmac(
                "sha256",
                f"{salt}{password}{_PEPPER}".encode(),
                salt.encode(),
                _PBKDF2_ITERATIONS,
            ).hex()
            return hmac.compare_digest(computed, h)
        except (ValueError, AttributeError):
            return False

    _HAS_BCRYPT = False
    logger.warning("bcrypt not installed — using PBKDF2 fallback with per-user salts. Install bcrypt for production.")


def _get_users_table(db):
    db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user',
            created_at REAL NOT NULL
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)")


_init_done = False


def ensure_default_user():
    global _init_done
    if _init_done:
        return
    _init_done = True
    init_default_user()


def init_default_user():
    from core.database import get_db
    db = get_db()
    _get_users_table(db)

    existing = db.fetchone("SELECT username FROM users WHERE username=?", ("admin",))
    if existing:
        return

    default_password = os.environ.get("QUANTCORE_ADMIN_PASSWORD")
    if not default_password:
        default_password = secrets.token_urlsafe(16)
        logger.warning(
            "No QUANTCORE_ADMIN_PASSWORD env var set — generated random password for initial admin user. "
            "Save this password and set QUANTCORE_ADMIN_PASSWORD env var for subsequent runs. "
            "Admin password for this session: %s", default_password
        )
    else:
        logger.info("Admin user created with password from QUANTCORE_ADMIN_PASSWORD env var.")
    db.execute(
        "INSERT INTO users (username, password_hash, role, created_at) VALUES (?, ?, ?, ?)",
        ("admin", _hash_password(default_password), "admin", time.time()),
    )


def create_user(username: str, password: str, role: str = "user") -> bool:
    if not username or len(username) < 2 or len(username) > 32:
        return False
    if not password or len(password) < 8:
        return False
    if role not in ("user", "admin"):
        return False
    from core.database import get_db
    db = get_db()
    _get_users_table(db)

    existing = db.fetchone("SELECT username FROM users WHERE username=?", (username,))
    if existing:
        return False

    db.execute(
        "INSERT INTO users (username, password_hash, role, created_at) VALUES (?, ?, ?, ?)",
        (username, _hash_password(password), role, time.time()),
    )
    return True


def authenticate_user(username: str, password: str) -> dict | None:
    from core.database import get_db
    db = get_db()
    _get_users_table(db)

    row = db.fetchone("SELECT username, password_hash, role FROM users WHERE username=?", (username,))
    if not row:
        return None

    if not _verify_password(password, row["password_hash"]):
        return None

    return {"username": row["username"], "role": row["role"]}


def create_token(user: dict) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": user["username"],
        "role": user["role"],
        "iat": now,
        "exp": now + timedelta(hours=JWT_EXPIRE_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = None,
) -> dict | None:
    if credentials is None:
        credentials = await _bearer.__call__(None)  # type: ignore[arg-type]
    if credentials is None:
        return None
    payload = decode_token(credentials.credentials)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
    return payload


async def require_auth(
    user: dict | None = None,
) -> dict:
    if user is None:
        user = await get_current_user()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    return user


class APIAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, api_key: str = "", enabled: bool = False):
        super().__init__(app)
        self._api_key = api_key
        self._enabled = enabled
        self._rate_limits: dict[str, list[float]] = {}
        self._rate_lock = threading.Lock()
        self._max_clients = 1000
        self._rate_limit_per_minute = 60 if enabled else 600
        self._cleanup_interval = 300
        self._last_cleanup = time.monotonic()

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path.startswith("/docs") or request.url.path.startswith("/openapi"):
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        now = time.time()
        now_mono = time.monotonic()

        with self._rate_lock:
            if now_mono - self._last_cleanup >= self._cleanup_interval:
                self._cleanup_stale_clients(now)
                self._last_cleanup = now_mono

            if client_ip not in self._rate_limits:
                if len(self._rate_limits) >= self._max_clients:
                    self._cleanup_stale_clients(now)
                    if len(self._rate_limits) >= self._max_clients:
                        return Response(status_code=429, content='{"success":false,"error":"Too many clients"}')
                self._rate_limits[client_ip] = []

            self._rate_limits[client_ip] = [t for t in self._rate_limits[client_ip] if now - t < 60]
            if len(self._rate_limits[client_ip]) >= self._rate_limit_per_minute:
                return Response(status_code=429, content='{"success":false,"error":"Rate limit exceeded"}')
            self._rate_limits[client_ip].append(now)

        if self._enabled and self._api_key:
            api_key = request.headers.get("X-API-Key", "")
            if not hmac.compare_digest(api_key, self._api_key):
                return Response(status_code=401, content='{"success":false,"error":"Invalid API key"}')

        return await call_next(request)

    def _cleanup_stale_clients(self, now: float):
        stale = [ip for ip, times in self._rate_limits.items()
                 if all(now - t > 60 for t in times)]
        for ip in stale:
            del self._rate_limits[ip]

