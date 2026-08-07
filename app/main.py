"""BOMatch FastAPI 应用入口"""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import (
    clear_session_cookie,
    create_default_user_if_needed,
    get_optional_user,
    hash_password,
    set_session_cookie,
    verify_password,
)
from app.db import get_session, init_db
from app.models import Batch, Category, Location, Part, Project, User
from app.routers import batches as batches_router
from app.routers import categories as categories_router
from app.routers import locations as locations_router
from app.routers import parts as parts_router
from app.routers import projects as projects_router
from app.seed import seed_categories
from app.templating import STATIC_DIR, TEMPLATES


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    seed_categories()
    create_default_user_if_needed()
    yield


app = FastAPI(title="BOMatch", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

app.include_router(parts_router.router)
app.include_router(categories_router.router)
app.include_router(locations_router.router)
app.include_router(batches_router.router)
app.include_router(projects_router.router)


@app.get("/", response_class=HTMLResponse, response_model=None)
def home(
    request: Request, session: Session = Depends(get_session)
) -> HTMLResponse | RedirectResponse:
    user = get_optional_user(request, session)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    part_count = session.scalar(select(func.count(Part.id))) or 0
    category_count = session.scalar(select(func.count(Category.id))) or 0
    location_count = session.scalar(select(func.count(Location.id))) or 0
    project_count = session.scalar(select(func.count(Project.id))) or 0
    stock_units = session.scalar(select(func.coalesce(func.sum(Batch.quantity), 0))) or 0
    stock_value = (
        session.scalar(select(func.coalesce(func.sum(Batch.quantity * Batch.unit_price), 0.0)))
        or 0.0
    )
    return TEMPLATES.TemplateResponse(
        request,
        "index.html",
        {
            "user": user.username,
            "part_count": part_count,
            "category_count": category_count,
            "location_count": location_count,
            "project_count": project_count,
            "stock_units": stock_units,
            "stock_value": stock_value,
        },
    )


@app.get("/login", response_class=HTMLResponse, response_model=None)
def login_page(request: Request) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(request, "login.html", {"error": None})


@app.post("/login", response_model=None)
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    session: Session = Depends(get_session),
) -> HTMLResponse | RedirectResponse:
    user = session.execute(select(User).where(User.username == username)).scalar_one_or_none()
    if user is None or not verify_password(password, user.password_hash):
        return TEMPLATES.TemplateResponse(
            request, "login.html", {"error": "用户名或密码错误"}, status_code=401
        )
    # cookie 必须设在返回的 Response 对象上（FastAPI 会丢弃注入 response 上设置的 cookie）
    redirect = RedirectResponse("/", status_code=303)
    set_session_cookie(redirect, user.username)
    return redirect


@app.post("/logout", response_model=None)
def logout() -> RedirectResponse:
    redirect = RedirectResponse("/login", status_code=303)
    clear_session_cookie(redirect)
    return redirect


@app.get("/password", response_class=HTMLResponse, response_model=None)
def password_page(
    request: Request, session: Session = Depends(get_session)
) -> HTMLResponse | RedirectResponse:
    user = get_optional_user(request, session)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    return TEMPLATES.TemplateResponse(
        request, "password.html", {"error": None, "ok": False, "user": user.username}
    )


@app.post("/password", response_model=None)
def change_password(
    request: Request,
    old_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    session: Session = Depends(get_session),
) -> HTMLResponse | RedirectResponse:
    user = get_optional_user(request, session)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    if not verify_password(old_password, user.password_hash):
        error = "当前密码错误"
    elif len(new_password) < 6:
        error = "新密码至少 6 位"
    elif new_password != confirm_password:
        error = "两次输入的新密码不一致"
    else:
        error = None
        user.password_hash = hash_password(new_password)
        session.commit()
    return TEMPLATES.TemplateResponse(
        request,
        "password.html",
        {"error": error, "ok": error is None, "user": user.username},
        status_code=200 if error is None else 400,
    )
