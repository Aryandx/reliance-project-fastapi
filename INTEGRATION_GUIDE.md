# Integration Guide
## How to add Intern + Tech Lead + Auth into your existing FastAPI codebase

---

> **Before you start:** This guide assumes your project already has FastAPI + MongoDB (Motor) running.
> You do NOT need to understand every line of code. Just follow the steps exactly.

---

## What you are adding

Three files go into your project:

| File | What it is |
|------|-----------|
| `auth_router.py` | Login, logout, register, change-password — the lock on every door |
| `techLeadIntern_routes.py` | All Intern and Tech Lead features — 16 endpoints |
| `AuthPages.tsx` | The React login page + auth store + auto-refresh |

---

## STEP 1 — Copy the 3 files into your project

```
your-project/
├── app/
│   └── routers/
│       ├── auth_router.py            ← paste here
│       └── techLeadIntern_routes.py  ← paste here
└── frontend/
    └── src/
        └── auth/
            └── AuthPages.tsx         ← paste here (create the auth/ folder)
```

> **That's it for file copying.** Now we connect them.

---

## STEP 2 — Check your main.py has a database on app.state

Open your `main.py`. Find where you connect to MongoDB.
It must look something like this:

```python
# Your existing code should already have something like this:
@asynccontextmanager
async def lifespan(app: FastAPI):
    client = AsyncIOMotorClient(os.getenv("MONGODB_URI"))
    app.state.db = client[os.getenv("DB_NAME")]   # ← this line is critical
    yield
    client.close()
```

**The critical part is `app.state.db = ...`**
The two new files expect to find the database at `request.app.state.db`.

> If your code does `app.state.db = ...` somewhere — you're good. Move to Step 3.
> If it doesn't, add that line wherever you connect to MongoDB.

---

## STEP 3 — Mount the two routers in main.py

Open your `main.py`. Add these lines:

```python
# Add these 2 imports at the top of main.py
from app.routers.auth_router import router as auth_router, create_db_indexes
from app.routers.techLeadIntern_routes import router as tracker_router

# Add these 2 lines AFTER you create your FastAPI app (after: app = FastAPI(...))
app.include_router(auth_router,  prefix="/api/auth",           tags=["Auth"])
app.include_router(tracker_router, prefix="/api/intern-tracker", tags=["Intern Tracker"])
```

> **How to find the right spot:** Look for other `app.include_router(...)` lines in your
> main.py. Add these two lines right next to them.

---

## STEP 4 — Create DB indexes on startup (one line)

Still in `main.py`, inside your startup code (the `lifespan` function or `@app.on_event("startup")`),
add this one line **after** you set `app.state.db`:

```python
await create_db_indexes(app.state.db)
```

**Full example of what your lifespan should look like after:**

```python
from app.routers.auth_router import router as auth_router, create_db_indexes
from app.routers.techLeadIntern_routes import router as tracker_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    client = AsyncIOMotorClient(os.getenv("MONGODB_URI"))
    app.state.db = client[os.getenv("DB_NAME")]
    await create_db_indexes(app.state.db)   # ← ADD THIS LINE
    yield
    client.close()

app = FastAPI(lifespan=lifespan)
app.include_router(auth_router,    prefix="/api/auth",            tags=["Auth"])
app.include_router(tracker_router, prefix="/api/intern-tracker",  tags=["Intern Tracker"])
```

---

## STEP 5 — Fix the import path inside techLeadIntern_routes.py

Open `techLeadIntern_routes.py`. Find **line 52** (it says `from auth_router import ...`):

```python
# CHANGE THIS:
from auth_router import get_current_user, require_role

# TO THIS (match your project's folder structure):
from app.routers.auth_router import get_current_user, require_role
```

> **Why?** The file needs to know where `auth_router.py` lives inside your project.
> If your routers folder is at a different path (e.g. `routers/` not `app/routers/`),
> adjust accordingly.

---

## STEP 6 — Add the environment variables

Open your `.env` file and add these lines at the bottom:

```env
# Auth secrets — make these long and random, never share them
JWT_SECRET=paste_any_long_random_string_here_min_32_chars
REFRESH_TOKEN_SECRET=paste_a_different_long_random_string_here

# How long tokens last
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=7

# MongoDB collection names — change these to match YOUR database's collection names
USER_COLLECTION=users
INTERN_COLLECTION=interns
ASSIGNMENT_COLLECTION=assignments
STANDUP_COLLECTION=standups
MILESTONE_COLLECTION=milestones
REVIEW_COLLECTION=reviews
REFRESH_TOKEN_COLLECTION=refresh_tokens

# The field in your users collection that holds the employee's unique ID
# Common values: employeeId  or  eid  or  empCode
SSO_ID_FIELD=employeeId

# The field in your users collection that stores the hashed password
PASSWORD_HASH_FIELD=passwordHash
```

> **How to generate a random secret:**
> Open a terminal and run: `python -c "import secrets; print(secrets.token_hex(32))"`
> Copy the output and paste it as your JWT_SECRET.

> **Collection names:** Open MongoDB Compass or Atlas. Look at what your collections are
> actually called. Use those exact names here.

---

## STEP 7 — Install Python dependencies (if missing)

Run this in your backend terminal:

```bash
pip install python-jose[cryptography] passlib[bcrypt] python-dotenv
```

