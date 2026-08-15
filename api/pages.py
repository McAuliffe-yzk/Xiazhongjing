"""匣中镜页面路由。"""

from fastapi import APIRouter
from fastapi.requests import Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from config import BASE_DIR


router = APIRouter(tags=["pages"])
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@router.get("/", response_class=HTMLResponse)
async def index():
    return RedirectResponse(url="/xiangzhongjing-demo", status_code=302)


@router.get("/xiangzhongjing-prd", response_class=HTMLResponse)
async def xiangzhongjing_prd():
    return FileResponse(BASE_DIR / "templates" / "xiangzhongjing_prd.html", media_type="text/html")


@router.get("/xiangzhongjing-evaluation", response_class=HTMLResponse)
async def xiangzhongjing_evaluation():
    return FileResponse(
        BASE_DIR / "templates" / "xiangzhongjing_evaluation.html",
        media_type="text/html",
    )


@router.get("/xiangzhongjing-demo", response_class=HTMLResponse)
async def xiangzhongjing_demo(request: Request):
    response = templates.TemplateResponse(
        request=request,
        name="xiangzhongjing_demo.html",
        context={},
    )
    response.headers["Cache-Control"] = "no-store, max-age=0"
    return response
