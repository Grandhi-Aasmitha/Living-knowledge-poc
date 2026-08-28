from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.config import get_settings
from app.db.neo4j import get_neo4j_client


def make_client(ping_result: bool) -> TestClient:
    async def ping() -> bool:
        return ping_result

    from app.main import create_app

    get_settings.cache_clear()
    app = create_app()
    app.dependency_overrides[get_neo4j_client] = lambda: SimpleNamespace(ping=ping)
    return TestClient(app)


def set_required_environment(monkeypatch) -> None:
    monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")
    monkeypatch.setenv("NEO4J_USERNAME", "neo4j")
    monkeypatch.setenv("NEO4J_PASSWORD", "test-password")
    monkeypatch.setenv("NEO4J_DATABASE", "neo4j")
    monkeypatch.setenv("FRONTEND_ORIGIN", "http://localhost:5173")


def test_health_returns_up_when_neo4j_ping_succeeds(monkeypatch) -> None:
    set_required_environment(monkeypatch)
    client = make_client(ping_result=True)

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "UP", "neo4j": "UP"}


def test_health_returns_degraded_when_neo4j_ping_fails(monkeypatch) -> None:
    set_required_environment(monkeypatch)
    client = make_client(ping_result=False)

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "DEGRADED", "neo4j": "DOWN"}
