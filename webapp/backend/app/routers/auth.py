"""Account routes: signup, login, "who am I"."""
from __future__ import annotations
from fastapi import APIRouter, HTTPException, Request

from .. import auth as auth_store
from ..schemas import SignupRequest, LoginRequest, AuthResponse, MeResponse

router = APIRouter()


@router.post("/api/auth/signup", response_model=AuthResponse)
def auth_signup(req: SignupRequest):
    err = auth_store.validate_username(req.username) or auth_store.validate_password(req.password)
    if err:
        raise HTTPException(400, err)
    try:
        user = auth_store.create_user(req.username, req.password)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    token = auth_store.make_token(user["id"], user["username"], 0)  # fresh row, token_version defaults to 0
    return AuthResponse(token=token, username=user["username"])


@router.post("/api/auth/login", response_model=AuthResponse)
def auth_login(req: LoginRequest):
    user = auth_store.get_user_by_username(req.username)
    if user is None or not auth_store.verify_password(req.password, user["salt"], user["pw_hash"]):
        raise HTTPException(401, "Wrong username or password")
    token = auth_store.make_token(user["id"], user["username"], user["token_version"])
    return AuthResponse(token=token, username=user["username"])


@router.get("/api/auth/me", response_model=MeResponse)
def auth_me(request: Request):
    return MeResponse(username=request.state.username)


@router.post("/api/auth/logout")
def auth_logout(request: Request):
    """Invalidates every token for this account, this one included — there's
    no per-device session tracking here, so there's nothing narrower than
    "everywhere" to log out of (see auth_store.bump_token_version)."""
    auth_store.bump_token_version(request.state.user_id)
    return {"ok": True}
