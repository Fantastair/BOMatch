"""料号 / 类别 / 库位 CRUD 集成测试"""

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.main import app
from app.models import Part

ADMIN = "admin"
PASSWORD = "testpass123"


def _login(client: TestClient) -> None:
    resp = client.post(
        "/login",
        data={"username": ADMIN, "password": PASSWORD},
        follow_redirects=False,
    )
    assert resp.status_code == 303


def _part_data(**overrides: str) -> dict[str, str]:
    data = {
        "category_id": "1",  # 电阻
        "mpn": "RC0603FR-0710KL",
        "manufacturer": "Yageo",
        "value": "10k",
        "package": "0603",
        "tolerance": "1%",
        "voltage": "",
        "dielectric": "",
        "description": "",
        "datasheet_url": "",
    }
    data.update(overrides)
    return data


def _create_part(client: TestClient, **overrides: str) -> None:
    resp = client.post("/parts", data=_part_data(**overrides), follow_redirects=False)
    assert resp.status_code == 303


def test_categories_seeded_and_crud() -> None:
    with TestClient(app) as client:
        _login(client)
        page = client.get("/categories")
        assert page.status_code == 200
        assert "电阻" in page.text
        # 新增
        resp = client.post(
            "/categories",
            data={"name": "晶振", "description": "测试"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "晶振" in client.get("/categories").text


def test_locations_crud() -> None:
    with TestClient(app) as client:
        _login(client)
        resp = client.post(
            "/locations", data={"name": "A1-1", "description": ""}, follow_redirects=False
        )
        assert resp.status_code == 303
        assert "A1-1" in client.get("/locations").text


def test_part_create_shows_canonical_key() -> None:
    with TestClient(app) as client:
        _login(client)
        _create_part(client)
        page = client.get("/parts")
        assert "RC0603FR-0710KL" in page.text
        assert "R|10000|0603|1%" in page.text


def test_equivalent_parts_share_canonical_key() -> None:
    """不同厂商料号（10k / 104 写法 / F 容差）归入同一等效组"""
    with TestClient(app) as client:
        _login(client)
        _create_part(client, mpn="RC0603FR-0710KL", value="10k", tolerance="1%")
        _create_part(client, mpn="ERJ-3EKF1002V", value="1002", tolerance="F")
        page = client.get("/parts")
        assert page.text.count("R|10000|0603|1%") == 2


def test_capacitor_canonical_key() -> None:
    with TestClient(app) as client:
        _login(client)
        _create_part(
            client,
            category_id="2",  # 电容
            mpn="CC0805KRX7R9BB104",
            manufacturer="Yageo",
            value="104",
            package="0805",
            voltage="50V",
            dielectric="X7R",
        )
        page = client.get("/parts")
        assert "C|1e-07|0805|50|X7R" in page.text


def test_part_search() -> None:
    with TestClient(app) as client:
        _login(client)
        _create_part(client, mpn="RC0603FR-0710KL", manufacturer="Yageo")
        _create_part(client, mpn="ERJ-3EKF1002V", manufacturer="Panasonic")
        page = client.get("/parts", params={"q": "Yageo"})
        assert "RC0603FR-0710KL" in page.text
        assert "ERJ-3EKF1002V" not in page.text


def test_part_edit_and_delete() -> None:
    with TestClient(app) as client:
        _login(client)
        _create_part(client, mpn="RC0603FR-0710KL")
        with SessionLocal() as session:
            part_id = (
                session.execute(select(Part).where(Part.mpn == "RC0603FR-0710KL")).scalar_one().id
            )
        # 编辑：改料号与数值
        resp = client.post(
            f"/parts/{part_id}/edit",
            data=_part_data(mpn="ERJ-3EKF1002V", value="1002", tolerance="F"),
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "ERJ-3EKF1002V" in client.get("/parts").text
        # 删除
        resp = client.post(f"/parts/{part_id}/delete", follow_redirects=False)
        assert resp.status_code == 303
        assert "ERJ-3EKF1002V" not in client.get("/parts").text


def test_part_invalid_value_shows_error() -> None:
    with TestClient(app) as client:
        _login(client)
        resp = client.post(
            "/parts", data=_part_data(mpn="BAD-VALUE", value="abc"), follow_redirects=False
        )
        assert resp.status_code == 400
        assert "无法解析数值" in resp.text


def test_create_part_redirects_to_detail_page() -> None:
    """保存后应跳转到新料号详情页，而非列表页"""
    with TestClient(app) as client:
        _login(client)
        resp = client.post("/parts", data=_part_data(), follow_redirects=False)
        assert resp.status_code == 303
        loc = resp.headers["location"]
        assert loc.startswith("/parts/")
        with SessionLocal() as session:
            part_id = session.execute(select(Part).where(Part.mpn == "RC0603FR-0710KL")).scalar_one().id
        assert loc.startswith(f"/parts/{part_id}")


def test_lcsc_code_duplicate_rejected() -> None:
    """立创编号唯一性：重复录入应报错"""
    with TestClient(app) as client:
        _login(client)
        _create_part(client, mpn="RC0603FR-0710KL", lcsc_code="C21189")
        resp = client.post(
            "/parts",
            data=_part_data(mpn="ERJ-3EKF1002V", lcsc_code="C21189"),
            follow_redirects=False,
        )
        assert resp.status_code == 400
        assert "C21189 已存在" in resp.text
        # 更新为他人已有的编号同样拒绝
        _create_part(client, mpn="THIRD", lcsc_code="C9999")
        resp = client.post(
            f"/parts/{_first_part_id(client)}/edit",
            data=_part_data(mpn="RC0603FR-0710KL", lcsc_code="C9999"),
            follow_redirects=False,
        )
        assert resp.status_code == 400


def _first_part_id(client: TestClient) -> int:
    with SessionLocal() as session:
        return session.execute(select(Part.id).order_by(Part.id)).scalars().first()


def test_x_category_aliases_merge_equivalent_group() -> None:
    """特殊件（X 类）别名：不同 MPN 通过别名归入同一等效组"""
    with TestClient(app) as client:
        _login(client)
        _create_part(
            client,
            category_id="7",  # 连接器（X 类）
            mpn="XKB8080-Z",
            manufacturer="telesky",
            aliases="通用8x8开关, 8x8-DIP",
        )
        _create_part(client, category_id="7", mpn="8x8-DIP", manufacturer="telesky")
        with SessionLocal() as session:
            keys = set(session.execute(select(Part.canonical_key)).scalars())
        assert keys == {"X|XKB8080-Z"}
        # 详情页应显示别名
        with SessionLocal() as session:
            pid = session.execute(select(Part.id).where(Part.mpn == "XKB8080-Z")).scalar_one()
        detail = client.get(f"/parts/{pid}")
        assert "等效别名" in detail.text


def test_nav_active_highlight() -> None:
    """顶栏应高亮当前模块，其他模块不带 active"""
    with TestClient(app) as client:
        _login(client)
        page = client.get("/parts")
        assert page.status_code == 200
        assert 'href="/parts" class="active"' in page.text
        assert 'href="/projects" class=""' in page.text


def test_breadcrumb_present() -> None:
    """子页面应渲染面包屑导航，且详情页支持 from_page 来源追踪"""
    with TestClient(app) as client:
        _login(client)
        # 列表页：首页 / 模块
        page = client.get("/parts")
        assert '<nav class="breadcrumb">' in page.text
        assert 'href="/"' in page.text
        # 创建料号并取 id
        _create_part(client)
        with SessionLocal() as session:
            part_id = session.execute(select(Part.id).limit(1)).scalar_one()
        # 详情页默认：首页 / 料号 / 料号名
        detail = client.get(f"/parts/{part_id}")
        assert '<nav class="breadcrumb">' in detail.text
        assert 'href="/parts">料号</a>' in detail.text
        # from_page=stock：面包屑应指向库存
        detail_from_stock = client.get(f"/parts/{part_id}?from_page=stock")
        assert 'href="/stock">库存</a>' in detail_from_stock.text
        assert 'href="/parts">料号</a>' not in detail_from_stock.text
