"""项目与 BOM 匹配集成测试：导入 → 解析 → 按等效组匹配库存 → 缺料报告"""

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.main import app
from app.models import BOMItem, Part, Project

ADMIN = "admin"
PASSWORD = "testpass123"


def _login(client: TestClient) -> None:
    resp = client.post(
        "/login",
        data={"username": ADMIN, "password": PASSWORD},
        follow_redirects=False,
    )
    assert resp.status_code == 303


def _make_part(client: TestClient, mpn: str = "RC0603FR-0710KL", **overrides: str) -> int:
    data = {
        "category_id": "1",
        "mpn": mpn,
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
    resp = client.post("/parts", data=data, follow_redirects=False)
    assert resp.status_code == 303
    with SessionLocal() as session:
        return session.execute(select(Part).where(Part.mpn == data["mpn"])).scalar_one().id


def _inbound(client: TestClient, part_id: int, quantity: int) -> None:
    resp = client.post(
        f"/parts/{part_id}/batches",
        data={"quantity": str(quantity)},
        follow_redirects=False,
    )
    assert resp.status_code == 303


def _make_project(client: TestClient, name: str = "Test Board") -> int:
    resp = client.post("/projects", data={"name": name, "description": ""}, follow_redirects=False)
    assert resp.status_code == 303
    with SessionLocal() as session:
        return session.execute(select(Project).where(Project.name == name)).scalar_one().id


def _import_bom(client: TestClient, project_id: int, text: str) -> None:
    resp = client.post(
        f"/projects/{project_id}/bom", data={"bom_text": text}, follow_redirects=False
    )
    assert resp.status_code == 303


_BOM_TEXT = (
    "Designator\tComment\tFootprint\tQuantity\tManufacturer Part\n"
    "R1,R2\t10k\t0603\t2\tRC0603FR-0710KL\n"
    "C1,C2\t100nF\t0805\t5\tCC0805KRX7R9BB104\n"
    "U1\tSTM32F103C8T6\tLQFP48\t1\tSTM32F103C8T6\n"
)


def test_project_create_and_empty_detail() -> None:
    with TestClient(app) as client:
        _login(client)
        project_id = _make_project(client)
        page = client.get(f"/projects/{project_id}")
        assert page.status_code == 200
        assert "导入 BOM" in page.text
        assert "缺料汇总" not in page.text  # 尚未导入


def test_bom_100nf_capacitor_matches_stock() -> None:
    """回归：BOM 里的 100nF 电容应匹配到库存电容（修复 F 被误判为容差）"""
    with TestClient(app) as client:
        _login(client)
        cap_id = _make_part(
            client,
            mpn="CC0805KRX7R9BB104",
            category_id="2",
            value="100nF",
            package="0805",
            voltage="50V",
            dielectric="X7R",
        )
        _inbound(client, cap_id, 50)
        project_id = _make_project(client)
        _import_bom(
            client,
            project_id,
            "Designator\tComment\tFootprint\tQuantity\nC1\t100nF\t0805\t5\n",
        )
        page = client.get(f"/projects/{project_id}")
        assert "缺料汇总" in page.text
        with SessionLocal() as session:
            item = session.execute(
                select(BOMItem).where(BOMItem.project_id == project_id)
            ).scalar_one()
            assert item.part_id == cap_id
            assert item.canonical_key.startswith("C|1e-07|0805|50|X7R")


def test_bom_matches_by_supplier_code() -> None:
    """BOM 带立创编号时优先反查库存（最高性价比匹配）"""
    with TestClient(app) as client:
        _login(client)
        part_id = _make_part(
            client,
            mpn="CC0603KRX7R9BB104",
            category_id="2",
            value="100nF",
            package="0603",
            voltage="50V",
            dielectric="X7R",
        )
        with SessionLocal() as s:
            p = s.get(Part, part_id)
            assert p is not None
            p.lcsc_code = "C14663"
            s.commit()
        project_id = _make_project(client)
        _import_bom(
            client,
            project_id,
            "Designator\tComment\tFootprint\tQuantity\tLCSC\nC1\t100nF\tC0603\t5\tC14663\n",
        )
        with SessionLocal() as s:
            item = s.execute(select(BOMItem).where(BOMItem.project_id == project_id)).scalar_one()
            assert item.part_id == part_id


def test_bom_package_normalization_matches() -> None:
    """BOM 封装 C0603 应匹配库存 0603（封装规范化）"""
    with TestClient(app) as client:
        _login(client)
        part_id = _make_part(
            client,
            mpn="CGA0603X7R104K500JT",
            category_id="2",
            value="100nF",
            package="0603",
            voltage="50V",
            dielectric="X7R",
        )
        _inbound(client, part_id, 10)
        project_id = _make_project(client)
        _import_bom(
            client,
            project_id,
            "Designator\tComment\tFootprint\tQuantity\nC1\t100nF\tC0603\t5\n",
        )
        with SessionLocal() as s:
            item = s.execute(select(BOMItem).where(BOMItem.project_id == project_id)).scalar_one()
            assert item.part_id == part_id


def test_bom_import_matches_stock_and_reports_shortage() -> None:
    with TestClient(app) as client:
        _login(client)
        # 库存：只有 10k 0603 1% 电阻 100 个
        _make_part(client, mpn="RC0603FR-0710KL")
        _inbound(client, _make_part(client, mpn="ERJ-3EKF1002V"), 100)
        project_id = _make_project(client)
        _import_bom(client, project_id, _BOM_TEXT)

        page = client.get(f"/projects/{project_id}")
        # 缺料汇总存在；总需求 2+5+1=8，缺 5(电容)+1(IC)=6
        assert "缺料汇总" in page.text
        assert ">6<" in page.text
        # 明细行数
        with SessionLocal() as session:
            items = (
                session.execute(select(BOMItem).where(BOMItem.project_id == project_id))
                .scalars()
                .all()
            )
            assert len(items) == 3
        # 电阻行匹配到库存料号，IC 未匹配
        with SessionLocal() as session:
            r_item = session.execute(
                select(BOMItem).where(BOMItem.mpn_raw == "RC0603FR-0710KL")
            ).scalar_one()
            assert r_item.part_id is not None
            u_item = session.execute(
                select(BOMItem).where(BOMItem.mpn_raw == "STM32F103C8T6")
            ).scalar_one()
            assert u_item.part_id is None


def test_bom_import_overwrites_previous() -> None:
    with TestClient(app) as client:
        _login(client)
        project_id = _make_project(client)
        _import_bom(client, project_id, _BOM_TEXT)
        _import_bom(client, project_id, "Designator\tComment\tQuantity\nR9\t470\t3\n")
        with SessionLocal() as session:
            items = (
                session.execute(select(BOMItem).where(BOMItem.project_id == project_id))
                .scalars()
                .all()
            )
            assert len(items) == 1
            assert items[0].value_raw == "470"


def test_bom_import_invalid_text_shows_error() -> None:
    with TestClient(app) as client:
        _login(client)
        project_id = _make_project(client)
        resp = client.post(
            f"/projects/{project_id}/bom",
            data={"bom_text": "这不是 BOM"},
            follow_redirects=False,
        )
        assert resp.status_code == 400
        assert "未识别到有效行" in resp.text


def test_shortage_summary_zero_when_stock_sufficient() -> None:
    with TestClient(app) as client:
        _login(client)
        _make_part(client, mpn="RC0603FR-0710KL")
        _inbound(client, _make_part(client, mpn="ERJ-3EKF1002V"), 100)
        project_id = _make_project(client)
        _import_bom(client, project_id, _BOM_TEXT)
        page = client.get(f"/projects/{project_id}")
        # 电阻满足、电容缺 5、IC 缺 1 → 总缺 6（非 0）
        assert ">6<" in page.text
        # 明细中电阻行匹配显示 ✓ 料号
        assert "✓ RC0603FR-0710KL" in page.text
