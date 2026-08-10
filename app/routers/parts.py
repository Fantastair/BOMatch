"""料号 CRUD 路由"""

import json
import re
from urllib.parse import quote

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
from app.services.lcsc import apply_product, query_product_detailed
from app.templating import TEMPLATES

router = APIRouter(prefix="/parts", dependencies=[Depends(require_auth)])


def _parse_aliases(text: str, mpn: str) -> list[str]:
    """解析别名文本（逗号/空白/换行分隔）→ 大写去重列表（排除自身 MPN）。"""
    seen: set[str] = set()
    result: list[str] = []
    for raw in re.split(r"[,，;\s]+", text or ""):
        item = raw.strip().upper()
        if item and item != mpn.strip().upper() and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _check_lcsc_duplicate(
    session: Session, lcsc_code: str | None, exclude_part_id: int | None = None
) -> Part | None:
    """校验 lcsc_code 唯一性（忽略空值、忽略自身）；重复返回已有料号。"""
    code = (lcsc_code or "").strip().upper()
    if not code:
        return None
    stmt = select(Part).where(Part.lcsc_code == code)
    if exclude_part_id is not None:
        stmt = stmt.where(Part.id != exclude_part_id)
    return session.execute(stmt).scalars().first()


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
    aliases: str = "",
    exclude_part_id: int | None = None,
) -> tuple[dict, str | None]:
    """解析表单字段 → (Part 字段 dict, 错误消息)；出错时返回 ({}, 错误)。"""
    mpn = mpn.strip()
    if not mpn:
        return {}, "料号不能为空"
    category = session.get(Category, category_id)
    if category is None:
        return {}, "类别无效"
    norm_code = lcsc_code.strip().upper() or None
    dup = _check_lcsc_duplicate(session, norm_code, exclude_part_id)
    if dup is not None:
        return {}, f"立创编号 {norm_code} 已存在（料号 {dup.mpn}），请勿重复录入"
    resolved_value, unit = resolve_value(value_text, category.name)
    if value_text.strip() and resolved_value is None:
        return {}, f"无法解析数值：{value_text}"
    norm_tolerance = normalize_tolerance(tolerance) if tolerance.strip() else None
    norm_package = normalize_package(package) if package.strip() else None
    norm_dielectric = normalize_dielectric(dielectric) if dielectric.strip() else None
    voltage_num = resolve_voltage(voltage_text)
    alias_list = _parse_aliases(aliases, mpn)
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
        "lcsc_code": norm_code,
        "aliases": json.dumps(alias_list, ensure_ascii=False) if alias_list else None,
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


def _reconcile_equivalent_group(session: Session, part: Part) -> None:
    """特殊件（X 类）等效组：按 mpn + 别名合并到同一 canonical_key。

    以组内最早创建的料号为基准（id 最小），其余同组成员（mpn 或别名相交）统一改写。
    """
    if not part.canonical_key or not part.canonical_key.startswith("X|"):
        return
    members = {part.mpn.strip().upper()} | set(part.alias_list)
    if not members:
        return
    group = [part]
    candidates = (
        session.execute(
            select(Part).where(
                Part.category_id == part.category_id,
                Part.id != part.id,
                Part.canonical_key.like("X|%"),
            )
        )
        .scalars()
        .all()
    )
    for cand in candidates:
        cand_members = {cand.mpn.strip().upper()} | set(cand.alias_list)
        if members & cand_members:
            group.append(cand)
            members |= cand_members
    base = min(group, key=lambda p: p.id).mpn.strip().upper()
    new_key = f"X|{base}"
    for p in group:
        if p.canonical_key != new_key:
            p.canonical_key = new_key


def _sync_part(session: Session, part: Part) -> tuple[bool | None, str]:
    """查询立创并回填该料号（参数不覆盖已有值，价格始终更新）；返回 (状态, 提示消息)。

    状态：None=未填写立创编号（跳过，中性提示）；True=成功；False=失败。
    供「新建料号带 C 编号」与「详情页同步按钮」共用，保证保存流程先同步、后跳转。
    """
    code = part.lcsc_code_effective
    if not code:
        return None, "未填写立创编号，跳过同步"
    try:
        product, error = query_product_detailed(code)
        if product is None:
            return False, error or "未查到该立创编号"
        apply_product(part, product)
        # 特殊件（X 类）同步会重算 canonical_key，需重新合并等效组
        _reconcile_equivalent_group(session, part)
        session.commit()
        return True, f"同步成功：{product.model or code}"
    except Exception as exc:  # noqa: BLE001
        return False, f"同步异常：{exc}"


