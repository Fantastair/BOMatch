"""料号 CRUD 路由"""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.auth import require_auth
from app.db import get_session
from app.models import Batch, Category, Location, Part, User
from app.parsers.canonical import (
    normalize_dielectric,
    normalize_package,
    normalize_tolerance,
)
from app.parsers.part import part_canonical_key, resolve_value, resolve_voltage
from app.services.lcsc import apply_product, query_product
from app.templating import TEMPLATES

router = APIRouter(prefix="/parts", dependencies=[Depends(require_auth)])


def _build_part_fields(
    session: Session,
    category_id: int,
    mpn: str,
    manufacturer: str,
    value_text: str,
    package: str,
    tolerance: str,
    voltage_text: str,
    dielectric: str,
    description: str,
    datasheet_url: str,
    lcsc_code: str = "",
) -> tuple[dict, str | None]:
    """解析表单字段 → (Part 字段 dict, 错误消息)；出错时返回 ({}, 错误)。"""
    mpn = mpn.strip()
    if not mpn:
        return {}, "料号不能为空"
    category = session.get(Category, category_id)
    if category is None:
        return {}, "类别无效"
    resolved_value, unit = resolve_value(value_text, category.name)
    if value_text.strip() and resolved_value is None:
        return {}, f"无法解析数值：{value_text}"
    norm_tolerance = normalize_tolerance(tolerance) if tolerance.strip() else None
    norm_package = normalize_package(package) if package.strip() else None
    norm_dielectric = normalize_dielectric(dielectric) if dielectric.strip() else None
    voltage_num = resolve_voltage(voltage_text)
    canonical = part_canonical_key(
        category.name,
        mpn,
        resolved_value,
        unit,
        norm_package,
        norm_tolerance,
        voltage_num,
        norm_dielectric,
    )
    return {
        "mpn": mpn,
        "manufacturer": manufacturer.strip() or None,
        "lcsc_code": lcsc_code.strip().upper() or None,
        "category_id": category_id,
        "value": resolved_value,
        "value_unit": unit,
        "value_raw": value_text.strip() or None,
        "package": norm_package,
        "tolerance": norm_tolerance,
        "voltage": voltage_num,
        "dielectric": norm_dielectric,
        "canonical_key": canonical,
        "description": description.strip() or None,
        "datasheet_url": datasheet_url.strip() or None,
    }, None


def _categories(session: Session) -> list[Category]:
    return list(
        session.execute(select(Category).order_by(Category.sort_order, Category.id)).scalars()
    )


@router.get("", response_class=HTMLResponse, response_model=None)
def list_parts(
    request: Request,
    q: str = "",
    category_id: str = "",
    session: Session = Depends(get_session),
    user: User = Depends(require_auth),
) -> HTMLResponse:
    # 前端"全部类别"提交空字符串，需解析为 int
    cat_id: int | None = None
    if category_id.isdigit():
        cat_id = int(category_id)
    stmt = select(Part)
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
    parts = session.execute(stmt.order_by(Part.id.desc())).scalars().all()
    return TEMPLATES.TemplateResponse(
        request,
        "parts/list.html",
        {
            "parts": parts,
            "categories": _categories(session),
            "q": q,
            "category_id": cat_id,
            "user": user.username,
        },
    )


@router.get("/new", response_class=HTMLResponse, response_model=None)
def new_part(
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(require_auth),
) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(
        request,
        "parts/form.html",
        {"part": None, "categories": _categories(session), "error": None, "user": user.username},
    )


@router.post("", response_model=None)
def create_part(
    request: Request,
    category_id: int = Form(...),
    mpn: str = Form(...),
    manufacturer: str = Form(""),
    value: str = Form(""),
    package: str = Form(""),
    tolerance: str = Form(""),
    voltage: str = Form(""),
    dielectric: str = Form(""),
    description: str = Form(""),
    datasheet_url: str = Form(""),
    lcsc_code: str = Form(""),
    session: Session = Depends(get_session),
) -> HTMLResponse | RedirectResponse:
    fields, error = _build_part_fields(
        session,
        category_id,
        mpn,
        manufacturer,
        value,
        package,
        tolerance,
        voltage,
        dielectric,
        description,
        datasheet_url,
        lcsc_code,
    )
    if error:
        return TEMPLATES.TemplateResponse(
            request,
            "parts/form.html",
            {"part": None, "categories": _categories(session), "error": error, "user": ""},
            status_code=400,
        )
    session.add(Part(**fields))
    session.commit()
    return RedirectResponse("/parts", status_code=303)


