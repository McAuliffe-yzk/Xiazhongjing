"""Public Streamable HTTP MCP adapter for Xiangzhongjing.

The tools intentionally wrap existing Xiangzhongjing use cases. They do not
reimplement generation, style loading, or book-support logic.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from typing import Annotated, Any, Literal

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import Field, ValidationError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from api.contracts import GenerateCopyRequest
from application.generation import generate_copy, parse_creation_materials as parse_creation_materials_usecase
from application.library_support import auto_insert_books, selected_book_sources
from config import BASE_DIR
from services.deepseek_service import load_writing_skill, writing_skill_stats
from services.cover_service import profile as creator_profile
from services.tavily_service import BOOKS
from services.xiangzhongjing_store import book_citation_summary, initialize_store


logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("xiangzhongjing.mcp")

MCP_HOST = os.getenv("MCP_HOST", os.getenv("HOST", "0.0.0.0"))
MCP_PORT = int(os.getenv("MCP_PORT", os.getenv("PORT", "8080")))
MCP_API_KEY = os.getenv("MCP_API_KEY", "").strip()
MCP_ALLOWED_HOSTS = [
    value.strip()
    for value in os.getenv("MCP_ALLOWED_HOSTS", "").split(",")
    if value.strip()
]

BookId = Literal["jianlai", "musk", "daode"]
TargetLength = Annotated[int | None, Field(default=None, ge=300, le=3000)]
MaterialText = Annotated[str, Field(min_length=1, max_length=50000)]
DraftText = Annotated[str, Field(min_length=1, max_length=20000)]


class MCPToolInputError(ValueError):
    code = "INVALID_INPUT"

    def __init__(self, message: str, details: str = ""):
        super().__init__(message)
        self.details = details


class OptionalApiKeyMiddleware(BaseHTTPMiddleware):
    """Enable bearer auth when configured without breaking public judging links."""

    def __init__(self, app, api_key: str):
        super().__init__(app)
        self.api_key = api_key

    async def dispatch(self, request: Request, call_next):
        if request.url.path in {"/", "/health", "/xiangzhongjing-demo"} or request.url.path.startswith("/static/"):
            return await call_next(request)
        authorization = request.headers.get("authorization", "")
        if authorization != f"Bearer {self.api_key}":
            return JSONResponse(
                {"error": "unauthorized", "message": "需要 Bearer MCP_API_KEY"},
                status_code=401,
            )
        return await call_next(request)


initialize_store()


def _transport_security() -> TransportSecuritySettings | None:
    """Keep local DNS-rebinding protection while supporting hosted proxies."""

    if MCP_ALLOWED_HOSTS:
        return TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=MCP_ALLOWED_HOSTS,
            allowed_origins=[
                f"https://{host}" for host in MCP_ALLOWED_HOSTS if not host.startswith("http")
            ],
        )
    if MCP_HOST in {"127.0.0.1", "localhost", "::1"}:
        return None
    return TransportSecuritySettings(enable_dns_rebinding_protection=False)


mcp = FastMCP(
    "匣中镜",
    instructions=(
        "这是一个面向具体创作者的个人创作 Agent。它优先使用匣中镜已发布的个人 DNA Skill，"
        "保留真实事实边界，以第一人称中文 Vlog 文案为主要产出。"
    ),
    host=MCP_HOST,
    port=MCP_PORT,
    stateless_http=True,
    json_response=True,
    transport_security=_transport_security(),
)


def _success(trace_id: str, started: float, data: Any) -> dict[str, Any]:
    elapsed_ms = round((time.perf_counter() - started) * 1000)
    logger.info("mcp tool completed trace_id=%s elapsed_ms=%s", trace_id, elapsed_ms)
    return {"ok": True, "trace_id": trace_id, "elapsed_ms": elapsed_ms, "data": data}


def _failure(trace_id: str, started: float, error: Exception) -> dict[str, Any]:
    elapsed_ms = round((time.perf_counter() - started) * 1000)
    if isinstance(error, ValidationError):
        code = "INVALID_INPUT"
        message = "输入参数不符合匣中镜的生成约束"
        details = error.errors()
    else:
        code = str(getattr(error, "code", "MCP_TOOL_FAILED"))
        message = str(error) or "匣中镜工具执行失败"
        details = str(getattr(error, "details", ""))
    logger.warning(
        "mcp tool failed trace_id=%s elapsed_ms=%s code=%s message=%s",
        trace_id,
        elapsed_ms,
        code,
        message,
    )
    return {
        "ok": False,
        "trace_id": trace_id,
        "elapsed_ms": elapsed_ms,
        "error": {"code": code, "message": message, "details": details},
    }


async def _run_tool(tool_name: str, action) -> dict[str, Any]:
    trace_id = str(uuid.uuid4())
    started = time.perf_counter()
    logger.info("mcp tool started trace_id=%s tool=%s", trace_id, tool_name)
    try:
        return _success(trace_id, started, await action())
    except Exception as error:  # MCP tools return a stable error contract.
        return _failure(trace_id, started, error)


@mcp.tool()
async def creator_identity() -> dict[str, Any]:
    """查看匣中镜当前启用的个人创作 DNA、版本和创作框架。"""

    async def action():
        version, _style = load_writing_skill()
        stats = writing_skill_stats()
        profile = creator_profile()
        return {
            "creator": profile.get("display_name") or "创作者",
            "product": "匣中镜",
            "style_version": version,
            "reference_documents": stats.get("reference_documents", 0),
            "framework": ["开头点题", "蒙太奇引入与发展", "高潮情绪堆叠", "下沉思考", "回引强化", "升华价值钩子"],
            "generation_chain": ["个人 DNA 撰写", "抖音 Vlog 优化", "本地书库直接引文支撑"],
            "expression_boundary": {
                "verbatim": "逐字使用用户明确要求保留的原句",
                "rewrite": "基于事实按个人 DNA 重新描述，默认模式",
                "elaborate": "原句加个人风格的解释性表达",
            },
        }

    return await _run_tool("creator_identity", action)


@mcp.tool()
async def parse_creation_materials(text: MaterialText) -> dict[str, Any]:
    """把一段创作输入拆解为主题、洞察、日常、事件、开头和收束素材。"""

    return await _run_tool("parse_creation_materials", lambda: parse_creation_materials_usecase(text))


@mcp.tool()
async def generate_vlog_copy(
    theme: Annotated[str, Field(min_length=1, max_length=300)],
    insight: Annotated[str, Field(min_length=1, max_length=6000)],
    daily: str = "",
    event: str = "",
    opening: str = "",
    quotes: str = "",
    ending_reference: str = "",
    selected_books: list[BookId] | None = None,
    narrative_mode: Literal["default", "parallelism", "six-stage", "contrast-first"] = "default",
    book_quote_strategy: Literal["restrained", "standard", "amplified"] = "standard",
    target_length_mode: Literal["auto", "manual"] = "auto",
    target_length: TargetLength = None,
) -> dict[str, Any]:
    """基于个人 DNA 生成完整中文 Vlog 文案，并按需要直接植入书库原句。"""

    async def action():
        if target_length_mode == "manual" and target_length is None:
            raise MCPToolInputError("手动字数模式必须填写 target_length", "允许范围为 300-3000 字")
        materials = {
            "theme": theme,
            "insight": insight,
            "daily": daily,
            "event": event,
            "opening": opening,
            "quotes": quotes,
            "ending_reference": ending_reference,
        }
        request = GenerateCopyRequest(
            materials=materials,
            selected_books=selected_books or [],
            generation_mode="fresh",
            narrative_mode=narrative_mode,
            book_quote_strategy=book_quote_strategy,
            target_length_mode=target_length_mode,
            target_length=target_length,
        )
        result = await generate_copy(request.service_payload())
        return {
            "copy": result.get("copy", ""),
            "char_count": len(str(result.get("copy", "")).replace("\n", "")),
            "style_version": result.get("style_version", ""),
            "narrative_mode": narrative_mode,
            "book_quote_strategy": book_quote_strategy,
            "trace": result.get("trace", []),
            "book_support": result.get("book_support", {}),
            "publish_pack": result.get("publish_pack", {}),
        }

    return await _run_tool("generate_vlog_copy", action)


@mcp.tool()
async def rewrite_current_copy(
    copy: DraftText,
    target_length_mode: Literal["auto", "manual"] = "auto",
    target_length: TargetLength = None,
    narrative_mode: Literal["default", "parallelism", "six-stage", "contrast-first"] = "default",
) -> dict[str, Any]:
    """只基于当前文案框中的文字重写，不回读原始创作素材。"""

    async def action():
        if target_length_mode == "manual" and target_length is None:
            raise MCPToolInputError("手动字数模式必须填写 target_length", "允许范围为 300-3000 字")
        request = GenerateCopyRequest(
            materials={},
            source_copy=copy,
            generation_mode="rewrite",
            narrative_mode=narrative_mode,
            target_length_mode=target_length_mode,
            target_length=target_length,
        )
        result = await generate_copy(request.service_payload())
        return {
            "copy": result.get("copy", ""),
            "char_count": len(str(result.get("copy", "")).replace("\n", "")),
            "style_version": result.get("style_version", ""),
            "source_materials_used": False,
            "trace": result.get("trace", []),
        }

    return await _run_tool("rewrite_current_copy", action)


@mcp.tool()
async def insert_book_quotes(
    draft: DraftText,
    selected_books: list[BookId],
    theme: str = "",
    insight: str = "",
    strategy: Literal["restrained", "standard", "amplified"] = "standard",
) -> dict[str, Any]:
    """从本地精神书库选择合适时机，植入逐字直接引用，不做转述。"""

    async def action():
        result = await auto_insert_books(
            {
                "draft": draft,
                "selected_books": selected_books,
                "book_quote_strategy": strategy,
                "materials": {"theme": theme, "insight": insight},
            }
        )
        return {
            "updated_copy": result.get("updated_copy", draft),
            "insertions": result.get("insertions", []),
            "citations": result.get("citations", []),
            "status": result.get("status", "none"),
            "reason": result.get("reason", ""),
            "strategy": result.get("strategy", {}),
        }

    return await _run_tool("insert_book_quotes", action)


@mcp.tool()
async def book_library_sources() -> dict[str, Any]:
    """查看已接入的精神书库来源与当前可用素材数量。"""

    async def action():
        summary = book_citation_summary(limit=12)
        return {
            "books": selected_book_sources(list(BOOKS.keys())),
            "summary": summary.get("summary", []),
            "recent": summary.get("recent", []),
            "quote_policy": "仅允许书库中的逐字直接引文，生成时优先判断植入时机。",
        }

    return await _run_tool("book_library_sources", action)


async def health(_request: Request) -> JSONResponse:
    return JSONResponse(
        {
            "status": "ok",
            "service": "xiangzhongjing-mcp",
            "transport": "streamable-http",
            "endpoint": "/mcp",
        }
    )


async def showcase(_request: Request) -> FileResponse:
    return FileResponse(
        BASE_DIR / "templates" / "xiangzhongjing_agent_showcase.html",
        media_type="text/html",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


app = mcp.streamable_http_app()
app.routes[:0] = [
    Route("/", showcase, methods=["GET"]),
    Route("/xiangzhongjing-demo", showcase, methods=["GET"]),
    Route("/health", health, methods=["GET"]),
    Mount("/static", app=StaticFiles(directory=str(BASE_DIR / "static")), name="static"),
]
if MCP_API_KEY:
    app.add_middleware(OptionalApiKeyMiddleware, api_key=MCP_API_KEY)


def main() -> None:
    import uvicorn

    uvicorn.run(app, host=MCP_HOST, port=MCP_PORT, log_level=os.getenv("LOG_LEVEL", "info").lower())


if __name__ == "__main__":
    main()
