"""匣中镜 AI Vlogger Studio 模块化单体入口。"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
import uvicorn

from api.covers import router as covers_router
from api.dialogue import router as dialogue_router
from api.dna import router as dna_router
from api.generation import router as generation_router
from api.library import router as library_router
from api.onboarding import router as onboarding_router
from api.pages import router as pages_router
from api.settings import router as settings_router
from api.state import router as state_router
from api.style import router as style_router
from config import BASE_DIR, app_config
from services.xiangzhongjing_store import initialize_store


@asynccontextmanager
async def lifespan(_application: FastAPI):
    initialize_store()
    yield


def create_app() -> FastAPI:
    application = FastAPI(
        title="匣中镜 AI Vlogger Studio",
        version="0.3.0-beta",
        description="服务单人真实创作流程的模块化单体应用。",
        lifespan=lifespan,
    )
    static_dir = BASE_DIR / "static"
    static_dir.mkdir(exist_ok=True)
    application.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    for router in (
        pages_router,
        generation_router,
        library_router,
        onboarding_router,
        dialogue_router,
        dna_router,
        settings_router,
        style_router,
        state_router,
        covers_router,
    ):
        application.include_router(router)

    return application


app = create_app()


if __name__ == "__main__":
    uvicorn.run("main:app", host=app_config.host, port=app_config.port, reload=False)
