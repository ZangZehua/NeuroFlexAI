from __future__ import annotations

import logging
import re
import shutil
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from openai import APIConnectionError, APITimeoutError, AuthenticationError, OpenAI, RateLimitError
from pydantic import BaseModel, Field

from .agent import Agent
from .cad import CADArtifactStore, CADPlanner
from .client import create_chat_client
from .config import Settings
from .documents import SUPPORTED_SUFFIXES
from .evaluate import Evaluator
from .feedback import EvolutionStore
from .knowledge_bases import KnowledgeBaseManager
from .planner import Reflector, SolutionPlanner
from .rag import LocalKnowledgeBase
from .skills import SkillManager
from .tools import Permission, Tool, ToolRegistry

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
SAFE_NAME = re.compile(r"[^A-Za-z0-9._\-\u4e00-\u9fff]+")
logger = logging.getLogger(__name__)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    limit: int = Field(default=5, ge=1, le=10)


class CADGenerateRequest(BaseModel):
    description: str = Field(min_length=10, max_length=12000)
    limit: int = Field(default=5, ge=0, le=10)


class IngestRequest(BaseModel):
    force: bool = False


class DeleteRequest(BaseModel):
    name: str = Field(min_length=1)


class KnowledgeBaseNameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class KnowledgeBaseSelectRequest(BaseModel):
    id: str = Field(min_length=1, max_length=64)


class SkillRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    content: str = Field(min_length=1, max_length=20000)


class SkillSelectRequest(BaseModel):
    id: str = Field(min_length=1, max_length=64)


class FeedbackSource(BaseModel):
    source: str = Field(min_length=1, max_length=500)


class FeedbackRequest(BaseModel):
    rating: str = Field(pattern="^(good|bad)$")
    answer_id: str | None = Field(default=None, max_length=64)
    correction: str | None = Field(default=None, max_length=5000)
    sources: list[FeedbackSource] | None = Field(default=None, max_length=20)


def _safe_filename(name: str) -> str:
    cleaned = SAFE_NAME.sub("_", Path(name).name).strip("._")
    return cleaned or "upload.bin"


