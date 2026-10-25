import hashlib
import hmac
import secrets
import time

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel


COOKIE_NAME = "living_knowledge_session"
SESSION_SECONDS = 8 * 60 * 60


class LoginRequest(BaseModel):
    password: str


class SessionResponse(BaseModel):
    required: bool
    authenticated: bool


class LocalAuth:
    def __init__(self, password: str | None) -> None:
        self._password = password if password else None
        self._signing_key = secrets.token_bytes(32)

    @property
    def required(self) -> bool:
        return self._password is not None

    def login(self, password: str) -> str:
        if self._password is None or not hmac.compare_digest(password, self._password):
            raise HTTPException(status_code=401, detail="Invalid password")
        expires = int(time.time()) + SESSION_SECONDS
        nonce = secrets.token_hex(16)
        payload = f"{expires}.{nonce}"
        signature = hmac.new(self._signing_key, payload.encode(), hashlib.sha256).hexdigest()
        return f"{payload}.{signature}"

    def authenticated(self, token: str | None) -> bool:
        if not self.required:
            return True
        if token is None:
            return False
        try:
            expires_text, nonce, signature = token.split(".")
            expires = int(expires_text)
        except (ValueError, TypeError):
            return False
        if expires < time.time() or len(nonce) != 32 or len(signature) != 64:
            return False
        payload = f"{expires_text}.{nonce}"
        expected = hmac.new(self._signing_key, payload.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature, expected)


router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/session", response_model=SessionResponse)
async def session(request: Request) -> SessionResponse:
    auth: LocalAuth = request.app.state.local_auth
    return SessionResponse(required=auth.required, authenticated=auth.authenticated(request.cookies.get(COOKIE_NAME)))


@router.post("/login", response_model=SessionResponse)
async def login(request: Request, credentials: LoginRequest, response: Response) -> SessionResponse:
    auth: LocalAuth = request.app.state.local_auth
    token = auth.login(credentials.password)
    response.set_cookie(
        COOKIE_NAME, token, max_age=SESSION_SECONDS, httponly=True,
        samesite="strict", secure=request.url.scheme == "https", path="/api",
    )
    return SessionResponse(required=True, authenticated=True)


@router.post("/logout", response_model=SessionResponse)
async def logout(request: Request, response: Response) -> SessionResponse:
    response.delete_cookie(COOKIE_NAME, path="/api")
    auth: LocalAuth = request.app.state.local_auth
    return SessionResponse(required=auth.required, authenticated=False)
