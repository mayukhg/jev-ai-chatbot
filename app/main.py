"""FastAPI entrypoint: wires the Jev client, API routes, and the static workbench."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.core.client import JevClient
from app.core.config import Settings, get_settings

STATIC_DIR = Path(__file__).parent / "static"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        notice = settings.setup_notice()
        if notice:
            print(notice, flush=True)
        mode = "MOCK" if settings.effective_mock_mode else "LIVE"
        print(f"[JEV] {mode} mode · model={settings.jev_model}", flush=True)
        yield
        await app.state.jev_client.aclose()

    app = FastAPI(title="Jev Decision Engine Workbench", version="0.1.0", lifespan=lifespan)
    app.state.jev_client = JevClient(settings)
    app.include_router(router)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    return app


app = create_app()
