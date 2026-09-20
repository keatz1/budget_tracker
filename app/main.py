from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.db import SessionLocal, run_migrations
from app.deps import NeedsLogin
from app.routers import (
    accounts,
    auth,
    budgets,
    categories,
    dashboards,
    home,
    imports,
    review,
    rules,
    sub_budgets,
    transactions,
)
from app.routers import settings as settings_router
from app.seed import seed


@asynccontextmanager
async def lifespan(_app: FastAPI):
    run_migrations()
    with SessionLocal() as db:
        seed(db)
    yield


app = FastAPI(title="Budget", lifespan=lifespan, docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.exception_handler(NeedsLogin)
async def _needs_login(_request: Request, exc: NeedsLogin):
    return RedirectResponse((exc.headers or {}).get("Location", "/login"), status_code=303)


@app.exception_handler(HTTPException)
async def _http_exc(request: Request, exc: HTTPException):
    if exc.status_code == 401 and exc.headers and "HX-Redirect" in exc.headers:
        return JSONResponse({}, status_code=401, headers=exc.headers)
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)


@app.get("/health")
def health():
    return {"ok": True}


app.include_router(auth.router)
app.include_router(accounts.router)
app.include_router(settings_router.router)
app.include_router(imports.router)
app.include_router(transactions.router)
app.include_router(categories.router)
app.include_router(review.router)
app.include_router(rules.router)
app.include_router(home.router)
app.include_router(budgets.router)
app.include_router(sub_budgets.router)
app.include_router(dashboards.router)