def _http_error(exc: Exception, prefix: str = "") -> HTTPException:
    if isinstance(exc, APITimeoutError):
        return HTTPException(
            status_code=504,
            detail=f"{prefix}模型 API 连接超时，请检查 DNS、网络或 HTTPS_PROXY 配置",
        )
    if isinstance(exc, APIConnectionError):
        return HTTPException(
            status_code=503,
            detail=f"{prefix}无法连接模型 API，请检查 DNS、网络或 HTTPS_PROXY 配置",
        )
    if isinstance(exc, RateLimitError):
        return HTTPException(
            status_code=429,
            detail=f"{prefix}模型 API 请求受限或账户配额不足，请检查 API 账单与配额",
        )
    if isinstance(exc, AuthenticationError):
        return HTTPException(status_code=401, detail=f"{prefix}模型 API 密钥无效")
    return HTTPException(status_code=500, detail=f"{prefix}{exc}")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.knowledge_dir.mkdir(parents=True, exist_ok=True)
    manager = KnowledgeBaseManager(settings.knowledge_dir)
    skill_manager = SkillManager(settings.skill_dir)

    app = FastAPI(title="wowo-agent", version="0.2.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    state: dict[str, Any] = {"client": None, "knowledge": {}, "evolution": {}}

    def get_client() -> Any:
        settings.require_api_key()
        if state["client"] is None:
            state["client"] = create_chat_client(settings)
        return state["client"]

    def get_evolution() -> EvolutionStore:
        current = manager.current()
        base_id = current["id"]
        if base_id not in state["evolution"]:
            state["evolution"][base_id] = EvolutionStore(current["path"] / ".evolution")
        return state["evolution"][base_id]

    def get_knowledge() -> LocalKnowledgeBase:
        current = manager.current()
        base_id = current["id"]
        if base_id not in state["knowledge"]:
            state["knowledge"][base_id] = LocalKnowledgeBase(
                current["path"],
                client=get_client() if settings.embeddings_enabled else None,
                embedding_model=settings.embedding_model,
                evolution=get_evolution(),
            )
        return state["knowledge"][base_id]

    def get_agent() -> Agent:
        knowledge = get_knowledge()
        registry = ToolRegistry()
        registry.register(
            Tool(
                name="retrieve_documents",
                description="从本地知识库检索与问题有关的文档片段（基于 embedding 相似度）。",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "检索问题或关键词"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 10},
                    },
                    "required": ["query", "limit"],
                    "additionalProperties": False,
                },
                handler=knowledge.search,
                permission=Permission.ALLOW,
            )
        )
        return Agent(
            get_client(),
            settings.model,
            registry,
            settings.max_tool_rounds,
            skill_instruction=skill_manager.current()["content"],
        )

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        current = manager.current()
        current_skill = skill_manager.current()
        return {
            "ok": True,
            "provider": "openai-compatible",
            "model": settings.model,
            "embedding_model": (
                settings.embedding_model if settings.embeddings_enabled else "local-keyword"
            ),
            "knowledge_dir": str(current["path"]),
            "knowledge_base": {"id": current["id"], "name": current["name"]},
            "skill": {"id": current_skill["id"], "name": current_skill["name"]},
            "supported": sorted(SUPPORTED_SUFFIXES),
        }

    @app.get("/api/knowledge-bases")
    def list_knowledge_bases() -> dict[str, Any]:
        return manager.list()

    @app.post("/api/knowledge-bases")
    def create_knowledge_base(body: KnowledgeBaseNameRequest) -> dict[str, Any]:
        try:
            created = manager.create(body.name)
            return {"knowledge_base": created, **manager.list()}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.put("/api/knowledge-bases/current")
    def select_knowledge_base(body: KnowledgeBaseSelectRequest) -> dict[str, Any]:
        try:
            selected = manager.select(body.id)
            return {"knowledge_base": selected, **manager.list()}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc.args[0])) from exc

    @app.patch("/api/knowledge-bases/{base_id}")
    def rename_knowledge_base(
        base_id: str,
        body: KnowledgeBaseNameRequest,
    ) -> dict[str, Any]:
        try:
            renamed = manager.rename(base_id, body.name)
            return {"knowledge_base": renamed, **manager.list()}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc.args[0])) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.delete("/api/knowledge-bases/{base_id}")
    def delete_knowledge_base(base_id: str) -> dict[str, Any]:
        try:
            result = manager.delete(base_id)
            state["knowledge"].pop(base_id, None)
            return {**result, **manager.list()}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc.args[0])) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/skills")
    def list_skills() -> dict[str, Any]:
        return skill_manager.list()

    @app.post("/api/skills")
    def create_skill(body: SkillRequest) -> dict[str, Any]:
        try:
            created = skill_manager.create(body.name, body.content)
            return {"skill": created, **skill_manager.list()}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.put("/api/skills/current")
    def select_skill(body: SkillSelectRequest) -> dict[str, Any]:
        try:
            selected = skill_manager.select(body.id)
            return {"skill": selected, **skill_manager.list()}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc.args[0])) from exc

    @app.patch("/api/skills/{skill_id}")
    def update_skill(skill_id: str, body: SkillRequest) -> dict[str, Any]:
        try:
            updated = skill_manager.update(skill_id, body.name, body.content)
            return {"skill": updated, **skill_manager.list()}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc.args[0])) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.delete("/api/skills/{skill_id}")
    def delete_skill(skill_id: str) -> dict[str, Any]:
        try:
            result = skill_manager.delete(skill_id)
            return {**result, **skill_manager.list()}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc.args[0])) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/documents")
    def list_documents() -> dict[str, Any]:
        docs = get_knowledge().list_documents()
        return {"documents": docs}

    @app.post("/api/upload")
    async def upload(files: list[UploadFile] = File(...)) -> dict[str, Any]:
        knowledge = get_knowledge()
        uploaded = []
        for file in files:
            suffix = Path(file.filename or "").suffix.lower()
            if suffix not in SUPPORTED_SUFFIXES:
                raise HTTPException(
                    status_code=400,
                    detail=f"不支持的文件类型: {suffix or '(无扩展名)'}",
                )
            filename = _safe_filename(file.filename or f"upload{suffix}")
            target = knowledge.root / filename
            with target.open("wb") as out:
                shutil.copyfileobj(file.file, out)
            try:
                result = knowledge.ingest_file(target)
            except Exception as exc:
                logger.exception("Failed to embed uploaded file %s", filename)
                raise _http_error(exc, "Embedding 失败：") from exc
            uploaded.append(result)
        return {"uploaded": uploaded}

    @app.post("/api/ingest")
    def ingest(body: IngestRequest) -> dict[str, Any]:
        try:
            return get_knowledge().ingest_all(force=body.force)
        except Exception as exc:
            logger.exception("Failed to ingest knowledge base")
            raise _http_error(exc, "索引失败：") from exc

    @app.post("/api/search")
    def search(body: ChatRequest) -> dict[str, Any]:
        try:
            return get_knowledge().search(body.message, body.limit)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    _SOLUTION_KEYWORDS = (
        "方案", "做法", "怎么实现", "如何实现", "方案设计", "设计一个", "推荐",
        "多种方案", "给出", "怎么做", "思路", "路线", "技术方案", "项目方案",
    )

    def _is_solution_request(message: str) -> bool:
        return any(keyword in message for keyword in _SOLUTION_KEYWORDS)

    @app.post("/api/chat")
    def chat(body: ChatRequest) -> dict[str, Any]:
        try:
            agent = get_agent()
            draft = agent.run(body.message)
            retrieval = agent.last_tool_outputs.get("retrieve_documents", {})
            sources = retrieval.get("results", []) if isinstance(retrieval, dict) else []
            client = get_client()

            reflection = Reflector(client, settings.model).reflect_answer(
                body.message, draft, sources
            )
            answer = reflection.revised_answer or draft

            options = []
            if _is_solution_request(body.message):
                try:
                    bundle = SolutionPlanner(client, settings.model).plan(body.message, sources)
                    options = [option.model_dump() for option in bundle.options]
                    recommendation = bundle.recommendation
                except Exception:
                    recommendation = ""
                    options = []
            else:
                recommendation = ""

            answer_id = uuid.uuid4().hex[:16]
            return {
                "answer_id": answer_id,
                "answer": answer,
                "sources": sources[: body.limit],
                "options": options,
                "recommendation": recommendation,
                "reflection": reflection.model_dump(),
            }
        except Exception as exc:
            logger.exception("Chat request failed")
            raise _http_error(exc) from exc

    @app.post("/api/feedback")
    def submit_feedback(body: FeedbackRequest) -> dict[str, Any]:
        """Record human (or experiment) feedback and evolve knowledge/capabilities."""
        try:
            store = get_evolution()
            result = Evaluator(store).record(
                rating=body.rating,
                answer_id=body.answer_id,
                correction=body.correction,
                sources=[s.source for s in body.sources] if body.sources else None,
            )
            current_skill = skill_manager.current()
            if current_skill["id"] != SkillManager.DEFAULT_ID:
                result["capability"] = store.apply_capability_feedback(
                    current_skill["id"], body.rating
                )
            capability_changes = skill_manager.evolve(store.capability_table())
            result["skill_evolve"] = capability_changes
            return result
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise _http_error(exc, "反馈处理失败：") from exc

    @app.get("/api/evolution")
    def evolution_report() -> dict[str, Any]:
        try:
            report = Evaluator(get_evolution()).report()
            report["skill"] = skill_manager.list()
            return report
        except Exception as exc:
            raise _http_error(exc, "获取进化报告失败：") from exc

    @app.post("/api/cad/generate")
    def generate_cad(body: CADGenerateRequest) -> dict[str, Any]:
        """Generate a validated manufacturing plan and deterministic 2D CAD files."""
        try:
            knowledge = get_knowledge()
            retrieval = knowledge.search(body.description, body.limit) if body.limit else {"results": []}
            sources = retrieval.get("results", [])
            plan = CADPlanner(get_client(), settings.model).create_plan(body.description, sources)
            artifact = CADArtifactStore(manager.current()["path"]).create(plan)
            return {
                "plan": plan.model_dump(),
                "artifact": artifact,
                "sources": sources[: body.limit],
            }
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("CAD generation failed")
            raise _http_error(exc, "CAD 生成失败：") from exc

    @app.get("/api/cad/files/{job_id}/{filename}")
    def download_cad_file(job_id: str, filename: str) -> FileResponse:
        try:
            path = CADArtifactStore(manager.current()["path"]).resolve(job_id, filename)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        media_types = {
            "drawing.dxf": "application/dxf",
            "drawing.dwg": "application/acad",
            "preview.svg": "image/svg+xml",
            "plan.json": "application/json",
        }
        download_name = filename if filename != "preview.svg" else None
        return FileResponse(path, media_type=media_types[filename], filename=download_name)

    @app.delete("/api/documents")
    def delete_document(body: DeleteRequest) -> dict[str, Any]:
        name = Path(body.name).name
        try:
            return get_knowledge().delete_document(name)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    if WEB_DIR.exists():
        app.mount("/assets", StaticFiles(directory=WEB_DIR / "assets"), name="assets")

        @app.get("/")
        def index() -> FileResponse:
            return FileResponse(WEB_DIR / "index.html")

    return app


app = create_app()


def main() -> None:
    import uvicorn

    settings = Settings.from_env()
    uvicorn.run(
        "wowo_agent.server:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )


if __name__ == "__main__":
    main()
