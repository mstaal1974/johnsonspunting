import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from starlette.middleware.sessions import SessionMiddleware  # noqa: E402

from app.db import init_db  # noqa: E402
from app.routes import admin, public  # noqa: E402

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Johnsons Punt Club", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SECRET_KEY", "dev-only-change-me"))
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# Browsers request /favicon.ico on their own, whatever the page's <link rel="icon"> says
@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse(os.path.join(STATIC_DIR, "favicon.svg"), media_type="image/svg+xml")


app.include_router(public.router)
app.include_router(admin.router)
