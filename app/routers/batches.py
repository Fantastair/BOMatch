"""库存批次与库存总览路由：入库、领料、删除批次、按料号聚合的库存视图"""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.auth import require_auth
from app.db import get_session
from app.models import Batch, Category, Location, Part, User
from app.templating import TEMPLATES

router = APIRouter(dependencies=[Depends(require_auth)])

# 库存 ≤ 该值在列表中标红提示（低库存预警）
LOW_STOCK_THRESHOLD = 10


def _categories(session: Session) -> list[Category]:
    return list(
        session.execute(select(Category).order_by(Category.sort_order, Category.id)).scalars()
    )


@router.get("/stock", response_class=HTMLResponse, response_model=None)
def stock_overview(
    request: Request,
    q: str = "",
    category_id: str = "",
    manufacturer: str = "",
    package: str = "",
    location_id: str = "",
    has_stock: str = "",
    session: Session = Depends(get_session),
    user: User = Depends(require_auth),
) -> HTMLResponse:
    """库存总览：按料号聚合剩余数量与金额，支持全参数搜索与多维筛选"""
    # 前端"全部"选项提交空字符串，需安全解析
    cat_id: int | None = None
    if category_id.isdigit():
        cat_id = int(category_id)
    loc_id: int | None = None
    if location_id.isdigit():
        loc_id = int(location_id)

    stmt = select(
        Part,
        func.coalesce(func.sum(Batch.quantity), 0),
        func.coalesce(func.sum(Batch.quantity * Batch.unit_price), 0.0),
        func.count(Batch.id),
    ).outerjoin(Batch, Batch.part_id == Part.id)

    # 全参数模糊搜索：料号/厂商/数值/封装/容差/耐压/介质/描述/立创编号
    if q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                Part.mpn.ilike(like),
                Part.manufacturer.ilike(like),
                Part.value_raw.ilike(like),
                Part.package.ilike(like),
                Part.tolerance.ilike(like),
                Part.voltage.ilike(like),
                Part.dielectric.ilike(like),
                Part.description.ilike(like),
                Part.lcsc_code.ilike(like),
            )
        )
    if cat_id:
        stmt = stmt.where(Part.category_id == cat_id)
    if manufacturer:
        stmt = stmt.where(Part.manufacturer == manufacturer)
    if package:
        stmt = stmt.where(Part.package == package)
    if loc_id:
        stmt = stmt.where(Batch.location_id == loc_id)
    if has_stock == "1":
        stmt = stmt.having(func.coalesce(func.sum(Batch.quantity), 0) > 0)

    rows = session.execute(stmt.group_by(Part.id).order_by(Part.id.desc())).all()

    total_units = session.scalar(select(func.coalesce(func.sum(Batch.quantity), 0))) or 0
    total_value = (
        session.scalar(select(func.coalesce(func.sum(Batch.quantity * Batch.unit_price), 0.0)))
        or 0.0
    )
    brands = (
        session.execute(
            select(Part.manufacturer)
            .where(Part.manufacturer.is_not(None), Part.manufacturer != "")
            .distinct()
            .order_by(Part.manufacturer)
        )
        .scalars()
        .all()
    )
    packages = (
        session.execute(
            select(Part.package)
            .where(Part.package.is_not(None), Part.package != "")
            .distinct()
            .order_by(Part.package)
        )
        .scalars()
        .all()
    )
    locations = session.execute(select(Location).order_by(Location.name)).scalars().all()
    return TEMPLATES.TemplateResponse(
        request,
        "stock/list.html",
        {
            "rows": rows,
            "categories": _categories(session),
            "brands": brands,
            "packages": packages,
            "locations": locations,
            "q": q,
            "category_id": cat_id,
            "manufacturer": manufacturer,
            "package": package,
            "location_id": loc_id,
            "has_stock": has_stock,
            "low_threshold": LOW_STOCK_THRESHOLD,
            "total_units": total_units,
            "total_value": total_value,
            "user": user.username,
        },
    )


