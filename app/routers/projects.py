"""项目与 BOM 匹配路由：导入 BOM → 解析 → 按等效组匹配库存 → 缺料报告"""

import re
from typing import Any

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_auth
from app.db import get_session
from app.models import BOMItem, BOMOrder, Part, Project, User
from app.parsers.bom import (
    infer_category_from_unit,
    parse_bom_text,
    split_tolerance,
)
from app.parsers.part import part_canonical_key, resolve_value
from app.parsers.values import parse_value
from app.services.stock import find_part_for_canonical_key, stock_for_canonical_key
from app.templating import TEMPLATES

router = APIRouter(prefix="/projects", dependencies=[Depends(require_auth)])

_QUANTITY_RE = re.compile(r"\d+")


def _parse_quantity(text: str | None) -> int:
    if not text:
        return 1
    match = _QUANTITY_RE.search(text)
    return int(match.group()) if match else 1


def _find_by_supplier(session: Session, supplier: str) -> Part | None:
    """按立创编号反查库存料号（lcsc_code 字段；mpn 本身是立创编号格式时也匹配）。"""
    if not supplier:
        return None
    part = (
        session.execute(select(Part).where(Part.lcsc_code == supplier).order_by(Part.id))
        .scalars()
        .first()
    )
    if part is None and re.fullmatch(r"C\d+", supplier):
        part = (
            session.execute(select(Part).where(Part.mpn == supplier).order_by(Part.id))
            .scalars()
            .first()
        )
    return part


def _resolve_row(session: Session, row: dict) -> tuple[str, int | None]:
    """解析 BOM 行 → (canonical_key, 匹配到的料号 id 或 None)

    匹配顺序：① 立创编号反查 ② 按值+封装推断的等效键（无单位数值默认电阻）③ 按料号精确匹配。
    canonical_key 记录实际匹配到的料号等效键（否则为 BOM 推断键），
    使缺料统计与真实库存对齐。
    """
    value_raw = (row.get("value") or "").strip()
    mpn = (row.get("mpn") or "").strip()
    package = row.get("package") or ""
    supplier = (row.get("supplier_part") or "").strip()

    # ① 立创编号精确反查库存（BOM 常带立创编号，命中率最高）
    part = _find_by_supplier(session, supplier)

    bom_key = ""
    if part is None:
        # ② 优先整串解析："100nF" 的单位 F 不能被当成容差字母拆掉
        value_text, tolerance = value_raw, ""
        parsed = parse_value(value_raw)
        if parsed is None:
            # 整串无法解析（可能带 "10k 1%" / "104J" 容差后缀），拆分容差再试
            value_text, tolerance = split_tolerance(value_raw)
            parsed = parse_value(value_text)

        category = None
        if parsed is not None:
            category = infer_category_from_unit(parsed.unit)
            if category is None and parsed.unit == "":
                category = "电阻"  # 无单位数值默认电阻（BOM 常见）

        if category:
            value_num, unit = resolve_value(value_text, category)
            bom_key = part_canonical_key(
                category, mpn, value_num, unit, package or None, tolerance or None, None, None
            )
            part = find_part_for_canonical_key(session, bom_key)

    # ③ 料号精确匹配
    if part is None and mpn:
        part = (
            session.execute(select(Part).where(Part.mpn == mpn).order_by(Part.id)).scalars().first()
        )
    if part is None:
        canonical = bom_key or (f"X|{mpn.upper()}" if mpn else "X|")
    else:
        canonical = part.canonical_key
    return canonical, (part.id if part else None)


def _detail_context(session: Session, project: Project) -> dict[str, Any]:
    """渲染项目详情所需的上下文（含缺料汇总）"""
    items = list(project.bom_items)
    agg: dict[str, dict[str, Any]] = {}
    for item in items:
        key = item.canonical_key or "(未解析)"
        entry = agg.setdefault(
            key,
            {
                "qty": 0,
                "value_raw": item.value_raw,
                "package": item.package,
                "mpn": item.mpn_raw,
            },
        )
        entry["qty"] = int(entry["qty"]) + item.quantity
    summary: list[dict[str, Any]] = []
    total_short = 0
    total_items = 0
    # 已下单标记（按 项目+等效键 持久化，重新导入 BOM 后仍保留）
    order_flags = {
        o.canonical_key: o.ordered
        for o in session.execute(
            select(BOMOrder).where(BOMOrder.project_id == project.id)
        ).scalars()
    }
    for key, info in agg.items():
        stock = stock_for_canonical_key(session, key)
        need = int(info["qty"])
        short = max(0, need - stock)
        total_short += short
        total_items += need
        summary.append(
            {
                **info,
                "key": key,
                "stock": stock,
                "need": need,
                "short": short,
                "ordered": order_flags.get(key, False),
            }
        )
    summary.sort(key=lambda s: int(s["short"]), reverse=True)
    ordered_count = sum(1 for s in summary if s["ordered"])
    pending_count = sum(1 for s in summary if s["short"] > 0 and not s["ordered"])
    return {
        "project": project,
        "items": items,
        "summary": summary,
        "total_short": total_short,
        "total_items": total_items,
        "ordered_count": ordered_count,
        "pending_count": pending_count,
    }


