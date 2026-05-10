import logging

from fastapi import APIRouter

from api.auth import authenticate_user, create_token, create_user, require_auth
from api.connection_manager import cache_response
from api.routers.models import LoginRequest, RegisterRequest
from api.utils import json_response as _json_response
from api.utils import rate_limiter

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/auth/login")
@rate_limiter(max_calls=10, time_window=60.0)
async def login(req: LoginRequest):
    user = authenticate_user(req.username, req.password)
    if not user:
        return _json_response(False, error="用户名或密码错误")
    token = create_token(user)
    return _json_response(True, data={
        "token": token,
        "username": user["username"],
        "role": user["role"],
    })


@router.post("/auth/register")
@rate_limiter(max_calls=5, time_window=60.0)
async def register(req: RegisterRequest, current_user: dict | None = None):
    if current_user is None:
        current_user = await require_auth()
    if current_user.get("role") != "admin":
        return _json_response(False, error="仅管理员可创建用户")
    ok = create_user(req.username, req.password)
    if not ok:
        return _json_response(False, error="注册失败：用户名已存在或密码不符合要求")
    return _json_response(True, data={"username": req.username})


@router.get("/auth/me")
async def me(user: dict | None = None):
    if user is None:
        user = await require_auth()
    return _json_response(True, data={
        "username": user.get("sub"),
        "role": user.get("role"),
    })
