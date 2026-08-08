"""批次 / 库存集成测试：入库、领料、删除、金额统计"""

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.main import app
from app.models import Batch, Part

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


def _make_location(client: TestClient, name: str = "A1-1") -> int:
    resp = client.post("/locations", data={"name": name}, follow_redirects=False)
    assert resp.status_code == 303
    with SessionLocal() as session:
        from app.models import Location

        return session.execute(select(Location).where(Location.name == name)).scalar_one().id


def _inbound(
    client: TestClient,
    part_id: int,
    quantity: int,
    unit_price: str | None = None,
    location_id: int | None = None,
) -> None:
    data: dict[str, str] = {"quantity": str(quantity)}
    if unit_price is not None:
        data["unit_price"] = unit_price
    if location_id is not None:
        data["location_id"] = str(location_id)
    resp = client.post(f"/parts/{part_id}/batches", data=data, follow_redirects=False)
    assert resp.status_code == 303


def _batch_id(client: TestClient, part_id: int) -> int:
    with SessionLocal() as session:
        batch = session.execute(select(Batch).where(Batch.part_id == part_id)).scalars().first()
        assert batch is not None
        return batch.id


def test_stock_empty_shows_part_with_zero() -> None:
    with TestClient(app) as client:
        _login(client)
        part_id = _make_part(client)
        page = client.get("/stock")
        assert "RC0603FR-0710KL" in page.text
        # 料号无批次：库存 0
        detail = client.get(f"/parts/{part_id}")
        assert "暂无库存" in detail.text


def test_inbound_and_stock_aggregate() -> None:
    with TestClient(app) as client:
        _login(client)
        part_id = _make_part(client)
        _inbound(client, part_id, 100, unit_price="0.5")
        page = client.get("/stock")
        assert "100" in page.text
        assert "50.00" in page.text  # 100 × 0.5
        detail = client.get(f"/parts/{part_id}")
        assert "共 100 个" in detail.text
        assert "50.00 元" in detail.text