> If you already use these — nothing will change, pip will skip them.

---

## STEP 8 — Test the backend is working

Start your FastAPI server, then open a browser and go to:

```
http://localhost:8000/docs
```

You should see new sections: **Auth** and **Intern Tracker**.

Try the login endpoint:
1. Click `POST /api/auth/login`
2. Click "Try it out"
3. Enter: `{ "email": "test@example.com", "password": "yourpassword" }`
4. Hit Execute

If you get back an `accessToken` — the backend is working.

---

## STEP 9 — Frontend: install Zustand (if not already installed)

In your frontend folder, run:

```bash
npm install zustand
```

> If Zustand is already in your `package.json` — skip this step.

---

## STEP 10 — Frontend: update the API URL in AuthPages.tsx

Open `AuthPages.tsx`. Find **line ~49** at the very top where it says:

```typescript
const API_BASE = "http://localhost:8000";
```

Change it to your actual backend URL:

```typescript
const API_BASE = "https://your-backend.onrender.com";   // for production
// OR keep "http://localhost:8000" for local development
```

---

## STEP 11 — Frontend: add the Login page to your router

In your main router file (usually `App.tsx` or wherever your `<Routes>` are):

```tsx
// Add this import at the top
import { LoginPage, setupAxiosAuth, useAuthStore } from "./auth/AuthPages";

// Add this somewhere near the top of your root component (before the return)
useEffect(() => {
  setupAxiosAuth(yourExistingAxiosInstance);   // ← pass your axios instance here
}, []);

// Add this route inside your <Routes>
<Route path="/login" element={<LoginPage onSuccess={(user) => navigate("/")} />} />
```

> **What is `yourExistingAxiosInstance`?**
> It's wherever you create axios in your project.
> Example: `import api from "@/utils/api";` → pass `api`
> This makes every API call automatically send the auth token.

---

## STEP 12 — Frontend: protect your existing pages

On any page that should only be visible to logged-in users, add this at the top:

```tsx
import { useAuthStore } from "./auth/AuthPages";   // adjust path
import { Navigate } from "react-router-dom";

// Inside your component, at the top:
const { user } = useAuthStore();
if (!user) return <Navigate to="/login" />;
```

Or if you already have a `ProtectedRoute` wrapper, use `useAuthStore().user` as the auth check.

---

## STEP 13 — Create the first user account

The register endpoint is **HR-only** (you need to be logged in as HR to create accounts).

For the very first user, you have two options:

**Option A — Run a one-time Python script:**
```python
# run_once_create_hr.py  — run this ONCE, then delete the file
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from passlib.context import CryptContext
from datetime import datetime

async def main():
    client = AsyncIOMotorClient("YOUR_MONGODB_URI")
    db = client["YOUR_DB_NAME"]
    pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
    await db["users"].insert_one({
        "name":         "HR Admin",
        "email":        "hr@yourcompany.com",
        "role":         "HR",
        "employeeId":   "HR001",
        "passwordHash": pwd.hash("ChangeMe123!"),
        "isActive":     True,
        "createdAt":    datetime.utcnow(),
    })
    print("HR user created")

asyncio.run(main())
```

**Option B — Temporarily open the register endpoint** (set it to `Depends(get_current_user)` instead of `require_role("HR")`), create HR, then lock it back.

---

## What each auth endpoint does (quick reference)

| Endpoint | Who calls it | What it does |
|----------|-------------|-------------|
| `POST /api/auth/login` | Anyone (public) | Give email+password → get tokens back |
| `POST /api/auth/refresh` | Frontend auto | Swap old refresh token for a new access token |
| `POST /api/auth/logout` | Logged-in user | Invalidate the refresh token |
| `GET /api/auth/me` | Logged-in user | Get your own user profile from DB |
| `POST /api/auth/register` | HR only | Create a new user account |
| `GET /api/auth/users` | HR only | List all user accounts |
| `POST /api/auth/change-password` | Logged-in user | Change your own password |

---

## Common questions

**Q: My existing routes — do I need to change them?**
No. The new routers are completely separate. Your existing routes keep working unchanged.
If you WANT to protect your existing routes with the same auth, add `Depends(get_current_user)`
to them and import `get_current_user` from `auth_router`.

**Q: I already have my own auth system. What do I do?**
Skip `auth_router.py` entirely. In `techLeadIntern_routes.py` line 52, replace:
```python
from app.routers.auth_router import get_current_user, require_role
```
with your own existing auth imports that provide the same two functions.

**Q: The role check is failing even though the user has the right role.**
Check that the role string in your database exactly matches what the code expects:
`"Intern"`, `"Tech Lead"`, `"Buddy"`, `"Manager"`, `"HR"` — case sensitive, space in Tech Lead.

**Q: I get "User not found" on intern endpoints.**
The intern endpoints look up `{ "employeeId": <value from JWT> }` in the `interns` collection.
Make sure your `SSO_ID_FIELD` env var matches the actual field name in your user documents.

---

## Summary — the 5 things that must be true for this to work

1. `app.state.db` points to your Motor database
2. Both routers are mounted in `main.py`
3. The import path in `techLeadIntern_routes.py` line 52 matches your folder structure
4. All env vars are in `.env`
5. Frontend `API_BASE` points to the right backend URL
