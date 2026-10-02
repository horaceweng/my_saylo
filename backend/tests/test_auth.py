from datetime import timedelta

from sqlmodel import select

from app.models import AuthSession, Invite, User
from app.services import auth
from tests.conftest import PASSWORD


def login(c, name, password=PASSWORD):
    return c.post("/api/auth/login", json={"username": name, "password": password})


def invite_code(admin_client):
    return admin_client.post("/api/admin/invites", json={"days": 7}).json()["code"]


def test_everything_but_auth_and_a_bare_health_needs_a_login(anon_client):
    assert anon_client.get("/api/health").json() == {"ok": True}
    for path in ("/api/media", "/api/phrases", "/api/books", "/api/settings", "/api/admin/users", "/api/auth/me", "/api/tts/status"):
        assert anon_client.get(path).status_code == 401, path
    assert anon_client.post("/api/ai/explain-sentence", json={"sentence": "Hi"}).status_code == 401


def test_health_gives_details_only_to_logged_in_users(client):
    assert "llm_backend" in client.get("/api/health").json()


def test_login_sets_a_safe_cookie_and_me_works(make_client, session):
    auth.create_user(session, "Carol", PASSWORD)
    c = make_client()
    res = login(c, "carol")
    assert res.status_code == 200 and res.json()["username"] == "carol" and res.json()["is_admin"] is False
    cookie = res.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    assert c.get("/api/auth/me").json()["username"] == "carol"
    # only a hash of the token is stored
    token = c.cookies.get("session")
    assert token and all(s.token_hash != token for s in session.exec(select(AuthSession)).all())


def test_secure_flag_follows_the_setting(make_client, session, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "cookie_secure", True)
    auth.create_user(session, "dave", PASSWORD)
    assert "secure" in login(make_client(), "dave").headers["set-cookie"].lower()


def test_wrong_password_and_unknown_user_look_the_same(make_client, session):
    auth.create_user(session, "erin", PASSWORD)
    c = make_client()
    a, b = login(c, "erin", "nope-nope-nope"), login(c, "nobody")
    assert a.status_code == b.status_code == 401 and a.json() == b.json()
    assert c.get("/api/auth/me").status_code == 401


def test_logout_ends_the_session(client):
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/auth/me").status_code == 401


def test_an_invite_works_once(client, make_client):
    code = invite_code(client)
    first, second = make_client(), make_client()
    body = {"code": code, "username": "frank", "password": PASSWORD}
    res = first.post("/api/auth/register", json=body)
    assert res.status_code == 200 and first.get("/api/auth/me").json()["username"] == "frank"
    again = second.post("/api/auth/register", json={**body, "username": "grace"})
    assert again.status_code == 400
    invites = client.get("/api/admin/invites").json()
    assert invites[0]["state"] == "used" and invites[0]["used_by"] == "frank"


def test_invite_that_is_unknown_or_expired_is_refused(client, make_client, session):
    c = make_client()
    body = {"username": "heidi", "password": PASSWORD}
    assert c.post("/api/auth/register", json={**body, "code": "made-up"}).status_code == 400
    code = invite_code(client)
    invite = session.get(Invite, code)
    invite.expires_at = auth.utcnow() - timedelta(minutes=1)
    session.add(invite)
    session.commit()
    assert c.post("/api/auth/register", json={**body, "code": code}).status_code == 400
    assert client.get("/api/admin/invites").json()[0]["state"] == "expired"
    assert session.exec(select(User).where(User.username == "heidi")).first() is None


def test_registration_checks_name_and_password(client, make_client):
    c = make_client()
    code = invite_code(client)
    assert c.post("/api/auth/register", json={"code": code, "username": "x", "password": PASSWORD}).status_code == 400
    assert c.post("/api/auth/register", json={"code": code, "username": "ivan", "password": "short"}).status_code == 400
    assert c.post("/api/auth/register", json={"code": code, "username": "ADMIN", "password": PASSWORD}).status_code == 409
    # none of those used up the code
    assert c.post("/api/auth/register", json={"code": code, "username": "ivan", "password": PASSWORD}).status_code == 200


def test_a_disabled_account_cannot_log_in_and_loses_its_session(client, make_client, session):
    bob = make_client("bob")
    bob_id = session.exec(select(User).where(User.username == "bob")).one().id
    assert client.post(f"/api/admin/users/{bob_id}/disable").status_code == 200
    assert bob.get("/api/auth/me").status_code == 401
    assert login(make_client(), "bob").status_code == 403
    assert client.post(f"/api/admin/users/{bob_id}/enable").status_code == 200
    assert login(make_client(), "bob").status_code == 200


def test_admin_cannot_disable_themselves(client, session):
    me = client.get("/api/auth/me").json()["id"]
    assert client.post(f"/api/admin/users/{me}/disable").status_code == 400


def test_an_expired_session_stops_working(make_client, session):
    auth.create_user(session, "judy", PASSWORD)
    c = make_client()
    login(c, "judy")
    row = session.exec(select(AuthSession)).one()
    row.expires_at = auth.utcnow() - timedelta(seconds=1)
    session.add(row)
    session.commit()
    assert c.get("/api/auth/me").status_code == 401
    assert session.exec(select(AuthSession)).all() == []


def test_admin_pages_are_for_admins(user_client):
    assert user_client.get("/api/admin/users").status_code == 403
    assert user_client.post("/api/admin/invites", json={}).status_code == 403
    assert user_client.get("/api/settings").status_code == 403
    assert user_client.put("/api/settings", json={"llm_model": "x"}).status_code == 403
    assert user_client.post("/api/settings/test/llm").status_code == 403


def test_admin_can_use_settings_and_see_users(client, user_client):
    assert client.get("/api/settings").status_code == 200
    names = [u["username"] for u in client.get("/api/admin/users").json()]
    assert names == ["admin", "alice"]