@router.post("/{part_id}/lcsc-sync", response_model=None)
def lcsc_sync(part_id: int, session: Session = Depends(get_session)) -> RedirectResponse:
    """查询立创商城并回填该料号的价格/参数/品牌（不覆盖已有值）"""
    part = session.get(Part, part_id)
    if part is None:
        return RedirectResponse("/parts", status_code=303)
    code = part.lcsc_code_effective
    if code:
        product = query_product(code)
        apply_product(part, product)
        session.commit()
    return RedirectResponse(f"/parts/{part_id}", status_code=303)


@router.get("/{part_id}", response_class=HTMLResponse, response_model=None)
def part_detail(
    part_id: int,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(require_auth),
    from_page: str = "",
) -> HTMLResponse | RedirectResponse:
    part = session.get(Part, part_id)
    if part is None:
        return RedirectResponse("/parts", status_code=303)
    from_page = from_page if from_page in ("stock",) else ""
    batches = (
        session.execute(select(Batch).where(Batch.part_id == part_id).order_by(Batch.id.desc()))
        .scalars()
        .all()
    )
    locations = session.execute(select(Location).order_by(Location.name)).scalars().all()
    equivalents = (
        session.execute(
            select(Part).where(Part.canonical_key == part.canonical_key, Part.id != part.id)
        )
        .scalars()
        .all()
    )
    total_qty = sum(b.quantity for b in batches)
    total_value = sum((b.quantity or 0) * (b.unit_price or 0) for b in batches)
    return TEMPLATES.TemplateResponse(
        request,
        "parts/detail.html",
        {
            "part": part,
            "batches": batches,
            "locations": locations,
            "equivalents": equivalents,
            "total_qty": total_qty,
            "total_value": total_value,
            "from_page": from_page,
            "user": user.username,
        },
    )


@router.get("/{part_id}/edit", response_class=HTMLResponse, response_model=None)
def edit_part(
    part_id: int,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(require_auth),
) -> HTMLResponse:
    part = session.get(Part, part_id)
    return TEMPLATES.TemplateResponse(
        request,
        "parts/form.html",
        {"part": part, "categories": _categories(session), "error": None, "user": user.username},
    )


@router.post("/{part_id}/edit", response_model=None)
def update_part(
    part_id: int,
    request: Request,
    category_id: int = Form(...),
    mpn: str = Form(...),
    manufacturer: str = Form(""),
    value: str = Form(""),
    package: str = Form(""),
    tolerance: str = Form(""),
    voltage: str = Form(""),
    dielectric: str = Form(""),
    description: str = Form(""),
    datasheet_url: str = Form(""),
    lcsc_code: str = Form(""),
    session: Session = Depends(get_session),
) -> HTMLResponse | RedirectResponse:
    part = session.get(Part, part_id)
    if part is None:
        return RedirectResponse("/parts", status_code=303)
    fields, error = _build_part_fields(
        session,
        category_id,
        mpn,
        manufacturer,
        value,
        package,
        tolerance,
        voltage,
        dielectric,
        description,
        datasheet_url,
        lcsc_code,
    )
    if error:
        return TEMPLATES.TemplateResponse(
            request,
            "parts/form.html",
            {"part": part, "categories": _categories(session), "error": error, "user": ""},
            status_code=400,
        )
    for key, val in fields.items():
        setattr(part, key, val)
    session.commit()
    return RedirectResponse("/parts", status_code=303)


@router.post("/{part_id}/delete", response_model=None)
def delete_part(part_id: int, session: Session = Depends(get_session)) -> RedirectResponse:
    part = session.get(Part, part_id)
    if part is not None:
        session.delete(part)
        session.commit()
    return RedirectResponse("/parts", status_code=303)
