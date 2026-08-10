"""库位 CRUD 路由"""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import require_auth
from app.db import get_session
from app.models import Location, User
from app.templating import TEMPLATES

router = APIRouter(prefix="/locations", dependencies=[Depends(require_auth)])


@router.get("", response_class=HTMLResponse, response_model=None)
def list_locations(
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(require_auth),
) -> HTMLResponse:
    locations = session.execute(select(Location).order_by(Location.name)).scalars().all()
    return TEMPLATES.TemplateResponse(
        request, "locations/list.html", {"locations": locations, "user": user.username}
    )


@router.post("", response_model=None)
def create_location(
    name: str = Form(...),
    description: str = Form(""),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    name = name.strip()
    if name:
        session.add(Location(name=name, description=description.strip() or None))
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
    return RedirectResponse("/locations", status_code=303)


@router.post("/{location_id}/delete", response_model=None)
def delete_location(location_id: int, session: Session = Depends(get_session)) -> RedirectResponse:
    location = session.get(Location, location_id)
    if location is not None:
        session.delete(location)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
    return RedirectResponse("/locations", status_code=303)
