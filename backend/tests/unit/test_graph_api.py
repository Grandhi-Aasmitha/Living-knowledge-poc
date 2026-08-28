from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.config import get_settings
from app.db.neo4j import get_neo4j_client
from app.main import create_app


class StubGraphClient:
    def session(self):
        return StubSessionContext()


class StubSessionContext:
    async def __aenter__(self):
        return StubSession()

    async def __aexit__(self, exc_type, exc, tb):
        return None


class StubSession:
    async def run(self, *_args, **_kwargs):
        return StubResult()


class StubResult:
    async def single(self):
        return {"rows": []}


def set_required_environment(monkeypatch) -> None:
    monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")
    monkeypatch.setenv("NEO4J_USERNAME", "neo4j")
    monkeypatch.setenv("NEO4J_PASSWORD", "test-password")
    monkeypatch.setenv("NEO4J_DATABASE", "neo4j")
    monkeypatch.setenv("FRONTEND_ORIGIN", "http://localhost:5173")


def make_client(monkeypatch) -> TestClient:
    set_required_environment(monkeypatch)
    get_settings.cache_clear()
    app = create_app()
    app.dependency_overrides[get_neo4j_client] = lambda: StubGraphClient()
    return TestClient(app)


def test_valid_statuses_accepted(monkeypatch) -> None:
    client = make_client(monkeypatch)

    response = client.get("/api/graph?statuses=CONFIRMED&statuses=PROPOSED")

    assert response.status_code == 200
    assert response.json() == {"nodes": [], "edges": [], "truncated": False}


def test_invalid_claim_status_rejected(monkeypatch) -> None:
    client = make_client(monkeypatch)

    response = client.get("/api/graph?statuses=UNKNOWN")

    assert response.status_code == 422


def test_valid_entity_type_accepted(monkeypatch) -> None:
    client = make_client(monkeypatch)

    response = client.get("/api/graph?entity_types=SERVICE")

    assert response.status_code == 200


def test_invalid_entity_type_rejected(monkeypatch) -> None:
    client = make_client(monkeypatch)

    response = client.get("/api/graph?entity_types=UNKNOWN")

    assert response.status_code == 422


def test_max_nodes_above_hard_max_rejected(monkeypatch) -> None:
    client = make_client(monkeypatch)

    response = client.get("/api/graph?max_nodes=501")

    assert response.status_code == 422


def test_max_nodes_zero_rejected(monkeypatch) -> None:
    client = make_client(monkeypatch)

    response = client.get("/api/graph?max_nodes=0")

    assert response.status_code == 422
