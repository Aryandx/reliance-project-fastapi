"""
main.py  –  Intern Tracker API
────────────────────────────────────────────────────────────────
FastAPI + Uvicorn + Motor (async MongoDB)

Quick start:
    cp .env.example .env          # fill in MONGODB_URI, JWT_SECRET, DB_NAME
    pip install -r requirements.txt
    uvicorn main:app --reload --port 8000

Swagger UI → http://localhost:8000/docs
Health     → http://localhost:8000/api/health
────────────────────────────────────────────────────────────────
"""

import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from passlib.context import CryptContext

from techLeadIntern_routes import router as intern_router

load_dotenv()

MONGODB_URI   = os.getenv("MONGODB_URI",   "mongodb://localhost:27017")
DB_NAME       = os.getenv("DB_NAME",       "internship_tracker")
CLIENT_ORIGIN = os.getenv("CLIENT_ORIGIN", "http://localhost:5173")
USER_COL      = os.getenv("USER_COLLECTION", "users")

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ── Seed test accounts ────────────────────────────────────────────────────────
SEED_USERS = [
    {"name": "HR Admin",    "email": "hr@reliance.com",       "role": "HR",       "password": "password123"},
    {"name": "Manager One", "email": "manager@reliance.com",  "role": "Manager",  "password": "password123"},
    {"name": "Tech Lead",   "email": "techlead@reliance.com", "role": "Tech Lead","password": "password123"},
    {"name": "Buddy One",   "email": "buddy@reliance.com",    "role": "Buddy",    "password": "password123"},
    {"name": "Intern One",  "email": "intern@reliance.com",   "role": "Intern",   "password": "password123"},
]

async def seed_users(db):
    for u in SEED_USERS:
        exists = await db[USER_COL].find_one({"email": u["email"]})
        if not exists:
            await db[USER_COL].insert_one({
                **u,
                "employeeId": u["email"].split("@")[0],
                "passwordHash": pwd_ctx.hash(u["password"]),
                "isActive": True,
                "createdAt": datetime.now(timezone.utc),
            })
            print(f"  Seeded  → {u['email']}")
    print("  Seed complete\n")


# ── App lifespan (startup / shutdown) ─────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    client = AsyncIOMotorClient(MONGODB_URI)
    db = client[DB_NAME]
    app.state.db = db
    print(f"\n  MongoDB → {DB_NAME}")
    await seed_users(db)
    yield
    client.close()


# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI(
    title="Intern Tracker API",
    version="1.0.0",
    description="Tech Lead & Intern features — FastAPI + Motor",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[CLIENT_ORIGIN, "http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(intern_router, prefix="/api/intern-tracker", tags=["Intern Tracker"])


# ── Auth routes (login / me) ──────────────────────────────────────────────────
import os
from datetime import timedelta
from fastapi import HTTPException, Request
from jose import jwt
from pydantic import BaseModel

JWT_SECRET          = os.getenv("JWT_SECRET", "change_this_secret")
JWT_ALGORITHM       = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_MINUTES  = int(os.getenv("JWT_EXPIRE_MINUTES", "1440"))


class LoginBody(BaseModel):
    email: str
    password: str


@app.post("/api/auth/login", tags=["Auth"])
async def login(body: LoginBody, request: Request):
    db: AsyncIOMotorClient = request.app.state.db
    user = await db[USER_COL].find_one({"email": body.email.lower()})
    if not user or not pwd_ctx.verify(body.password, user.get("passwordHash", "")):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    payload = {
        "employeeId": user.get("employeeId", str(user["_id"])),
        "name": user["name"],
        "email": user["email"],
        "role": user["role"],
        "exp": datetime.now(timezone.utc) + timedelta(minutes=JWT_EXPIRE_MINUTES),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return {"token": token, "user": {"name": user["name"], "email": user["email"], "role": user["role"]}}


@app.get("/api/health", tags=["Health"])
async def health():
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
