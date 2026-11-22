import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.ai.client import AIProviderError
from app.ai.answer_interpreter import AnswerInterpreter
from app.ai.provider import build_structured_ai_client
from app.ai.question_generator import QuestionGenerator
from app.api.assistant import router as assistant_router
from app.api.assessments import router as assessments_router
from app.auth import COOKIE_NAME, LocalAuth, router as auth_router
from app.api.claim_reviews import router as claim_reviews_router
from app.api.conflicts import router as conflicts_router
from app.api.curation import router as curation_router
from app.api.entities import router as entities_router
from app.api.gaps import router as gaps_router
from app.api.graph import router as graph_router
from app.api.health import router as health_router
from app.api.sources import router as sources_router
from app.api.learning import router as learning_router
from app.repositories.learning_repository import LearningRepository
from app.ai.entity_resolver import EntityResolver
from app.assistant.answer_generator import AnswerGenerator
from app.assistant.query_planner import QueryPlanner
from app.assistant.service import KnowledgeAssistantService
from app.assessment.workflow import AssessmentWorkflow
from app.config import REPOSITORY_ROOT, get_settings
from app.db.neo4j import Neo4jClient
from app.db.schema import ensure_schema
from app.repositories.claim_repository import ClaimRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.entity_repository import EntityRepository
from app.repositories.gap_repository import GapRepository
from app.repositories.knowledge_query_repository import KnowledgeQueryRepository
from app.repositories.source_repository import SourceRepository
from app.services.file_ingestion_service import FileIngestionService
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
    app.state.curation_unavailable_reason = "AI provider is unavailable"
    app.state.file_ingestion_service = None
    app.state.file_ingestion_unavailable_reason = "AI provider is unavailable"
    app.state.knowledge_assistant_service = None
    app.state.knowledge_assistant_unavailable_reason = "AI provider is unavailable"
    app.state.assessment_workflow = None
    app.state.assessment_unavailable_reason = "AI provider is unavailable"
    app.state.document_repository = DocumentRepository(app.state.neo4j)
    app.state.langgraph_checkpointer_context = None

    try:
        if await app.state.neo4j.ping():
            await ensure_schema(app.state.neo4j)
        else:
            logger.warning("Neo4j is unavailable; skipping schema initialization")
    except Exception:
        logger.exception("Neo4j schema initialization failed; continuing application startup")

    try:
        ai_client = build_structured_ai_client(settings)
        if settings.ai_provider != "local_rules":
            checkpoint_path = REPOSITORY_ROOT / settings.langgraph_checkpoint_db
            checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
            checkpointer_context = AsyncSqliteSaver.from_conn_string(str(checkpoint_path))
            checkpointer = await checkpointer_context.__aenter__()
            checkpointer.serde = JsonPlusSerializer(pickle_fallback=False, allowed_msgpack_modules=None)
            await checkpointer.setup()
            app.state.langgraph_checkpointer_context = checkpointer_context
        entity_repository = EntityRepository(app.state.neo4j)
        claim_repository = ClaimRepository(app.state.neo4j)
        source_repository = SourceRepository(app.state.neo4j)
        gap_repository = GapRepository(app.state.neo4j)
        if settings.ai_provider != "local_rules":
            app.state.curation_workflow = CurationWorkflow(
                entity_repository=entity_repository,
                claim_repository=claim_repository,
                source_repository=source_repository,
                gap_repository=gap_repository,
                question_generator=QuestionGenerator(ai_client),
                answer_interpreter=AnswerInterpreter(ai_client),
                checkpointer=checkpointer,
                entity_resolver=EntityResolver(ai_client, entity_repository, settings.entity_resolution_auto_match_threshold, settings.entity_resolution_max_candidates),
                learning_repository=LearningRepository(app.state.neo4j),
            )
        app.state.file_ingestion_service = FileIngestionService(
            ai_client=ai_client,
            source_repository=source_repository,
            document_repository=app.state.document_repository,
            entity_repository=entity_repository,
            claim_repository=claim_repository,
            upload_directory=settings.upload_directory,
            max_upload_size_mb=settings.max_upload_size_mb,
            max_chunk_chars=settings.max_chunk_chars,
            max_chunks_per_document=settings.max_chunks_per_document,
            entity_resolution_auto_match_threshold=settings.entity_resolution_auto_match_threshold,
            entity_resolution_max_candidates=settings.entity_resolution_max_candidates,
            learning_repository=LearningRepository(app.state.neo4j),
            require_explicit_relationships=settings.ai_provider == "local_rules",
            auto_confirm_file_claims=settings.auto_confirm_file_claims,
            extraction_audit_enabled=settings.extraction_audit_enabled and settings.ai_provider != "local_rules",
            pdf_ocr_enabled=settings.pdf_ocr_enabled,
        )
        if settings.ai_provider != "local_rules":
            app.state.knowledge_assistant_service = KnowledgeAssistantService(
                query_planner=QueryPlanner(ai_client),
                repository=KnowledgeQueryRepository(app.state.neo4j),
                answer_generator=AnswerGenerator(ai_client),
                max_claims=settings.assistant_max_claims,
                max_evidence_per_claim=settings.assistant_max_evidence_per_claim,
                max_evidence_chars=settings.assistant_max_evidence_chars,
                max_context_chars=settings.assistant_max_context_chars,
            )
            app.state.assessment_workflow = AssessmentWorkflow(
                repository=KnowledgeQueryRepository(app.state.neo4j),
                ai_client=ai_client,
                checkpointer=checkpointer,
            )
            app.state.curation_unavailable_reason = None
            app.state.knowledge_assistant_unavailable_reason = None
            app.state.assessment_unavailable_reason = None
        else:
            app.state.curation_unavailable_reason = "Local rules support document uploads only"
            app.state.knowledge_assistant_unavailable_reason = "Local rules support document uploads only"
            app.state.assessment_unavailable_reason = "An AI provider is required for assessments"
        app.state.file_ingestion_unavailable_reason = None
    except AIProviderError as error:
        app.state.curation_unavailable_reason = str(error)
        app.state.file_ingestion_unavailable_reason = str(error)
        app.state.knowledge_assistant_unavailable_reason = str(error)
        app.state.assessment_unavailable_reason = str(error)
        logger.warning("AI-backed workflows unavailable: %s", error)

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
    app.state.local_auth = LocalAuth(settings.app_password.get_secret_value() if settings.app_password else None)

    @app.middleware("http")
    async def protect_knowledge_api(request: Request, call_next):
        path = request.url.path
        if path.startswith("/api/") and not path.startswith("/api/auth/") and path != "/api/health" and request.method != "OPTIONS":
            if not app.state.local_auth.authenticated(request.cookies.get(COOKIE_NAME)):
                return JSONResponse({"detail": "Sign in required"}, status_code=401)
            if app.state.local_auth.required and request.method not in {"GET", "HEAD"}:
                origin = request.headers.get("origin")
                own_origin = f"{request.url.scheme}://{request.url.netloc}"
                if origin not in {settings.frontend_origin, own_origin}:
                    return JSONResponse({"detail": "Invalid request origin"}, status_code=403)
        return await call_next(request)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(entities_router)
    app.include_router(gaps_router)
    app.include_router(curation_router)
    app.include_router(sources_router)
    app.include_router(learning_router)
    app.include_router(graph_router)
    app.include_router(conflicts_router)
    app.include_router(assistant_router)
    app.include_router(assessments_router)
    app.include_router(claim_reviews_router)
    return app


app = create_app()