def _sync_query(sync_ok: bool | None, sync_msg: str) -> str:
    """按同步状态生成详情页回跳 query（ok/error/skip 三种）。"""
    if sync_ok is None:
        return f"?sync=skip&sync_msg={quote(sync_msg)}"
    return f"?sync={'ok' if sync_ok else 'error'}&sync_msg={quote(sync_msg)}"


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
    from_page: str = "",
    session: Session = Depends(get_session),
    user: User = Depends(require_auth),
) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(
        request,
        "parts/form.html",
        {
            "part": None,
            "categories": _categories(session),
            "error": None,
            "from_page": from_page,
            "user": user.username,
        },
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
    aliases: str = Form(""),
    from_page: str = Form(""),
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
        aliases,
    )
    if error:
        return TEMPLATES.TemplateResponse(
            request,
            "parts/form.html",
            {
                "part": None,
                "categories": _categories(session),
                "error": error,
                "from_page": from_page,
                "user": "",
            },
            status_code=400,
        )
    part = Part(**fields)
    session.add(part)
    session.commit()
    _reconcile_equivalent_group(session, part)
    # 填了立创编号 → 先同步、后跳转详情页，让用户看到同步结果
    sync_ok, sync_msg = _sync_part(session, part)
    session.commit()
    url = f"/parts/{part.id}{_sync_query(sync_ok, sync_msg)}"
    if from_page == "stock":
        url += "&from_page=stock"
    return RedirectResponse(url, status_code=303)


@router.post("/{part_id}/lcsc-sync", response_model=None)
def lcsc_sync(
    part_id: int, from_page: str = Form(""), session: Session = Depends(get_session)
) -> RedirectResponse:
    """查询立创商城并回填该料号的价格/参数/品牌（不覆盖已有值）；失败时带原因跳回详情页。"""
    part = session.get(Part, part_id)
    if part is None:
        return RedirectResponse("/parts", status_code=303)
    sync_ok, sync_msg = _sync_part(session, part)
    url = f"/parts/{part_id}{_sync_query(sync_ok, sync_msg)}"
    if from_page == "stock":
        url += "&from_page=stock"
    return RedirectResponse(url, status_code=303)


@router.get("/{part_id}", response_class=HTMLResponse, response_model=None)
def part_detail(
    part_id: int,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(require_auth),
    from_page: str = "",
    sync: str = "",
    sync_msg: str = "",
    dup: str = "",
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
    # 最近批次（来源/备注）供入库防重复提示
    recent_batches = [
        {"source": b.source or "", "note": b.note or ""}
        for b in session.execute(
            select(Batch).where(Batch.part_id == part_id).order_by(Batch.id.desc()).limit(5)
        ).scalars()
    ]
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
            "recent_batches": recent_batches,
            "locations": locations,
            "equivalents": equivalents,
            "total_qty": total_qty,
            "total_value": total_value,
            "from_page": from_page,
            "sync": sync,
            "sync_msg": sync_msg,
            "dup": dup == "1",
            "user": user.username,
        },
    )


@router.get("/{part_id}/edit", response_class=HTMLResponse, response_model=None)
def edit_part(
    part_id: int,
    request: Request,
    from_page: str = "",
    session: Session = Depends(get_session),
    user: User = Depends(require_auth),
) -> HTMLResponse:
    part = session.get(Part, part_id)
    return TEMPLATES.TemplateResponse(
        request,
        "parts/form.html",
        {
            "part": part,
            "categories": _categories(session),
            "error": None,
            "from_page": from_page,
            "user": user.username,
        },
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
    aliases: str = Form(""),
    from_page: str = Form(""),
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
        aliases,
        exclude_part_id=part_id,
    )
    if error:
        return TEMPLATES.TemplateResponse(
            request,
            "parts/form.html",
            {
                "part": part,
                "categories": _categories(session),
                "error": error,
                "from_page": from_page,
                "user": "",
            },
            status_code=400,
        )
    for key, val in fields.items():
        setattr(part, key, val)
    session.commit()
    _reconcile_equivalent_group(session, part)
    session.commit()
    url = f"/parts/{part_id}"
    if from_page == "stock":
        url += "?from_page=stock"
    return RedirectResponse(url, status_code=303)


@router.post("/{part_id}/delete", response_model=None)
def delete_part(part_id: int, session: Session = Depends(get_session)) -> RedirectResponse:
    part = session.get(Part, part_id)
    if part is not None:
        session.delete(part)
        session.commit()
    return RedirectResponse("/parts", status_code=303)
