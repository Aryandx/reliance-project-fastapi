"""
auth_router.py
────────────────────────────────────────────────────────────────────────────────
DROP INTO:  app/routers/auth_router.py

MOUNT in your main.py / app.py (one line):
    from app.routers.auth_router import router as auth_router, get_current_user, require_role
    app.include_router(auth_router, prefix="/api/auth", tags=["Auth"])

USE in any other router to protect endpoints:
    from app.routers.auth_router import get_current_user, require_role

    @router.get("/something")
    async def my_endpoint(user: dict = Depends(get_current_user)):
        ...

    @router.get("/manager-only")
    async def manager_endpoint(user: dict = Depends(require_role("Manager", "HR"))):
        ...

ENV VARS (add to your .env):
    JWT_SECRET                  — access token signing secret (keep long & private)
    REFRESH_TOKEN_SECRET        — refresh token signing secret (different from JWT_SECRET)
    ACCESS_TOKEN_EXPIRE_MINUTES — default 15
    REFRESH_TOKEN_EXPIRE_DAYS   — default 7
    USER_COLLECTION             — MongoDB collection name for users (default: "users")
    REFRESH_TOKEN_COLLECTION    — MongoDB collection for refresh tokens (default: "refresh_tokens")
    SSO_ID_FIELD                — field on user doc that holds the unique employee ID
    PASSWORD_HASH_FIELD         — field name where bcrypt hash is stored (default: "passwordHash")

ASSUMPTIONS:
    - Your FastAPI app stores the Motor DB client at  request.app.state.db
    - User documents have at minimum: name, email, role, isActive, <PASSWORD_HASH_FIELD>
    - Role strings: "HR" | "Manager" | "Tech Lead" | "Buddy" | "Intern"
────────────────────────────────────────────────────────────────────────────────
"""

import os
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

from bson import ObjectId
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────
ACCESS_SECRET   = os.getenv("JWT_SECRET",                   "change_this_access_secret_min_32_chars")
REFRESH_SECRET  = os.getenv("REFRESH_TOKEN_SECRET",         "change_this_refresh_secret_min_32_chars")
ACCESS_MINS     = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "15"))
REFRESH_DAYS    = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS",   "7"))
ALGORITHM       = "HS256"

USER_COL        = os.getenv("USER_COLLECTION",           "users")
REFRESH_COL     = os.getenv("REFRESH_TOKEN_COLLECTION",  "refresh_tokens")
SSO_ID_FIELD    = os.getenv("SSO_ID_FIELD",              "employeeId")
PASSWORD_FIELD  = os.getenv("PASSWORD_HASH_FIELD",       "passwordHash")

VALID_ROLES = {"HR", "Manager", "Tech Lead", "Buddy", "Intern"}

pwd_ctx  = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer(auto_error=False)
router   = APIRouter()


# ── Internal helpers ──────────────────────────────────────────────────────────
def _db(request: Request):
    return request.app.state.db


def _safe_user(doc: dict) -> dict:
    """Strip sensitive fields and convert ObjectId → str for API responses."""
    out = {}
    for k, v in doc.items():
        if k == PASSWORD_FIELD:
            continue
        out[k] = str(v) if isinstance(v, ObjectId) else v
    return out


def _make_access_token(user: dict) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            SSO_ID_FIELD: user.get(SSO_ID_FIELD, str(user.get("_id", ""))),
            "name":  user["name"],
            "email": user["email"],
            "role":  user["role"],
            "type":  "access",
            "iat":   now,
            "exp":   now + timedelta(minutes=ACCESS_MINS),
        },
        ACCESS_SECRET,
        algorithm=ALGORITHM,
    )


def _make_refresh_token(user_id: str) -> tuple[str, str, datetime]:
    jti = str(uuid.uuid4())
    exp = datetime.now(timezone.utc) + timedelta(days=REFRESH_DAYS)
    token = jwt.encode(
        {"sub": user_id, "jti": jti, "type": "refresh", "exp": exp},
        REFRESH_SECRET,
        algorithm=ALGORITHM,
    )
    return token, jti, exp


