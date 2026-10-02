import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.config import settings
from app.services import ratelimit


def request(peer, forwarded=None):
    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded else []
    return Request({"type": "http", "client": (peer, 5000), "headers": headers})


def test_a_forwarded_address_is_only_believed_from_this_machine():
    assert ratelimit.client_ip(request("127.0.0.1", "203.0.113.9")) == "203.0.113.9"
    assert ratelimit.client_ip(request("127.0.0.1")) == "127.0.0.1"
    assert ratelimit.client_ip(request("192.168.1.20", "203.0.113.9")) == "192.168.1.20"  # anyone can write that header
    assert ratelimit.client_ip(request("100.64.0.7", "203.0.113.9")) == "100.64.0.7"


def test_only_the_address_our_own_proxy_added_is_used():
    assert ratelimit.client_ip(request("127.0.0.1", "1.2.3.4, 203.0.113.9")) == "203.0.113.9"  # 1.2.3.4 came from the caller


def test_the_limit_is_per_minute_and_slides():
    for i in range(3):
        ratelimit.hit("k", 3, "操作", now=100.0 + i)
    with pytest.raises(HTTPException) as e:
        ratelimit.hit("k", 3, "操作", now=105.0)
    assert e.value.status_code == 429 and "秒後再試" in e.value.detail and int(e.value.headers["Retry-After"]) in range(50, 60)
    ratelimit.hit("other", 3, "操作", now=105.0)  # another key is not affected
    ratelimit.hit("k", 3, "操作", now=161.0)  # the first hit is a minute old now


def test_quiet_keys_are_forgotten():
    ratelimit.hit("old", 5, "操作", now=1.0)
    ratelimit.hit("new", 5, "操作", now=500.0)
    assert "old" not in ratelimit._hits


def test_logins_are_limited_per_address(anon_client, session, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_auth_per_minute", 3)
    bad = {"username": "nobody", "password": "wrong password"}
    for _ in range(3):
        assert anon_client.post("/api/auth/login", json=bad).status_code == 401
    res = anon_client.post("/api/auth/login", json=bad, headers={"X-Forwarded-For": "198.51.100.7"})  # a made-up address does not help
    assert res.status_code == 429 and "登入" in res.json()["detail"] and "Retry-After" in res.headers
    assert anon_client.post("/api/auth/register", json={**bad, "code": "x"}).status_code == 429  # sign-up shares the count


def test_the_limit_for_logins_is_ten_by_default():
    assert settings.rate_limit_auth_per_minute == 10 and settings.rate_limit_api_per_minute == 120


def test_api_calls_are_limited_per_user(user_client, other_client, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_api_per_minute", 5)
    for _ in range(5):
        assert user_client.get("/api/phrases").status_code == 200
    res = user_client.get("/api/phrases")
    assert res.status_code == 429 and "秒後再試" in res.json()["detail"]
    assert other_client.get("/api/phrases").status_code == 200  # someone else is not affected


def test_a_bare_health_check_is_not_limited(anon_client, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_api_per_minute", 1)
    for _ in range(5):
        assert anon_client.get("/api/health").status_code == 200


def test_uvicorns_proxy_header_handling_and_ours_agree():
    """With --proxy-headers uvicorn rewrites request.client before our code runs; the answer must not change."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

    app = FastAPI()

    @app.get("/ip")
    def ip(request: Request):
        return {"ip": ratelimit.client_ip(request)}

    behind_uvicorn = TestClient(ProxyHeadersMiddleware(app, trusted_hosts="127.0.0.1"), client=("127.0.0.1", 5000))
    alone = TestClient(app, client=("127.0.0.1", 5000))
    for forwarded in ("203.0.113.9", "1.2.3.4, 203.0.113.9", "6.6.6.6, 7.7.7.7, 203.0.113.9"):
        got = [c.get("/ip", headers={"X-Forwarded-For": forwarded}).json()["ip"] for c in (behind_uvicorn, alone)]
        assert got == ["203.0.113.9", "203.0.113.9"], forwarded
    for peer in ("192.168.1.20", "100.64.0.7"):  # not the proxy: the header is ignored by both
        for c in (TestClient(ProxyHeadersMiddleware(app, trusted_hosts="127.0.0.1"), client=(peer, 5000)), TestClient(app, client=(peer, 5000))):
            assert c.get("/ip", headers={"X-Forwarded-For": "203.0.113.9"}).json()["ip"] == peer
