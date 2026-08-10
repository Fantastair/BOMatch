"""类别 CRUD 路由"""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import require_auth
from app.db import get_session
from app.models import Category, Part, User
from app.templating import TEMPLATES

router = APIRouter(prefix="/categories", dependencies=[Depends(require_auth)])


@router.get("", response_class=HTMLResponse, response_model=None)
def list_categories(
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(require_auth),
) -> HTMLResponse:
    categories = session.execute(
        select(Category, func.count(Part.id))
        .outerjoin(Part, Part.category_id == Category.id)
        .group_by(Category.id)
        .order_by(Category.sort_order, Category.id)
    ).all()
    return TEMPLATES.TemplateResponse(
        request, "categories/list.html", {"categories": categories, "user": user.username}
    )


@router.post("", response_model=None)
def create_category(
    name: str = Form(...),
    description: str = Form(""),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    name = name.strip()
    if name:
        session.add(Category(name=name, description=description.strip() or None))
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
    return RedirectResponse("/categories", status_code=303)


@router.post("/{category_id}/delete", response_model=None)
def delete_category(category_id: int, session: Session = Depends(get_session)) -> RedirectResponse:
    category = session.get(Category, category_id)
    if category is not None:
        session.delete(category)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
    return RedirectResponse("/categories", status_code=303)
