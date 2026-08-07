"""冒烟测试：应用可导入、登录页可访问"""

from fastapi.testclient import TestClient

from app.main import app


def test_app_importable() -> None:
    assert app.title == "BOMatch"


def test_login_page_accessible() -> None:
    with TestClient(app) as client:
        resp = client.get("/login")
        assert resp.status_code == 200
        assert "登录" in resp.text