def test_consume_reduces_quantity() -> None:
    with TestClient(app) as client:
        _login(client)
        part_id = _make_part(client)
        _inbound(client, part_id, 100)
        batch_id = _batch_id(client, part_id)
        resp = client.post(
            f"/batches/{batch_id}/consume",
            data={"quantity": "30"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "共 70 个" in client.get(f"/parts/{part_id}").text


def test_consume_over_quantity_no_change() -> None:
    with TestClient(app) as client:
        _login(client)
        part_id = _make_part(client)
        _inbound(client, part_id, 10)
        batch_id = _batch_id(client, part_id)
        resp = client.post(
            f"/batches/{batch_id}/consume",
            data={"quantity": "999"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "共 10 个" in client.get(f"/parts/{part_id}").text


def test_delete_batch_empties_stock() -> None:
    with TestClient(app) as client:
        _login(client)
        part_id = _make_part(client)
        _inbound(client, part_id, 50)
        batch_id = _batch_id(client, part_id)
        resp = client.post(f"/batches/{batch_id}/delete", follow_redirects=False)
        assert resp.status_code == 303
        assert "暂无库存" in client.get(f"/parts/{part_id}").text


def test_multi_batch_value_ignores_missing_price() -> None:
    """金额只统计有单价的批次；无单价批次不影响"""
    with TestClient(app) as client:
        _login(client)
        part_id = _make_part(client)
        _inbound(client, part_id, 100, unit_price="0.5")
        _inbound(client, part_id, 200)  # 无单价
        page = client.get("/stock")
        assert "300" in page.text  # 总数量 300
        assert "50.00" in page.text  # 金额仍只算有单价的 100×0.5
        detail = client.get(f"/parts/{part_id}")
        assert "共 300 个" in detail.text


def test_stock_search_and_filter() -> None:
    with TestClient(app) as client:
        _login(client)
        part_a = _make_part(client, mpn="RC0603FR-0710KL", manufacturer="Yageo")
        _make_part(client, mpn="ERJ-3EKF1002V", manufacturer="Panasonic")
        _inbound(client, part_a, 10)
        page = client.get("/stock", params={"q": "Yageo"})
        assert "RC0603FR-0710KL" in page.text
        assert "ERJ-3EKF1002V" not in page.text


def test_empty_category_filter_no_error() -> None:
    """筛选表单提交空 category_id（全部类别）不应 422（回归：修复 int 解析错误）"""
    with TestClient(app) as client:
        _login(client)
        stock = client.get("/stock", params={"q": "", "category_id": ""})
        assert stock.status_code == 200
        assert "库存" in stock.text
        parts = client.get("/parts", params={"q": "", "category_id": ""})
        assert parts.status_code == 200
        assert "料号" in parts.text


def test_stock_search_matches_value_field() -> None:
    """全参数搜索：按数值命中"""
    with TestClient(app) as client:
        _login(client)
        _make_part(client, mpn="RC0603FR-0710KL", value="10k")
        _make_part(client, mpn="ERJ-3EKF1002V", value="100k")
        page = client.get("/stock", params={"q": "10k"})
        assert "RC0603FR-0710KL" in page.text
        assert "ERJ-3EKF1002V" not in page.text


def test_stock_filter_by_manufacturer() -> None:
    """按品牌筛选"""
    with TestClient(app) as client:
        _login(client)
        _make_part(client, mpn="RC0603FR-0710KL", manufacturer="Yageo")
        _make_part(client, mpn="ERJ-3EKF1002V", manufacturer="Panasonic")
        page = client.get("/stock", params={"manufacturer": "Yageo"})
        assert "RC0603FR-0710KL" in page.text
        assert "ERJ-3EKF1002V" not in page.text


def test_stock_filter_has_stock() -> None:
    """只看有库存的料号"""
    with TestClient(app) as client:
        _login(client)
        p1 = _make_part(client, mpn="RC0603FR-0710KL")
        _make_part(client, mpn="ERJ-3EKF1002V")
        _inbound(client, p1, 10)
        page = client.get("/stock", params={"has_stock": "1"})
        assert "RC0603FR-0710KL" in page.text
        assert "ERJ-3EKF1002V" not in page.text


def test_stock_low_stock_marked() -> None:
    """库存低于阈值标红"""
    with TestClient(app) as client:
        _login(client)
        p1 = _make_part(client, mpn="RC0603FR-0710KL")
        _inbound(client, p1, 5)
        page = client.get("/stock")
        assert "stock-low" in page.text


def test_inbound_duplicate_source_note_blocked_then_forced() -> None:
    """入库防重复：相同 source+note 再次提交被拦截（dup=1），勾选确认后可强制入库"""
    with TestClient(app) as client:
        _login(client)
        part_id = _make_part(client)
        # 首次入库
        resp = client.post(
            f"/parts/{part_id}/batches",
            data={"quantity": "10", "source": "SO1", "note": "n1"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        # 相同 source+note 再次入库 → 拦截
        resp = client.post(
            f"/parts/{part_id}/batches",
            data={"quantity": "10", "source": "SO1", "note": "n1"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert resp.headers["location"].endswith("?dup=1")
        with SessionLocal() as session:
            count = len(
                session.execute(select(Batch).where(Batch.part_id == part_id)).scalars().all()
            )
        assert count == 1
        # 不同 note 不拦截
        resp = client.post(
            f"/parts/{part_id}/batches",
            data={"quantity": "10", "source": "SO1", "note": "n2"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "?dup=1" not in resp.headers["location"]
        # 带 force 确认可强制再次入库
        resp = client.post(
            f"/parts/{part_id}/batches",
            data={"quantity": "10", "source": "SO1", "note": "n1", "force": "1"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        with SessionLocal() as session:
            count = len(
                session.execute(select(Batch).where(Batch.part_id == part_id)).scalars().all()
            )
        assert count == 3


def test_batch_location_update() -> None:
    """单个批次改库位 + 批量设置（后期补录库位）"""
    with TestClient(app) as client:
        _login(client)
        part_id = _make_part(client)
        _inbound(client, part_id, 10)
        batch_id = _batch_id(client, part_id)
        loc1 = _make_location(client, "A1-1")
        loc2 = _make_location(client, "B2-1")
        # 单个修改
        resp = client.post(
            f"/batches/{batch_id}/location",
            data={"location_id": str(loc1)},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        with SessionLocal() as s:
            batch = s.get(Batch, batch_id)
            assert batch is not None
            assert batch.location_id == loc1
        # 批量设置（不勾选"仅未指定"= 全部批次，覆盖为 loc2）
        resp = client.post(
            f"/parts/{part_id}/batches/set-location",
            data={"location_id": str(loc2)},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        with SessionLocal() as s:
            batch = s.get(Batch, batch_id)
            assert batch is not None
            assert batch.location_id == loc2
