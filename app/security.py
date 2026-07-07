"""アクセス制御ミドルウェア（監査 4-1, 4-2）。

- BasicAuthMiddleware: DIPTRIAGE_PASSWORD 設定時のみ main.py で有効化される全ルート Basic 認証。
- OriginCheckMiddleware: Origin ヘッダ付き POST が自ホスト以外から来た場合に拒否（CSRF 対策）。
"""
from __future__ import annotations

import base64
import secrets
from urllib.parse import urlparse

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class BasicAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, username: str, password: str):
        super().__init__(app)
        self._username = username
        self._password = password

    async def dispatch(self, request: Request, call_next):
        header = request.headers.get("authorization", "")
        if header.lower().startswith("basic "):
            try:
                decoded = base64.b64decode(header[6:]).decode("utf-8")
            except Exception:
                decoded = ""
            user, _, password = decoded.partition(":")
            if secrets.compare_digest(user, self._username) and secrets.compare_digest(
                password, self._password
            ):
                return await call_next(request)
        return Response(
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="DipTriage"'},
        )


class OriginCheckMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method == "POST":
            origin = request.headers.get("origin")
            if origin:
                origin_host = urlparse(origin).netloc
                if origin_host and origin_host != request.headers.get("host", ""):
                    return Response("Forbidden: cross-origin POST", status_code=403)
        return await call_next(request)