# ── Exported auth dependencies ────────────────────────────────────────────────
async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """
    FastAPI dependency — validates the Bearer access token.
    Returns the decoded JWT payload (includes name, email, role, employeeId).
    Import and use in any router:
        user: dict = Depends(get_current_user)
    """
    if not credentials:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    try:
        payload = jwt.decode(credentials.credentials, ACCESS_SECRET, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired access token")
    if payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Wrong token type — use access token")
    return payload


def require_role(*roles: str):
    """
    FastAPI dependency factory — restricts endpoint to specific roles.
    Usage:  user: dict = Depends(require_role("Manager", "HR"))
    """
    async def _check(user: dict = Depends(get_current_user)) -> dict:
        if user.get("role") not in roles:
            raise HTTPException(
                status_code=403,
                detail=f"Access denied. Required: {' / '.join(roles)}. Your role: {user.get('role')}",
            )
        return user
    return _check


# ── Pydantic models ───────────────────────────────────────────────────────────
class LoginBody(BaseModel):
    email:    EmailStr
    password: str


class RegisterBody(BaseModel):
    name:       str
    email:      EmailStr
    password:   str
    role:       str
    employeeId: Optional[str] = None   # auto-derived from email if omitted


class RefreshBody(BaseModel):
    refreshToken: str


class ChangePasswordBody(BaseModel):
    currentPassword: str
    newPassword:     str


# ── POST /api/auth/login ──────────────────────────────────────────────────────
@router.post("/login", summary="Login with email + password")
async def login(body: LoginBody, request: Request):
    db   = _db(request)
    user = await db[USER_COL].find_one({"email": body.email.lower()})

    if not user or not user.get(PASSWORD_FIELD):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not pwd_ctx.verify(body.password, user[PASSWORD_FIELD]):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not user.get("isActive", True):
        raise HTTPException(status_code=403, detail="Account is deactivated. Contact HR.")

    user_id = str(user["_id"])
    access_token                   = _make_access_token(user)
    refresh_token, jti, expires_at = _make_refresh_token(user_id)

    await db[REFRESH_COL].insert_one({
        "jti":       jti,
        "userId":    ObjectId(user_id),
        "expiresAt": expires_at,
        "revoked":   False,
        "createdAt": datetime.now(timezone.utc),
    })

    return {
        "accessToken":  access_token,
        "refreshToken": refresh_token,
        "expiresIn":    ACCESS_MINS * 60,   # seconds — useful for frontend countdown
        "user": {
            "_id":       user_id,
            "name":      user["name"],
            "email":     user["email"],
            "role":      user["role"],
            SSO_ID_FIELD: user.get(SSO_ID_FIELD, ""),
        },
    }


# ── POST /api/auth/refresh ────────────────────────────────────────────────────
@router.post("/refresh", summary="Exchange refresh token for a new access token")
async def refresh_token(body: RefreshBody, request: Request):
    db = _db(request)

    try:
        payload = jwt.decode(body.refreshToken, REFRESH_SECRET, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Wrong token type")

    jti     = payload["jti"]
    user_id = payload["sub"]

    db_token = await db[REFRESH_COL].find_one({"jti": jti, "revoked": False})
    if not db_token:
        raise HTTPException(status_code=401, detail="Refresh token revoked or not found")

    user = await db[USER_COL].find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not user.get("isActive", True):
        raise HTTPException(status_code=403, detail="Account deactivated")

    # Token rotation — revoke old, issue new pair
    await db[REFRESH_COL].update_one({"jti": jti}, {"$set": {"revoked": True}})

    new_access                          = _make_access_token(user)
    new_refresh, new_jti, new_expires   = _make_refresh_token(user_id)

    await db[REFRESH_COL].insert_one({
        "jti":       new_jti,
        "userId":    ObjectId(user_id),
        "expiresAt": new_expires,
        "revoked":   False,
        "createdAt": datetime.now(timezone.utc),
    })

    return {
        "accessToken":  new_access,
        "refreshToken": new_refresh,
        "expiresIn":    ACCESS_MINS * 60,
    }


# ── POST /api/auth/logout ─────────────────────────────────────────────────────
@router.post("/logout", summary="Revoke refresh token (logout)")
async def logout(body: RefreshBody, request: Request):
    db = _db(request)
    try:
        payload = jwt.decode(body.refreshToken, REFRESH_SECRET, algorithms=[ALGORITHM])
        jti = payload.get("jti")
        if jti:
            await db[REFRESH_COL].update_one({"jti": jti}, {"$set": {"revoked": True}})
    except JWTError:
        pass   # already expired — nothing to revoke, still counts as logged out
    return {"message": "Logged out successfully"}


# ── GET /api/auth/me ──────────────────────────────────────────────────────────
@router.get("/me", summary="Get current user profile")
async def get_me(request: Request, user: dict = Depends(get_current_user)):
    db  = _db(request)
    doc = await db[USER_COL].find_one({SSO_ID_FIELD: user.get(SSO_ID_FIELD)})
    if not doc:
        raise HTTPException(status_code=404, detail="User profile not found")
    return {"user": _safe_user(doc)}


# ── POST /api/auth/register  (HR-only) ───────────────────────────────────────
@router.post("/register", status_code=201, summary="Create a new user account (HR only)")
async def register(
    body:   RegisterBody,
    request: Request,
    _caller: dict = Depends(require_role("HR")),
):
    if body.role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"Invalid role. Choose from: {', '.join(sorted(VALID_ROLES))}")

    db     = _db(request)
    exists = await db[USER_COL].find_one({"email": body.email.lower()})
    if exists:
        raise HTTPException(status_code=409, detail="Email already registered")

    doc = {
        "name":         body.name.strip(),
        "email":        body.email.lower(),
        "role":         body.role,
        SSO_ID_FIELD:   body.employeeId or body.email.split("@")[0],
        PASSWORD_FIELD: pwd_ctx.hash(body.password),
        "isActive":     True,
        "createdAt":    datetime.now(timezone.utc),
        "createdBy":    _caller.get(SSO_ID_FIELD),
    }
    result = await db[USER_COL].insert_one(doc)
    doc["_id"] = str(result.inserted_id)
    doc.pop(PASSWORD_FIELD, None)
    return {"user": doc}


# ── POST /api/auth/change-password ───────────────────────────────────────────
@router.post("/change-password", summary="Change own password")
async def change_password(
    body:    ChangePasswordBody,
    request: Request,
    user:    dict = Depends(get_current_user),
):
    db  = _db(request)
    doc = await db[USER_COL].find_one({SSO_ID_FIELD: user.get(SSO_ID_FIELD)})
    if not doc:
        raise HTTPException(status_code=404, detail="User not found")

    if not pwd_ctx.verify(body.currentPassword, doc.get(PASSWORD_FIELD, "")):
        raise HTTPException(status_code=401, detail="Current password is incorrect")

    await db[USER_COL].update_one(
        {"_id": doc["_id"]},
        {"$set": {PASSWORD_FIELD: pwd_ctx.hash(body.newPassword), "updatedAt": datetime.now(timezone.utc)}},
    )
    return {"message": "Password changed successfully"}
