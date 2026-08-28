import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.ai.answer_interpreter import AnswerInterpreter
from app.ai.model import build_ai_model
from app.ai.question_generator import QuestionGenerator
from app.api.curation import router as curation_router
from app.api.entities import router as entities_router
from app.api.gaps import router as gaps_router
from app.api.health import router as health_router
from app.config import REPOSITORY_ROOT, get_settings
from app.db.neo4j import Neo4jClient
from app.db.schema import ensure_schema
from app.repositories.claim_repository import ClaimRepository
from app.repositories.entity_repository import EntityRepository
from app.repositories.gap_repository import GapRepository
from app.repositories.source_repository import SourceRepository
from app.workflows.curation import CurationWorkflow


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    app.state.neo4j = Neo4jClient(
        uri=settings.neo4j_uri,
        username=settings.neo4j_username,
        password=settings.neo4j_password,
        database=settings.neo4j_database,
    )
    app.state.curation_workflow = None
    app.state.curation_unavailable_reason = "Azure OpenAI configuration is incomplete"
    app.state.langgraph_checkpointer_context = None

    try:
        if await app.state.neo4j.ping():
            await ensure_schema(app.state.neo4j)
        else:
            logger.warning("Neo4j is unavailable; skipping schema initialization")
    except Exception:
        logger.exception("Neo4j schema initialization failed; continuing application startup")

    ai_model = build_ai_model(settings)
    if ai_model is not None:
        checkpoint_path = REPOSITORY_ROOT / settings.langgraph_checkpoint_db
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        checkpointer_context = AsyncSqliteSaver.from_conn_string(str(checkpoint_path))
        checkpointer = await checkpointer_context.__aenter__()
        checkpointer.serde = JsonPlusSerializer(pickle_fallback=False, allowed_msgpack_modules=None)
        await checkpointer.setup()
        app.state.langgraph_checkpointer_context = checkpointer_context
        app.state.curation_workflow = CurationWorkflow(
            entity_repository=EntityRepository(app.state.neo4j),
            claim_repository=ClaimRepository(app.state.neo4j),
            source_repository=SourceRepository(app.state.neo4j),
            gap_repository=GapRepository(app.state.neo4j),
            question_generator=QuestionGenerator(ai_model),
            answer_interpreter=AnswerInterpreter(ai_model),
            checkpointer=checkpointer,
        )
        app.state.curation_unavailable_reason = None

    try:
        yield
    finally:
        checkpointer_context = getattr(app.state, "langgraph_checkpointer_context", None)
        if checkpointer_context is not None:
            await checkpointer_context.__aexit__(None, None, None)
        await app.state.neo4j.close()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    app.include_router(health_router)
    app.include_router(entities_router)
    app.include_router(gaps_router)
    app.include_router(curation_router)
    return app


app = create_app()
