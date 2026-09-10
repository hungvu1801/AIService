import asyncio
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exception_handlers import (
    http_exception_handler,
    request_validation_exception_handler,
)
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core import models  # noqa: F401  — register tables
from app.core.database import AsyncSessionLocal, Base, engine
from app.core.seed_apps import load_plaza_apps, seed_apps
from app.engine.worker import data_root, job_worker
from app.routers import apps, jobs, users


@asynccontextmanager
async def lifespan(_app: FastAPI):
    async def init_db():
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            async with AsyncSessionLocal() as db:
                await seed_apps(db)
        except Exception as exc:
            print(f"Database not ready (pages still load): {exc}")

    asyncio.create_task(init_db())
    data_root()
    worker = asyncio.create_task(job_worker())
    yield
    worker.cancel()
    await engine.dispose()


app = FastAPI(title="AI Dancing", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

app.include_router(users.router, prefix="/api/users", tags=["users"])
app.include_router(jobs.router, prefix="/api/jobs", tags=["jobs"])
app.include_router(apps.router, prefix="/api/apps", tags=["apps"])


def page(request: Request, template: str, title: str, active: str = "", **extra):
    return templates.TemplateResponse(
        request,
        template,
        {"title": title, "active": active, **extra},
    )


@app.get("/", include_in_schema=False, name="home")
async def home(request: Request):
    plaza_apps = await load_plaza_apps()
    live_count = sum(1 for item in plaza_apps if item.is_live)
    return page(
        request,
        "home.html",
        "Apps",
        "plaza",
        apps=plaza_apps,
        live_count=live_count,
    )


@app.get("/studio", include_in_schema=False, name="studio_page")
async def studio_page(request: Request):
    return page(request, "studio.html", "Studio", "studio")


@app.get("/studio/pixel", include_in_schema=False, name="studio_pixel_page")
async def studio_pixel_page(request: Request):
    return page(request, "studio_pixel.html", "Pixel Art", "studio")


@app.get("/studio/minimax", include_in_schema=False, name="studio_minimax_page")
async def studio_minimax_page(request: Request):
    return page(request, "studio_minimax.html", "MiniMax H3", "studio")


@app.get("/studio/wan", include_in_schema=False, name="studio_wan_page")
async def studio_wan_page(request: Request):
    return page(request, "studio_wan.html", "Wan T2V", "studio")


@app.get("/jobs", include_in_schema=False, name="jobs_page")
async def jobs_page(request: Request):
    return page(request, "jobs.html", "Jobs", "jobs")


@app.get("/login", include_in_schema=False)
async def login_page(request: Request):
    return page(request, "login.html", "Log in")


@app.get("/register", include_in_schema=False)
async def register_page(request: Request):
    return page(request, "register.html", "Sign up")


@app.get("/account", include_in_schema=False)
async def account_page(request: Request):
    return page(request, "account.html", "Account")


@app.get("/forgot-password", include_in_schema=False)
async def forgot_password_page(request: Request):
    return page(request, "forgot_password.html", "Forgot password")


@app.get("/reset-password", include_in_schema=False)
async def reset_password_page(request: Request):
    response = page(request, "reset_password.html", "Reset password")
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@app.exception_handler(StarletteHTTPException)
async def general_http_exception_handler(
    request: Request, exception: StarletteHTTPException
):
    if request.url.path.startswith("/api"):
        return await http_exception_handler(request, exception)

    message = (
        exception.detail
        if exception.detail
        else "An error occurred. Please check your request and try again."
    )
    return templates.TemplateResponse(
        request,
        "error.html",
        {
            "status_code": exception.status_code,
            "title": exception.status_code,
            "message": message,
            "active": "",
        },
        status_code=exception.status_code,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exception: RequestValidationError
):
    if request.url.path.startswith("/api"):
        return await request_validation_exception_handler(request, exception)

    return templates.TemplateResponse(
        request,
        "error.html",
        {
            "status_code": status.HTTP_422_UNPROCESSABLE_CONTENT,
            "title": status.HTTP_422_UNPROCESSABLE_CONTENT,
            "message": "Invalid request. Please check your input and try again.",
            "active": "",
        },
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
    )


if __name__ == "__main__":
    import uvicorn

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
