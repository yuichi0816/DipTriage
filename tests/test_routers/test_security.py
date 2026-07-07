import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

from app.security import BasicAuthMiddleware, OriginCheckMiddleware


def _make_app(password: str | None = None) -> FastAPI:
    app = FastAPI()

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    @app.post("/ping")
    async def ping_post():
        return {"ok": True}

    app.add_middleware(OriginCheckMiddleware)
    if password is not None:
        app.add_middleware(BasicAuthMiddleware, username="user", password=password)
    return app


def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_basic_auth_rejects_without_credentials():
    async with _client(_make_app(password="pw")) as c:
        r = await c.get("/ping")
    assert r.status_code == 401
    assert "www-authenticate" in {k.lower() for k in r.headers}


async def test_basic_auth_accepts_correct_credentials():
    async with _client(_make_app(password="pw")) as c:
        r = await c.get("/ping", auth=("user", "pw"))
    assert r.status_code == 200


async def test_basic_auth_rejects_wrong_password():
    async with _client(_make_app(password="pw")) as c:
        r = await c.get("/ping", auth=("user", "WRONG"))
    assert r.status_code == 401


async def test_no_auth_when_password_not_configured():
    async with _client(_make_app(password=None)) as c:
        r = await c.get("/ping")
    assert r.status_code == 200


async def test_origin_check_blocks_cross_origin_post():
    async with _client(_make_app()) as c:
        r = await c.post("/ping", headers={"Origin": "http://evil.example"})
    assert r.status_code == 403


async def test_origin_check_allows_same_origin_post():
    async with _client(_make_app()) as c:
        r = await c.post("/ping", headers={"Origin": "http://test"})
    assert r.status_code == 200


async def test_origin_check_allows_post_without_origin_header():
    async with _client(_make_app()) as c:
        r = await c.post("/ping")
    assert r.status_code == 200
