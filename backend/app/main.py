import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.entities import router as entities_router
from app.api.gaps import router as gaps_router
from app.api.health import router as health_router
from app.config import get_settings
from app.db.neo4j import Neo4jClient
from app.db.schema import ensure_schema


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

    try:
        if await app.state.neo4j.ping():
            await ensure_schema(app.state.neo4j)
        else:
            logger.warning("Neo4j is unavailable; skipping schema initialization")
    except Exception:
        logger.exception("Neo4j schema initialization failed; continuing application startup")

    try:
        yield
    finally:
        await app.state.neo4j.close()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=True,
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    app.include_router(health_router)
    app.include_router(entities_router)
    app.include_router(gaps_router)
    return app


app = create_app()
