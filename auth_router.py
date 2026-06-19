"""
auth_router.py
────────────────────────────────────────────────────────────────────────────────
DROP INTO:  app/routers/auth_router.py

MOUNT in your main FastAPI app (two lines):
    from app.routers.auth_router import router as auth_router, get_current_user, require_role
    app.include_router(auth_router, prefix="/api/auth", tags=["Auth"])

PROTECT any endpoint in your other routers:
    from app.routers.auth_router import get_current_user, require_role

    @router.get("/something")
    async def my_endpoint(user: dict = Depends(get_current_user)):
        ...

    @router.get("/manager-only")
    async def manager_only(user: dict = Depends(require_role("Manager", "HR"))):
        ...

CALL create_db_indexes on startup (add to your lifespan):
    from app.routers.auth_router import create_db_indexes
    async with lifespan(app):
        await create_db_indexes(app.state.db)

ENV VARS — add these to your .env:
    JWT_SECRET                   access-token signing secret  (min 32 chars)
    REFRESH_TOKEN_SECRET         refresh-token signing secret (different from JWT_SECRET)
    ACCESS_TOKEN_EXPIRE_MINUTES  default 15
    REFRESH_TOKEN_EXPIRE_DAYS    default 7
    USER_COLLECTION              MongoDB collection for users       (default: "users")
    REFRESH_TOKEN_COLLECTION     MongoDB collection for RT storage  (default: "refresh_tokens")
    SSO_ID_FIELD                 unique employee ID field on the user doc (default: "employeeId")
    PASSWORD_HASH_FIELD          field where bcrypt hash is stored  (default: "passwordHash")

ROLE STRINGS (must match your DB):  "HR" | "Manager" | "Tech Lead" | "Buddy" | "Intern"
────────────────────────────────────────────────────────────────────────────────
"""

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from bson import ObjectId
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr, field_validator

load_dotenv()

# ── Config ─────────────────────────────────────────────────────────────────────
ACCESS_SECRET  = os.getenv("JWT_SECRET",                    "change_this_access_secret_min_32_chars")
REFRESH_SECRET = os.getenv("REFRESH_TOKEN_SECRET",          "change_this_refresh_secret_min_32_chars")
ACCESS_MINS    = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "15"))
REFRESH_DAYS   = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS",   "7"))
ALGORITHM      = "HS256"

USER_COL       = os.getenv("USER_COLLECTION",            "users")
REFRESH_COL    = os.getenv("REFRESH_TOKEN_COLLECTION",   "refresh_tokens")
SSO_ID_FIELD   = os.getenv("SSO_ID_FIELD",               "employeeId")
PASSWORD_FIELD = os.getenv("PASSWORD_HASH_FIELD",        "passwordHash")

VALID_ROLES = {"HR", "Manager", "Tech Lead", "Buddy", "Intern"}

pwd_ctx  = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer(auto_error=False)
router   = APIRouter()


# ── MongoDB indexes (call once at startup) ────────────────────────────────────
async def create_db_indexes(db) -> None:
    """
    Call this once during app startup so queries are fast and refresh tokens
    expire automatically.

    In your lifespan:
        await create_db_indexes(app.state.db)
    """
    # Fast login lookups
    await db[USER_COL].create_index("email",        unique=True)
    await db[USER_COL].create_index(SSO_ID_FIELD,   unique=True)

    # Auto-delete expired refresh tokens (MongoDB TTL index)
    await db[REFRESH_COL].create_index("expiresAt", expireAfterSeconds=0)
    await db[REFRESH_COL].create_index("jti",       unique=True)


# ── Helpers ───────────────────────────────────────────────────────────────────
def _db(request: Request):
    return request.app.state.db


def _safe_user(doc: dict) -> dict:
    """Remove password hash and convert ObjectId → str before sending to client."""
    return {
        k: str(v) if isinstance(v, ObjectId) else v
        for k, v in doc.items()
        if k != PASSWORD_FIELD
    }


def _utc_now() -> datetime:
    """Naive UTC datetime — consistent with what MongoDB stores/returns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _make_access_token(user: dict) -> str:
    now = _utc_now()
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
    exp = _utc_now() + timedelta(days=REFRESH_DAYS)
    token = jwt.encode(
        {"sub": user_id, "jti": jti, "type": "refresh", "exp": exp},
        REFRESH_SECRET,
        algorithm=ALGORITHM,
    )
    return token, jti, exp


# ── Exported auth dependencies ─────────────────────────────────────────────────
async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """
    Validates the Bearer access token.
    Returns decoded JWT payload: { employeeId, name, email, role, type }.
    Raises 401 if missing, expired, or wrong token type (e.g. refresh token used by mistake).
    """
    if not credentials:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    try:
        payload = jwt.decode(credentials.credentials, ACCESS_SECRET, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired access token")
    if payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Wrong token type — send the access token, not the refresh token")
    return payload


def require_role(*roles: str):
    """
    Dependency factory for role-based access control.
    Usage:  Depends(require_role("Manager", "HR"))
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
    employeeId: Optional[str] = None

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Name cannot be blank")
        return v.strip()


class RefreshBody(BaseModel):
    refreshToken: str


class ChangePasswordBody(BaseModel):
    currentPassword: str
    newPassword:     str

    @field_validator("newPassword")
    @classmethod
    def new_password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("New password must be at least 8 characters")
        return v


