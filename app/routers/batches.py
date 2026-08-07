"""库存批次与库存总览路由：入库、领料、删除批次、按料号聚合的库存视图"""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import require_auth
from app.db import get_session
from app.models import Batch, Category, Part, User
from app.templating import TEMPLATES

router = APIRouter(dependencies=[Depends(require_auth)])


def _categories(session: Session) -> list[Category]:
    return list(
        session.execute(select(Category).order_by(Category.sort_order, Category.id)).scalars()
    )


@router.get("/stock", response_class=HTMLResponse, response_model=None)
def stock_overview(
    request: Request,
    q: str = "",
    category_id: str = "",
    session: Session = Depends(get_session),
    user: User = Depends(require_auth),
) -> HTMLResponse:
    """库存总览：按料号聚合剩余数量与金额"""
    # 前端"全部类别"提交空字符串，需解析为 int
    cat_id: int | None = None
    if category_id.isdigit():
        cat_id = int(category_id)
    stmt = select(
        Part,
        func.coalesce(func.sum(Batch.quantity), 0),
        func.coalesce(func.sum(Batch.quantity * Batch.unit_price), 0.0),
        func.count(Batch.id),
    ).outerjoin(Batch, Batch.part_id == Part.id)
    if q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(Part.mpn.ilike(like) | Part.manufacturer.ilike(like))
    if cat_id:
        stmt = stmt.where(Part.category_id == cat_id)
    rows = session.execute(stmt.group_by(Part.id).order_by(Part.id.desc())).all()

    total_units = session.scalar(select(func.coalesce(func.sum(Batch.quantity), 0))) or 0
    total_value = (
        session.scalar(select(func.coalesce(func.sum(Batch.quantity * Batch.unit_price), 0.0)))
        or 0.0
    )
    return TEMPLATES.TemplateResponse(
        request,
        "stock/list.html",
        {
            "rows": rows,
            "categories": _categories(session),
            "q": q,
            "category_id": cat_id,
            "total_units": total_units,
            "total_value": total_value,
            "user": user.username,
        },
    )


@router.post("/parts/{part_id}/batches", response_model=None)
def create_batch(
    part_id: int,
    location_id: str = Form(""),
    quantity: int = Form(...),
    unit_price: str = Form(""),
    source: str = Form(""),
    note: str = Form(""),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    """入库：为料号新建一个批次"""
    part = session.get(Part, part_id)
    if part is None or quantity <= 0:
        return RedirectResponse(f"/parts/{part_id}", status_code=303)
    loc_id = int(location_id) if location_id.strip().isdigit() else None
    price = float(unit_price) if unit_price.strip() else None
    session.add(
        Batch(
            part_id=part_id,
            location_id=loc_id,
            quantity=quantity,
            unit_price=price,
            source=source.strip() or None,
            note=note.strip() or None,
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
