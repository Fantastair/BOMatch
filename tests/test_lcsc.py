"""立创同步：参数映射 / 回填逻辑 / 页面同步路由测试（mock 网络）"""

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import Batch, Category, Part
from app.services.lcsc import LcscProduct, apply_product, extract_value, map_params, query_product

ADMIN = "admin"
PASSWORD = "testpass123"


def test_extract_value() -> None:
    """从立创参数表提取数值（容值/阻值/感值）"""
    assert extract_value({"容值": "22uF", "精度": "±20%"}) == (2.2e-5, "F", "22uF")
    assert extract_value({"阻值": "10kΩ"}) == (10000.0, "Ω", "10kΩ")
    assert extract_value({"感值": "1uH"}) == (1e-6, "H", "1uH")
    assert extract_value({"精度": "±1%"}) == (None, "", None)
    assert extract_value({}) == (None, "", None)


def test_apply_product_fills_value_and_package() -> None:
    """同步应回填值/封装（此前漏掉），等效键才能正确匹配 BOM"""
    cat = Category(name="电容")
    part = Part(mpn="C7432770", category=cat, canonical_key="C|||")
    product = LcscProduct(
        code="C7432770",
        model="HGC0603R5226M100NTHJ",
        package="0603",
        params={"容值": "22uF", "精度": "±20%", "额定电压": "10V", "温度系数": "X5R"},
        tolerance="20%",
        voltage=10.0,
        dielectric="X5R",
        value=2.2e-5,
        value_unit="F",
        value_raw="22uF",
    )
    apply_product(part, product)
    assert part.lcsc_code == "C7432770"
    assert part.package == "0603"
    assert part.value == 2.2e-5
    assert part.value_unit == "F"
    assert part.value_raw == "22uF"
    assert part.canonical_key == "C|2.2e-05|0603|10|X5R"


def test_map_params() -> None:
    params = {"容值": "100nF", "精度": "±10%", "额定电压": "50V", "温度系数": "X7R"}
    tolerance, voltage, dielectric = map_params(params)
    assert tolerance == "10%"
    assert voltage == 50.0
    assert dielectric == "X7R"


def test_map_params_empty() -> None:
    assert map_params({}) == (None, None, None)
    assert map_params(None) == (None, None, None)


def test_apply_product_backfills_and_recalculates() -> None:
    cat = Category(name="电阻")
    part = Part(
        mpn="C21189",
        category=cat,
        value=10000.0,
        value_unit="Ω",
        value_raw="10kΩ",
        package="0603",
        canonical_key="R|10000|0603|",
    )
    batch = Batch(quantity=100)
    part.batches.append(batch)

    product = LcscProduct(
        code="C21189", model="RC0603FR-0710KL", brand="Yageo", tolerance="1%", moq_price=0.0942
    )
    apply_product(part, product)

    assert part.lcsc_code == "C21189"
    assert part.mpn == "RC0603FR-0710KL"  # mpn 从立创编号迁移到厂家型号
    assert part.manufacturer == "Yageo"
    assert part.tolerance == "1%"
    assert part.canonical_key == "R|10000|0603|1%"  # 容差参与后等效键变精确
    assert batch.unit_price == 0.0942


def test_apply_product_updates_existing_price() -> None:
    """同步时已有价格的批次也应更新为立创最新价（Issue #6）"""
    cat = Category(name="电阻")
    part = Part(mpn="RC0603FR-0710KL", category=cat, canonical_key="R|10000|0603|")
    batch = Batch(quantity=100, unit_price=0.05)  # 已有旧价
    part.batches.append(batch)

    product = LcscProduct(code="C21189", model="RC0603FR-0710KL", moq_price=0.0942)
    apply_product(part, product)

    assert batch.unit_price == 0.0942  # 旧价被更新为立创最新价


def test_apply_product_keeps_existing_values() -> None:
    cat = Category(name="电容")
    part = Part(
        mpn="CC0805KRX7R9BB104",
        category=cat,
        manufacturer="Yageo",
        value=1e-7,
        value_unit="F",
        value_raw="100nF",
        package="0805",
        tolerance="10%",
        canonical_key="C|1e-07|0805||",
    )
    product = LcscProduct(code="C14663", model="FCC0603B104K500CT", tolerance="5%")
    apply_product(part, product)
    # 已有容差/厂商不覆盖；非 C 开头 mpn 不动
    assert part.tolerance == "10%"
    assert part.manufacturer == "Yageo"
    assert part.mpn == "CC0805KRX7R9BB104"