# 相同来源+备注的重复入库判定窗口（分钟）
_DUP_WINDOW_MINUTES = 10


@router.post("/parts/{part_id}/batches", response_model=None)
def create_batch(
    part_id: int,
    location_id: str = Form(""),
    quantity: int = Form(...),
    unit_price: str = Form(""),
    source: str = Form(""),
    note: str = Form(""),
    force: str = Form(""),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    """入库：为料号新建一个批次（重复来源+备注时需 force 确认）"""
    part = session.get(Part, part_id)
    if part is None or quantity <= 0:
        return RedirectResponse(f"/parts/{part_id}", status_code=303)
    src = source.strip() or None
    nt = note.strip() or None
    # 防重复：source 或 note 非空时，窗口内已有相同来源+备注的批次 → 拦截并提示
    if force != "1" and (src or nt):
        from datetime import datetime, timedelta, timezone

        cutoff = datetime.now(timezone.utc) - timedelta(minutes=_DUP_WINDOW_MINUTES)
        recent = (
            session.execute(
                select(Batch).where(
                    Batch.part_id == part_id,
                    Batch.source == src,
                    Batch.note == nt,
                    Batch.created_at >= cutoff,
                )
            )
            .scalars()
            .first()
        )
        if recent is not None:
            return RedirectResponse(f"/parts/{part_id}?dup=1", status_code=303)
    loc_id = int(location_id) if location_id.strip().isdigit() else None
    price = float(unit_price) if unit_price.strip() else None
    session.add(
        Batch(
            part_id=part_id,
            location_id=loc_id,
            quantity=quantity,
            unit_price=price,
            source=src,
            note=nt,
        )
    )
    session.commit()
    return RedirectResponse(f"/parts/{part_id}", status_code=303)


@router.post("/batches/{batch_id}/consume", response_model=None)
def consume_batch(
    batch_id: int,
    quantity: int = Form(...),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    """领料：从批次扣减数量"""
    batch = session.get(Batch, batch_id)
    if batch is None:
        return RedirectResponse("/stock", status_code=303)
    if quantity <= 0 or quantity > batch.quantity:
        return RedirectResponse(f"/parts/{batch.part_id}", status_code=303)
    batch.quantity -= quantity
    session.commit()
    return RedirectResponse(f"/parts/{batch.part_id}", status_code=303)


@router.post("/batches/{batch_id}/delete", response_model=None)
def delete_batch(batch_id: int, session: Session = Depends(get_session)) -> RedirectResponse:
    """删除批次（整批移除，如售出/报废）"""
    batch = session.get(Batch, batch_id)
    if batch is None:
        return RedirectResponse("/stock", status_code=303)
    part_id = batch.part_id
    session.delete(batch)
    session.commit()
    return RedirectResponse(f"/parts/{part_id}", status_code=303)


@router.post("/batches/{batch_id}/location", response_model=None)
def update_batch_location(
    batch_id: int,
    location_id: str = Form(""),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    """修改单个批次库位（后期补录）"""
    batch = session.get(Batch, batch_id)
    if batch is None:
        return RedirectResponse("/stock", status_code=303)
    batch.location_id = int(location_id) if location_id.strip().isdigit() else None
    session.commit()
    return RedirectResponse(f"/parts/{batch.part_id}", status_code=303)


@router.post("/parts/{part_id}/batches/set-location", response_model=None)
def set_part_batch_locations(
    part_id: int,
    location_id: str = Form(""),
    only_unassigned: str = Form(""),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    """批量设置该料号所有批次（或仅未分配库位的）的库位"""
    part = session.get(Part, part_id)
    if part is None:
        return RedirectResponse("/parts", status_code=303)
    loc_id = int(location_id) if location_id.strip().isdigit() else None
    stmt = select(Batch).where(Batch.part_id == part_id)
    if only_unassigned == "1":
        stmt = stmt.where(Batch.location_id.is_(None))
    batches = session.execute(stmt).scalars().all()
    for b in batches:
        b.location_id = loc_id
    session.commit()
    return RedirectResponse(f"/parts/{part_id}", status_code=303)
