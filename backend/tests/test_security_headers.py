from app.security import CSP, HEADERS


def test_every_kind_of_response_carries_the_security_headers(client, anon_client):
    responses = [
        client.get("/api/health"), anon_client.get("/api/health"), anon_client.get("/api/media"),  # 401
        client.get("/api/nothing"), client.get("/"), client.get("/videos/3"), client.post("/api/auth/login", json={"username": "x", "password": "y"}),
    ]
    for res in responses:
        for name, value in HEADERS.items():
            assert res.headers.get(name) == value, (res.request.url, name)


def test_the_policy_allows_what_the_page_needs_and_nothing_more():
    assert "frame-src https://www.youtube.com" in CSP and "script-src 'self' https://www.youtube.com" in CSP
    assert "'unsafe-eval'" not in CSP and "script-src 'self' 'unsafe-inline'" not in CSP
    assert "object-src 'none'" in CSP and "frame-ancestors 'none'" in CSP and "default-src 'self'" in CSP
    assert HEADERS["Permissions-Policy"] == "microphone=(self)" and HEADERS["X-Frame-Options"] == "DENY"


def test_api_answers_are_not_cached_and_https_gets_hsts(client):
    assert client.get("/api/auth/me").headers["cache-control"] == "no-store"
    assert "strict-transport-security" not in client.get("/api/health").headers  # plain http
    from fastapi.testclient import TestClient
    from app.main import app

    secure = TestClient(app, base_url="https://testserver")
    assert secure.get("/api/health").headers["strict-transport-security"].startswith("max-age=")


def test_there_is_no_cors(client):
    res = client.get("/api/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in res.headers
    pre = client.options("/api/media", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in pre.headers