# ── POST /api/auth/login ──────────────────────────────────────────────────────
@router.post("/login", summary="Login — returns access + refresh tokens")
async def login(body: LoginBody, request: Request):
    db   = _db(request)
    user = await db[USER_COL].find_one({"email": body.email.lower()})

    # Intentionally same error message for wrong email OR wrong password (don't leak which one)
    if not user or not user.get(PASSWORD_FIELD):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not pwd_ctx.verify(body.password, user[PASSWORD_FIELD]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.get("isActive", True):
        raise HTTPException(status_code=403, detail="Account deactivated. Contact HR.")

    user_id                        = str(user["_id"])
    access_token                   = _make_access_token(user)
    refresh_token, jti, expires_at = _make_refresh_token(user_id)

    await db[REFRESH_COL].insert_one({
        "jti":       jti,
        "userId":    ObjectId(user_id),
        "expiresAt": expires_at,
        "revoked":   False,
        "createdAt": _utc_now(),
    })

    return {
        "accessToken":  access_token,
        "refreshToken": refresh_token,
        "expiresIn":    ACCESS_MINS * 60,
        "user": {
            "_id":        user_id,
            "name":       user["name"],
            "email":      user["email"],
            "role":       user["role"],
            SSO_ID_FIELD: user.get(SSO_ID_FIELD, ""),
        },
    }


# ── POST /api/auth/refresh ────────────────────────────────────────────────────
@router.post("/refresh", summary="Exchange refresh token for new access token (token rotation)")
async def refresh_token_endpoint(body: RefreshBody, request: Request):
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
        raise HTTPException(status_code=401, detail="Refresh token revoked or not found — please log in again")

    user = await db[USER_COL].find_one({"_id": ObjectId(user_id)})
    if not user or not user.get("isActive", True):
        raise HTTPException(status_code=403, detail="Account not found or deactivated")

    # Rotate: revoke old token, issue new pair
    await db[REFRESH_COL].update_one({"jti": jti}, {"$set": {"revoked": True}})

    new_access                        = _make_access_token(user)
    new_refresh, new_jti, new_expires = _make_refresh_token(user_id)

    await db[REFRESH_COL].insert_one({
        "jti":       new_jti,
        "userId":    ObjectId(user_id),
        "expiresAt": new_expires,
        "revoked":   False,
        "createdAt": _utc_now(),
    })

    return {
        "accessToken":  new_access,
        "refreshToken": new_refresh,
        "expiresIn":    ACCESS_MINS * 60,
    }


# ── POST /api/auth/logout ─────────────────────────────────────────────────────
@router.post("/logout", summary="Revoke refresh token")
async def logout(body: RefreshBody, request: Request):
    db = _db(request)
    try:
        payload = jwt.decode(body.refreshToken, REFRESH_SECRET, algorithms=[ALGORITHM])
        jti = payload.get("jti")
        if jti:
            await db[REFRESH_COL].update_one({"jti": jti}, {"$set": {"revoked": True}})
    except JWTError:
        pass  # already expired — nothing to revoke; logout still succeeds
    return {"message": "Logged out successfully"}


# ── GET /api/auth/me ──────────────────────────────────────────────────────────
@router.get("/me", summary="Get own profile from DB (always fresh)")
async def get_me(request: Request, user: dict = Depends(get_current_user)):
    db  = _db(request)
    doc = await db[USER_COL].find_one({SSO_ID_FIELD: user.get(SSO_ID_FIELD)})
    if not doc:
        raise HTTPException(status_code=404, detail="User profile not found in DB")
    return {"user": _safe_user(doc)}


# ── GET /api/auth/users  (HR only) ───────────────────────────────────────────
@router.get("/users", summary="List all users — HR only")
async def list_users(
    request: Request,
    role:    Optional[str] = None,
    hr_user: dict = Depends(require_role("HR")),  # auth guard — value not needed in body
) -> dict:
    del hr_user  # FastAPI runs the dependency for enforcement; return value unused
    db     = _db(request)
    filt   = {"role": role} if role else {}
    users  = await db[USER_COL].find(filt, {PASSWORD_FIELD: 0}).sort("name", 1).to_list(None)
    return {"users": [_safe_user(u) for u in users], "total": len(users)}


# ── POST /api/auth/register  (HR only) ───────────────────────────────────────
@router.post("/register", status_code=201, summary="Create user account — HR only")
async def register(
    body:       RegisterBody,
    request:    Request,
    current_hr: dict = Depends(require_role("HR")),   # current_hr IS used below
):
    if body.role not in VALID_ROLES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid role '{body.role}'. Valid roles: {', '.join(sorted(VALID_ROLES))}",
        )

    db     = _db(request)
    exists = await db[USER_COL].find_one({"email": body.email.lower()})
    if exists:
        raise HTTPException(status_code=409, detail="Email already registered")

    doc = {
        "name":         body.name,
        "email":        body.email.lower(),
        "role":         body.role,
        SSO_ID_FIELD:   body.employeeId or body.email.split("@")[0],
        PASSWORD_FIELD: pwd_ctx.hash(body.password),
        "isActive":     True,
        "createdAt":    _utc_now(),
        "createdBy":    current_hr.get(SSO_ID_FIELD),  # audit trail
    }
    result  = await db[USER_COL].insert_one(doc)
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
        {"$set": {PASSWORD_FIELD: pwd_ctx.hash(body.newPassword), "updatedAt": _utc_now()}},
    )
    return {"message": "Password changed successfully"}
