"""登录 / 会话流程测试"""

from fastapi.testclient import TestClient

from app.main import app

ADMIN = "admin"
PASSWORD = "testpass123"


def test_unauthenticated_root_redirects_to_login() -> None:
    with TestClient(app) as client:
        resp = client.get("/", follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/login"


def test_login_wrong_password() -> None:
    with TestClient(app) as client:
        resp = client.post(
            "/login",
            data={"username": ADMIN, "password": "wrong-password"},
        )
        assert resp.status_code == 401
        assert "用户名或密码错误" in resp.text


def test_login_success_then_access_home() -> None:
    with TestClient(app) as client:
        resp = client.post(
            "/login",
            data={"username": ADMIN, "password": PASSWORD},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "bomatch_session" in client.cookies

        home = client.get("/")
        assert home.status_code == 200
        assert f"你好，{ADMIN}" in home.text


def test_logout_clears_session() -> None:
    with TestClient(app) as client:
        client.post("/login", data={"username": ADMIN, "password": PASSWORD})
        resp = client.post("/logout", follow_redirects=False)
        assert resp.status_code == 303

        after = client.get("/", follow_redirects=False)
        assert after.status_code == 303
        assert after.headers["location"] == "/login"


def test_password_page_redirects_when_unauthenticated() -> None:
    with TestClient(app) as client:
        resp = client.get("/password", follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/login"


def test_password_change_flow() -> None:
    with TestClient(app) as client:
        client.post(
            "/login",
            data={"username": ADMIN, "password": PASSWORD},
            follow_redirects=False,
        )
        # 旧密码错误
        resp = client.post(
            "/password",
            data={
                "old_password": "wrong",
                "new_password": "newpass123",
                "confirm_password": "newpass123",
            },
        )
        assert resp.status_code == 400
        assert "当前密码错误" in resp.text
        # 两次新密码不一致
        resp = client.post(
            "/password",
            data={
                "old_password": PASSWORD,
                "new_password": "newpass123",
                "confirm_password": "different",
            },
        )
        assert resp.status_code == 400
        assert "不一致" in resp.text
        # 成功
        resp = client.post(
            "/password",
            data={
                "old_password": PASSWORD,
                "new_password": "newpass123",
                "confirm_password": "newpass123",
            },
        )
        assert resp.status_code == 200
        assert "密码已修改" in resp.text
        # 用新密码重新登录
        client.post("/logout", follow_redirects=False)
        resp = client.post(
            "/login",
            data={"username": ADMIN, "password": "newpass123"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
