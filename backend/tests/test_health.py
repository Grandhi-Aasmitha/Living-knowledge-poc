import os
from types import SimpleNamespace

os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USERNAME", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "test-password")
os.environ.setdefault("NEO4J_DATABASE", "neo4j")
os.environ.setdefault("FRONTEND_ORIGIN", "http://localhost:5173")

from fastapi.testclient import TestClient

from app.config import get_settings
from app.db.neo4j import get_neo4j_client
from app.main import create_app


def make_client(ping_result: bool) -> TestClient:
    async def ping() -> bool:
        return ping_result

    get_settings.cache_clear()
    app = create_app()
    app.dependency_overrides[get_neo4j_client] = lambda: SimpleNamespace(ping=ping)
    return TestClient(app)


def test_health_returns_up_when_neo4j_ping_succeeds() -> None:
    client = make_client(ping_result=True)

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "UP", "neo4j": "UP"}


def test_health_returns_degraded_when_neo4j_ping_fails() -> None:
    client = make_client(ping_result=False)

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "DEGRADED", "neo4j": "DOWN"}
