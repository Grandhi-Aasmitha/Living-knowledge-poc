from fastapi.testclient import TestClient

from app.auth import LocalAuth
from app.main import create_app


def test_shared_password_protects_knowledge_api_and_checks_write_origin() -> None:
    app = create_app()
    app.state.local_auth = LocalAuth("test-password")
    client = TestClient(app)

    assert client.get("/api/auth/session").json() == {"required": True, "authenticated": False}
    assert client.get("/api/gaps").status_code == 401
    assert client.post("/api/auth/login", json={"password": "wrong"}).status_code == 401
    assert client.post("/api/auth/login", json={"password": "test-password"}).status_code == 200
    assert client.get("/api/auth/session").json() == {"required": True, "authenticated": True}
    assert client.post("/api/gaps/detect", headers={"Origin": "https://untrusted.example"}).status_code == 403
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/gaps").status_code == 401


def test_session_token_expires_and_rejects_tampering() -> None:
    auth = LocalAuth("test-password")
    token = auth.login("test-password")
    assert auth.authenticated(token)
    assert not auth.authenticated(token + "x")
    assert not LocalAuth("test-password").authenticated(token)