@router.get("", response_class=HTMLResponse, response_model=None)
def list_projects(
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(require_auth),
) -> HTMLResponse:
    projects = session.query(Project).order_by(Project.id.desc()).all()
    return TEMPLATES.TemplateResponse(
        request, "projects/list.html", {"projects": projects, "user": user.username}
    )


@router.get("/new", response_class=HTMLResponse, response_model=None)
def new_project(request: Request, user: User = Depends(require_auth)) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(
        request, "projects/form.html", {"error": None, "user": user.username}
    )


@router.post("", response_model=None)
def create_project(
    name: str = Form(...),
    description: str = Form(""),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    name = name.strip()
    if not name:
        return RedirectResponse("/projects/new", status_code=303)
    project = Project(name=name, description=description.strip() or None)
    session.add(project)
    session.commit()
    return RedirectResponse(f"/projects/{project.id}", status_code=303)


@router.get("/{project_id}", response_class=HTMLResponse, response_model=None)
def project_detail(
    project_id: int,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(require_auth),
) -> HTMLResponse | RedirectResponse:
    project = session.get(Project, project_id)
    if project is None:
        return RedirectResponse("/projects", status_code=303)
    ctx = _detail_context(session, project)
    ctx["user"] = user.username
    ctx["error"] = None
    return TEMPLATES.TemplateResponse(request, "projects/detail.html", ctx)


@router.post("/{project_id}/bom", response_model=None)
def import_bom(
    project_id: int,
    request: Request,
    bom_text: str = Form(""),
    session: Session = Depends(get_session),
    user: User = Depends(require_auth),
) -> HTMLResponse | RedirectResponse:
    """解析粘贴的 BOM 文本并覆盖式重建该项目 BOM（重新匹配）"""
    project = session.get(Project, project_id)
    if project is None:
        return RedirectResponse("/projects", status_code=303)
    rows = parse_bom_text(bom_text)
    ctx = _detail_context(session, project)
    ctx["user"] = user.username
    if not rows:
        ctx["error"] = "未识别到有效行，请确认粘贴了带表头的 BOM 文本"
        return TEMPLATES.TemplateResponse(request, "projects/detail.html", ctx, status_code=400)
    for item in project.bom_items:
        session.delete(item)
    session.flush()
    for row in rows:
        canonical, part_id = _resolve_row(session, row)
        session.add(
            BOMItem(
                project_id=project.id,
                part_id=part_id,
                canonical_key=canonical,
                quantity=_parse_quantity(row.get("quantity")),
                designator=row.get("designator"),
                value_raw=row.get("value"),
                package=row.get("package"),
                mpn_raw=row.get("mpn"),
                manufacturer_raw=row.get("manufacturer"),
            )
        )
    session.commit()
    return RedirectResponse(f"/projects/{project_id}", status_code=303)


@router.post("/{project_id}/order", response_model=None)
def set_bom_order(
    project_id: int,
    canonical_key: str = Form(...),
    ordered: int = Form(0),
    session: Session = Depends(get_session),
    user: User = Depends(require_auth),
) -> dict[str, Any]:
    """标记/取消 BOM 缺料项已下单购买（按 项目+等效键）"""
    project = session.get(Project, project_id)
    if project is None:
        return {"ok": False}
    order = (
        session.execute(
            select(BOMOrder).where(
                BOMOrder.project_id == project_id,
                BOMOrder.canonical_key == canonical_key,
            )
        )
        .scalars()
        .first()
    )
    if order is None:
        order = BOMOrder(project_id=project_id, canonical_key=canonical_key)
        session.add(order)
    order.ordered = bool(ordered)
    session.commit()
    return {"ok": True, "ordered": order.ordered}


@router.post("/{project_id}/delete", response_model=None)
def delete_project(project_id: int, session: Session = Depends(get_session)) -> RedirectResponse:
    project = session.get(Project, project_id)
    if project is not None:
        session.delete(project)
        session.commit()
    return RedirectResponse("/projects", status_code=303)
