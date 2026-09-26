import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.frontend import mount_frontend


@pytest.fixture
def site(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>APP</html>")
    (dist / "assets" / "app.js").write_text("console.log('js')")
    (dist / "favicon.svg").write_text("<svg/>")
    (tmp_path / "secret.txt").write_text("do not serve")
    app = FastAPI()

    @app.get("/api/ping")
    def ping():
        return {"pong": True}

    assert mount_frontend(app, dist) is True
    return TestClient(app)


def test_the_page_assets_and_the_api_all_come_from_one_server(site):
    assert "APP" in site.get("/").text
    assert site.get("/assets/app.js").text == "console.log('js')"
    assert site.get("/favicon.svg").text == "<svg/>"
    assert site.get("/api/ping").json() == {"pong": True}


def test_addresses_of_the_app_get_the_page_so_a_reload_works(site):
    for path in ("/videos/3", "/news", "/books/7?p=12", "/library?tab=podcast"):
        res = site.get(path)
        assert res.status_code == 200 and "APP" in res.text, path


def test_unknown_api_addresses_are_errors_not_the_page(site):
    res = site.get("/api/nothing")
    assert res.status_code == 404 and "APP" not in res.text
    assert site.get("/api").status_code == 404
    assert site.post("/api/nothing", json={}).status_code == 404 and site.delete("/api/nothing").status_code == 404
    assert site.post("/videos/3", json={}).status_code == 404  # only GET gets a page


def test_files_outside_the_build_folder_cannot_be_read(site):
    for path in ("/../secret.txt", "/%2e%2e/secret.txt", "/..%2fsecret.txt", "/assets/../../secret.txt"):
        assert "do not serve" not in site.get(path).text, path


def test_nothing_is_added_when_the_page_has_not_been_built(tmp_path):
    app = FastAPI()
    assert mount_frontend(app, tmp_path / "missing") is False
    assert TestClient(app).get("/").status_code == 404