def test_query_product_falls_back_to_jsonld() -> None:
    with (
        patch("app.services.lcsc._query_substitute", return_value=None),
        patch("app.services.lcsc.query_by_pid") as mock_b,
    ):
        mock_b.return_value = LcscProduct(code="C1", model="X", moq_price=1.0)
        result = query_product("C1", pid="123")
        assert result is not None
        assert result.model == "X"
        mock_b.assert_called_once_with("123")


def _login(client: TestClient) -> None:
    client.post(
        "/login",
        data={"username": ADMIN, "password": PASSWORD},
        follow_redirects=False,
    )


def _lcsc_part_data(**overrides: str) -> dict[str, str]:
    data = {
        "category_id": "1",
        "mpn": "C21189",
        "manufacturer": "",
        "value": "10k",
        "package": "0603",
        "tolerance": "",
        "voltage": "",
        "dielectric": "",
        "description": "",
        "datasheet_url": "",
        "lcsc_code": "C21189",
    }
    data.update(overrides)
    return data


def test_create_part_with_lcsc_syncs_and_redirects_to_detail() -> None:
    """新建料号带 C 编号：先同步、后跳转详情页，并显示同步成功"""
    with TestClient(app) as client:
        _login(client)
        product = LcscProduct(
            code="C21189", model="RC0603FR-0710KL", brand="Yageo", tolerance="1%", moq_price=0.5
        )
        with patch("app.routers.parts.query_product_detailed", return_value=(product, None)):
            resp = client.post("/parts", data=_lcsc_part_data(), follow_redirects=False)
            assert resp.status_code == 303
            loc = resp.headers["location"]
            assert loc.startswith("/parts/")
            assert "sync=ok" in loc
            page = client.get(loc)
            assert "同步成功" in page.text
        with SessionLocal() as session:
            part = session.query(Part).filter_by(mpn="RC0603FR-0710KL").one()
            assert part.lcsc_code == "C21189"
            assert part.tolerance == "1%"


def test_create_part_sync_failure_shows_reason() -> None:
    """同步失败时详情页显示明确错误，而非静默重定向"""
    with TestClient(app) as client:
        _login(client)
        resp = client.post("/parts", data=_lcsc_part_data(), follow_redirects=False)
        assert resp.status_code == 303
        loc = resp.headers["location"]
        assert "sync=error" in loc
        page = client.get(loc)
        assert "立创同步失败" in page.text
        assert "测试环境跳过" in page.text  # autouse mock 返回的原因


def test_create_manual_part_skip_sync_neutral() -> None:
    """手动料号（无立创编号）保存后应中性提示「跳过同步」，而非「同步失败」"""
    with TestClient(app) as client:
        _login(client)
        resp = client.post(
            "/parts",
            data=_lcsc_part_data(mpn="MY-MANUAL-PART", lcsc_code=""),
            follow_redirects=False,
        )
        assert resp.status_code == 303
        loc = resp.headers["location"]
        assert "sync=skip" in loc
        page = client.get(loc)
        assert "跳过同步" in page.text
        assert "同步失败" not in page.text


def test_lcsc_sync_route_backfills_part() -> None:
    with TestClient(app) as client:
        _login(client)
        resp = client.post(
            "/parts",
            data={
                "category_id": "1",
                "mpn": "C21189",
                "manufacturer": "",
                "value": "10k",
                "package": "0603",
                "tolerance": "",
                "voltage": "",
                "dielectric": "",
                "description": "",
                "datasheet_url": "",
                "lcsc_code": "C21189",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 303
        with SessionLocal() as session:
            part = session.query(Part).filter_by(mpn="C21189").one()
            part_id = part.id
            session.add(Batch(part_id=part_id, quantity=50))
            session.commit()

        product = LcscProduct(code="C21189", model="RC0603FR-0710KL", tolerance="1%", moq_price=0.5)
        with patch("app.routers.parts.query_product_detailed", return_value=(product, None)):
            resp = client.post(f"/parts/{part_id}/lcsc-sync", follow_redirects=False)
            assert resp.status_code == 303
            # 成功时带 sync=ok 回跳详情页
            assert resp.headers["location"].startswith(f"/parts/{part_id}?sync=ok")

        with SessionLocal() as session:
            part = session.get(Part, part_id)
            assert part is not None
            batch = session.query(Batch).filter_by(part_id=part_id).one()
            assert part.mpn == "RC0603FR-0710KL"
            assert part.lcsc_code == "C21189"
            assert part.tolerance == "1%"
            assert part.canonical_key == "R|10000|0603|1%"
            assert batch.unit_price == 0.5
