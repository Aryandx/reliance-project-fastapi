"""
techLeadIntern_routes.py
────────────────────────────────────────────────────────────────────────────────
FastAPI router — Tech Lead & Intern endpoints.
Equivalent of techLeadIntern.routes.js, rewritten for FastAPI + Motor.

Mounted at /api/intern-tracker in main.py.

All routes require a valid JWT in the Authorization header:
    Authorization: Bearer <token>

Endpoints
─────────
  Intern (role = "Intern")
    GET  /intern/me
    GET  /intern/standup/today
    POST /intern/standup
    GET  /intern/standups
    GET  /intern/progress
    GET  /intern/compliance
    GET  /intern/feedback

  Tech Lead (role = "Tech Lead")
    GET  /tech-lead/interns
    GET  /tech-lead/standup-feed
    GET  /tech-lead/reviews
    POST /tech-lead/reviews/{review_id}/forward
    POST /tech-lead/assign-buddy
    GET  /tech-lead/buddies
    GET  /tech-lead/dashboard-summary
────────────────────────────────────────────────────────────────────────────────
"""

import os
from datetime import datetime, timezone, timedelta
from typing import Optional

from bson import ObjectId
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from pydantic import BaseModel

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────
JWT_SECRET    = os.getenv("JWT_SECRET",    "change_this_secret")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
SSO_ID_FIELD  = os.getenv("SSO_ID_FIELD",  "employeeId")

INTERN_COL     = os.getenv("INTERN_COLLECTION",     "interns")
USER_COL       = os.getenv("USER_COLLECTION",       "users")
ASSIGNMENT_COL = os.getenv("ASSIGNMENT_COLLECTION", "assignments")
STANDUP_COL    = os.getenv("STANDUP_COLLECTION",    "standups")
MILESTONE_COL  = os.getenv("MILESTONE_COLLECTION",  "milestones")
REVIEW_COL     = os.getenv("REVIEW_COLLECTION",     "reviews")

router   = APIRouter()
security = HTTPBearer()


# ── Helpers ───────────────────────────────────────────────────────────────────
def get_db(request: Request):
    return request.app.state.db


def serialize(doc: dict | None) -> dict | None:
    """Convert ObjectId fields to strings so FastAPI can JSON-encode them."""
    if doc is None:
        return None
    result = {}
    for k, v in doc.items():
        if isinstance(v, ObjectId):
            result[k] = str(v)
        elif isinstance(v, list):
            result[k] = [serialize(i) if isinstance(i, dict) else (str(i) if isinstance(i, ObjectId) else i) for i in v]
        elif isinstance(v, dict):
            result[k] = serialize(v)
        else:
            result[k] = v
    return result


def oid(s: str) -> ObjectId:
    """String → ObjectId, raises 400 on bad format."""
    try:
        return ObjectId(s)
    except Exception:
        raise HTTPException(status_code=400, detail=f"Invalid id: {s}")


def today_start() -> datetime:
    t = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return t


def count_working_days(start: datetime, end: datetime) -> int:
    count = 0
    cursor = start.replace(hour=0, minute=0, second=0, microsecond=0)
    end    = end.replace(hour=0, minute=0, second=0, microsecond=0)
    while cursor <= end:
        if cursor.weekday() < 5:   # Mon–Fri
            count += 1
        cursor += timedelta(days=1)
    return count


# ── Auth dependencies ─────────────────────────────────────────────────────────
async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


def require_role(*roles: str):
    """Usage: Depends(require_role("Intern"))  or  Depends(require_role("Tech Lead", "HR"))"""
    async def checker(user: dict = Depends(get_current_user)) -> dict:
        if user.get("role") not in roles:
            raise HTTPException(
                status_code=403,
                detail=f"Requires role: {' or '.join(roles)}. You have: {user.get('role')}",
            )
        return user
    return checker


# ════════════════════════════════════════════════════════════════════════════════
#  INTERN ROUTES
# ════════════════════════════════════════════════════════════════════════════════

@router.get("/intern/me", summary="Intern: own profile + assignment")
async def get_intern_me(
    request: Request,
    user: dict = Depends(require_role("Intern")),
):
    db = get_db(request)
    sso_id = user.get(SSO_ID_FIELD)

    intern = serialize(await db[INTERN_COL].find_one({"employeeId": sso_id}))
    if not intern:
        raise HTTPException(404, "Intern profile not found")

    pipeline = [
        {"$match": {"internId": oid(intern["_id"])}},
        {"$lookup": {"from": USER_COL, "localField": "managerId",  "foreignField": "_id", "as": "_mgr",
                     "pipeline": [{"$project": {"name": 1, "email": 1}}]}},
        {"$lookup": {"from": USER_COL, "localField": "techLeadId", "foreignField": "_id", "as": "_tl",
                     "pipeline": [{"$project": {"name": 1, "email": 1}}]}},
        {"$lookup": {"from": USER_COL, "localField": "buddyId",    "foreignField": "_id", "as": "_buddy",
                     "pipeline": [{"$project": {"name": 1, "email": 1}}]}},
        {"$addFields": {
            "managerId":  {"$arrayElemAt": ["$_mgr",   0]},
            "techLeadId": {"$arrayElemAt": ["$_tl",    0]},
            "buddyId":    {"$arrayElemAt": ["$_buddy", 0]},
        }},
        {"$project": {"_mgr": 0, "_tl": 0, "_buddy": 0}},
    ]
    rows = await db[ASSIGNMENT_COL].aggregate(pipeline).to_list(1)
    assignment = serialize(rows[0]) if rows else None

    return {"intern": intern, "assignment": assignment}


@router.get("/intern/standup/today", summary="Intern: check today's standup")
async def get_standup_today(
    request: Request,
    user: dict = Depends(require_role("Intern")),
):
    db = get_db(request)
    intern = serialize(await db[INTERN_COL].find_one({"employeeId": user.get(SSO_ID_FIELD)}))
    if not intern:
        raise HTTPException(404, "Intern profile not found")

    today = today_start()
    standup = serialize(await db[STANDUP_COL].find_one({
        "internId": oid(intern["_id"]),
        "date": today,
    }))
    return {"submitted": standup is not None, "standup": standup}


class StandupBody(BaseModel):
    yesterday: str
    today: str
    blockers: Optional[str] = ""


@router.post("/intern/standup", status_code=201, summary="Intern: submit standup")
async def submit_standup(
    body: StandupBody,
    request: Request,
    user: dict = Depends(require_role("Intern")),
):
    if not body.yesterday.strip():
        raise HTTPException(400, "'yesterday' is required")
    if not body.today.strip():
        raise HTTPException(400, "'today' is required")

    db = get_db(request)
    intern = serialize(await db[INTERN_COL].find_one({"employeeId": user.get(SSO_ID_FIELD)}))
    if not intern:
        raise HTTPException(404, "Intern profile not found")

    assignment = await db[ASSIGNMENT_COL].find_one({"internId": oid(intern["_id"])})
    if not assignment or not assignment.get("buddyId"):
        raise HTTPException(400, "No buddy assigned yet — ask your Tech Lead to assign one")

    today = today_start()
    doc = {
        "internId":    oid(intern["_id"]),
        "buddyId":     assignment["buddyId"],
        "date":        today,
        "yesterday":   body.yesterday.strip(),
        "today":       body.today.strip(),
        "blockers":    body.blockers.strip() if body.blockers else "",
        "submittedAt": datetime.now(timezone.utc),
        "slaStatus":   "PENDING",
    }
    result = await db[STANDUP_COL].find_one_and_update(
        {"internId": oid(intern["_id"]), "date": today},
        {"$set": doc},
        upsert=True,
        return_document=True,
    )
    return {"standup": serialize(result)}


@router.get("/intern/standups", summary="Intern: standup history")
async def get_standup_history(
    request: Request,
    page:  int = Query(1,  ge=1),
    limit: int = Query(20, ge=1, le=50),
    user: dict = Depends(require_role("Intern")),
):
    db = get_db(request)
    intern = serialize(await db[INTERN_COL].find_one({"employeeId": user.get(SSO_ID_FIELD)}))
    if not intern:
        raise HTTPException(404, "Intern profile not found")

    filt  = {"internId": oid(intern["_id"])}
    total = await db[STANDUP_COL].count_documents(filt)
    rows  = await db[STANDUP_COL].find(filt).sort("date", -1).skip((page - 1) * limit).limit(limit).to_list(limit)
    return {
        "standups": [serialize(r) for r in rows],
        "total": total, "page": page, "limit": limit,
        "pages": -(-total // limit),
    }


@router.get("/intern/progress", summary="Intern: milestones + summary")
async def get_progress(
    request: Request,
    user: dict = Depends(require_role("Intern")),
):
    db = get_db(request)
    intern = serialize(await db[INTERN_COL].find_one({"employeeId": user.get(SSO_ID_FIELD)}))
    if not intern:
        raise HTTPException(404, "Intern profile not found")

    milestones = [
        serialize(m) for m in
        await db[MILESTONE_COL].find({"internId": oid(intern["_id"])}).sort("dueDate", 1).to_list(None)
    ]
    return {
        "milestones": milestones,
        "summary": {
            "total":      len(milestones),
            "completed":  sum(1 for m in milestones if m.get("status") == "COMPLETED"),
            "inProgress": sum(1 for m in milestones if m.get("status") == "IN_PROGRESS"),
            "pending":    sum(1 for m in milestones if m.get("status") == "PENDING"),
        },
    }


@router.get("/intern/compliance", summary="Intern: standup compliance %")
async def get_compliance(
    request: Request,
    user: dict = Depends(require_role("Intern")),
):
    db = get_db(request)
    intern = serialize(await db[INTERN_COL].find_one({"employeeId": user.get(SSO_ID_FIELD)}))
    if not intern:
        raise HTTPException(404, "Intern profile not found")

    raw_start = intern.get("startDate") or intern.get("createdAt")
    start = raw_start if isinstance(raw_start, datetime) else datetime.fromisoformat(str(raw_start))
    today = datetime.now(timezone.utc)

    working_days = count_working_days(start, today)
    submitted    = await db[STANDUP_COL].count_documents({
        "internId": oid(intern["_id"]),
        "date": {"$gte": start.replace(hour=0, minute=0, second=0, microsecond=0),
                 "$lte": today.replace(hour=23, minute=59, second=59)},
    })
    compliance = round((submitted / working_days) * 100) if working_days > 0 else 0
    return {"submitted": submitted, "workingDays": working_days, "compliance": compliance}


@router.get("/intern/feedback", summary="Intern: published reviews")
async def get_feedback(
    request: Request,
    user: dict = Depends(require_role("Intern")),
):
    db = get_db(request)
    intern = serialize(await db[INTERN_COL].find_one({"employeeId": user.get(SSO_ID_FIELD)}))
    if not intern:
        raise HTTPException(404, "Intern profile not found")

    pipeline = [
        {"$match": {"internId": oid(intern["_id"]), "state": "PUBLISHED"}},
        {"$lookup": {"from": USER_COL, "localField": "authorBuddyId", "foreignField": "_id", "as": "_author",
                     "pipeline": [{"$project": {"name": 1, "email": 1}}]}},
        {"$addFields": {"authorBuddyId": {"$arrayElemAt": ["$_author", 0]}}},
        {"$project": {"_author": 0}},
        {"$sort": {"publishedAt": -1}},
    ]
    reviews = [serialize(r) for r in await db[REVIEW_COL].aggregate(pipeline).to_list(None)]
    return {"reviews": reviews}


# ════════════════════════════════════════════════════════════════════════════════
#  TECH LEAD ROUTES
# ════════════════════════════════════════════════════════════════════════════════

@router.get("/tech-lead/interns", summary="Tech Lead: list assigned interns")
async def get_tl_interns(
    request: Request,
    user: dict = Depends(require_role("Tech Lead")),
):
    db = get_db(request)
    tl_user = serialize(await db[USER_COL].find_one({"employeeId": user.get(SSO_ID_FIELD)}))
    if not tl_user:
        raise HTTPException(404, "User not found")

    pipeline = [
        {"$match": {"techLeadId": oid(tl_user["_id"])}},
        {"$lookup": {
            "from": INTERN_COL,
            "localField": "internId",
            "foreignField": "_id",
            "as": "_intern",
            "pipeline": [{"$project": {"name": 1, "email": 1, "employeeCode": 1,
                                       "department": 1, "startDate": 1, "endDate": 1, "status": 1}}],
        }},
        {"$lookup": {
            "from": USER_COL,
            "localField": "buddyId",
            "foreignField": "_id",
            "as": "_buddy",
            "pipeline": [{"$project": {"name": 1, "email": 1}}],
        }},
        {"$addFields": {
            "internData": {"$arrayElemAt": ["$_intern", 0]},
            "buddyData":  {"$arrayElemAt": ["$_buddy",  0]},
        }},
    ]

    rows = await db[ASSIGNMENT_COL].aggregate(pipeline).to_list(None)
    interns = []
    for row in rows:
        if not row.get("internData"):
            continue
        intern = serialize(row["internData"])
        intern["buddyAssigned"]   = row.get("buddyId") is not None
        intern["buddy"]           = serialize(row.get("buddyData"))
        intern["assignmentId"]    = str(row["_id"])
        intern["assignmentState"] = row.get("state")
        interns.append(intern)

    return {"interns": interns}


@router.get("/tech-lead/standup-feed", summary="Tech Lead: standup feed for all interns")
async def get_standup_feed(
    request: Request,
    date:  Optional[str] = Query(None, description="YYYY-MM-DD filter"),
    page:  int = Query(1,  ge=1),
    limit: int = Query(30, ge=1, le=50),
    user: dict = Depends(require_role("Tech Lead")),
):
    db = get_db(request)
    tl_user = serialize(await db[USER_COL].find_one({"employeeId": user.get(SSO_ID_FIELD)}))
    if not tl_user:
        raise HTTPException(404, "User not found")

    assignments = await db[ASSIGNMENT_COL].find(
        {"techLeadId": oid(tl_user["_id"])}, {"internId": 1}
    ).to_list(None)
    intern_ids = [a["internId"] for a in assignments]

    filt: dict = {"internId": {"$in": intern_ids}}
    if date:
        day_start = datetime.fromisoformat(date).replace(
            hour=0, minute=0, second=0, microsecond=0, tzinfo=timezone.utc
        )
        day_end   = day_start.replace(hour=23, minute=59, second=59)
        filt["date"] = {"$gte": day_start, "$lte": day_end}

    pipeline = [
        {"$match": filt},
        {"$sort": {"date": -1, "submittedAt": -1}},
        {"$skip": (page - 1) * limit},
        {"$limit": limit},
        {"$lookup": {"from": INTERN_COL, "localField": "internId", "foreignField": "_id", "as": "_intern",
                     "pipeline": [{"$project": {"name": 1, "employeeCode": 1, "department": 1}}]}},
        {"$lookup": {"from": USER_COL,   "localField": "buddyId",  "foreignField": "_id", "as": "_buddy",
                     "pipeline": [{"$project": {"name": 1}}]}},
        {"$addFields": {
            "internId": {"$arrayElemAt": ["$_intern", 0]},
            "buddyId":  {"$arrayElemAt": ["$_buddy",  0]},
        }},
        {"$project": {"_intern": 0, "_buddy": 0}},
    ]

    total    = await db[STANDUP_COL].count_documents(filt)
    standups = [serialize(s) for s in await db[STANDUP_COL].aggregate(pipeline).to_list(limit)]
    return {"standups": standups, "total": total, "page": page, "limit": limit}


@router.get("/tech-lead/reviews", summary="Tech Lead: reviews pending TL approval")
async def get_tl_reviews(
    request: Request,
    user: dict = Depends(require_role("Tech Lead")),
):
    db = get_db(request)
    tl_user = serialize(await db[USER_COL].find_one({"employeeId": user.get(SSO_ID_FIELD)}))
    if not tl_user:
        raise HTTPException(404, "User not found")

    assignments = await db[ASSIGNMENT_COL].find(
        {"techLeadId": oid(tl_user["_id"])}, {"internId": 1}
    ).to_list(None)
    intern_ids = [a["internId"] for a in assignments]

    pipeline = [
        {"$match": {"internId": {"$in": intern_ids}, "state": "TL_REVIEW"}},
        {"$lookup": {"from": INTERN_COL, "localField": "internId",      "foreignField": "_id", "as": "_intern",
                     "pipeline": [{"$project": {"name": 1, "email": 1, "employeeCode": 1}}]}},
        {"$lookup": {"from": USER_COL,   "localField": "authorBuddyId", "foreignField": "_id", "as": "_author",
                     "pipeline": [{"$project": {"name": 1}}]}},
        {"$addFields": {
            "internId":      {"$arrayElemAt": ["$_intern",  0]},
            "authorBuddyId": {"$arrayElemAt": ["$_author", 0]},
        }},
        {"$project": {"_intern": 0, "_author": 0}},
        {"$sort": {"updatedAt": -1}},
    ]
    reviews = [serialize(r) for r in await db[REVIEW_COL].aggregate(pipeline).to_list(None)]
    return {"reviews": reviews}


class ForwardReviewBody(BaseModel):
    comment: Optional[str] = ""


@router.post("/tech-lead/reviews/{review_id}/forward", summary="Tech Lead: forward review to Manager")
async def forward_review(
    review_id: str,
    body: ForwardReviewBody,
    request: Request,
    user: dict = Depends(require_role("Tech Lead")),
):
    db = get_db(request)
    tl_user = serialize(await db[USER_COL].find_one({"employeeId": user.get(SSO_ID_FIELD)}))
    if not tl_user:
        raise HTTPException(404, "User not found")

    review = await db[REVIEW_COL].find_one({"_id": oid(review_id)})
    if not review:
        raise HTTPException(404, "Review not found")
    if review.get("state") != "TL_REVIEW":
        raise HTTPException(409, f"Review is in \"{review['state']}\" — cannot forward from here")

    owns = await db[ASSIGNMENT_COL].find_one({
        "internId": review["internId"],
        "techLeadId": oid(tl_user["_id"]),
    })
    if not owns:
        raise HTTPException(403, "This review does not belong to your interns")

    now    = datetime.now(timezone.utc)
    stages = review.get("stages", [])
    updated = False
    for stage in stages:
        if stage.get("stage") == "TL_REVIEW" and not stage.get("exitedAt"):
            stage["comment"]  = body.comment.strip() if body.comment else ""
            stage["exitedAt"] = now
            updated = True
            break
    if not updated:
        stages.append({
            "stage": "TL_REVIEW", "actorId": oid(tl_user["_id"]),
            "comment": body.comment.strip() if body.comment else "",
            "enteredAt": now, "exitedAt": now,
        })
    stages.append({"stage": "MGR_REVIEW", "actorId": None, "enteredAt": now, "exitedAt": None})

    result = await db[REVIEW_COL].find_one_and_update(
        {"_id": oid(review_id)},
        {"$set": {"state": "MGR_REVIEW", "stages": stages, "updatedAt": now}},
        return_document=True,
    )
    return {"review": serialize(result)}


class AssignBuddyBody(BaseModel):
    internId:    str
    buddyUserId: str


@router.post("/tech-lead/assign-buddy", summary="Tech Lead: assign buddy to intern")
async def assign_buddy(
    body: AssignBuddyBody,
    request: Request,
    user: dict = Depends(require_role("Tech Lead")),
):
    db = get_db(request)
    tl_user = serialize(await db[USER_COL].find_one({"employeeId": user.get(SSO_ID_FIELD)}))
    if not tl_user:
        raise HTTPException(404, "User not found")

    assignment = await db[ASSIGNMENT_COL].find_one({
        "internId":   oid(body.internId),
        "techLeadId": oid(tl_user["_id"]),
    })
    if not assignment:
        raise HTTPException(403, "This intern is not in your team")

    buddy = await db[USER_COL].find_one({"_id": oid(body.buddyUserId)})
    if not buddy:
        raise HTTPException(404, "Buddy user not found")
    if buddy.get("role") != "Buddy":
        raise HTTPException(400, f"\"{buddy['name']}\" has role \"{buddy['role']}\", not \"Buddy\"")

    now     = datetime.now(timezone.utc)
    history = assignment.get("history", [])
    history.append({
        "field":    "buddyId",
        "fromId":   assignment.get("buddyId"),
        "toId":     oid(body.buddyUserId),
        "byUserId": oid(tl_user["_id"]),
        "at":       now,
    })

    new_state = "BUDDY_ASSIGNED" if assignment.get("state") == "TECHLEAD_ASSIGNED" else assignment.get("state")
    result = await db[ASSIGNMENT_COL].find_one_and_update(
        {"_id": assignment["_id"]},
        {"$set": {"buddyId": oid(body.buddyUserId), "state": new_state,
                  "history": history, "updatedAt": now}},
        return_document=True,
    )

    # Populate buddy info
    pipeline = [
        {"$match": {"_id": result["_id"]}},
        {"$lookup": {"from": USER_COL, "localField": "buddyId", "foreignField": "_id", "as": "_buddy",
                     "pipeline": [{"$project": {"name": 1, "email": 1}}]}},
        {"$addFields": {"buddyId": {"$arrayElemAt": ["$_buddy", 0]}}},
        {"$project": {"_buddy": 0}},
    ]
    rows = await db[ASSIGNMENT_COL].aggregate(pipeline).to_list(1)
    return {"assignment": serialize(rows[0]) if rows else serialize(result)}


@router.get("/tech-lead/buddies", summary="Tech Lead: list all active Buddy users")
async def get_buddies(
    request: Request,
    user: dict = Depends(require_role("Tech Lead")),
):
    db = get_db(request)
    buddies = [
        serialize(b) for b in
        await db[USER_COL].find(
            {"role": "Buddy", "isActive": {"$ne": False}},
            {"name": 1, "email": 1, "employeeId": 1},
        ).sort("name", 1).to_list(None)
    ]
    return {"buddies": buddies}


@router.get("/tech-lead/dashboard-summary", summary="Tech Lead: dashboard stats")
async def get_dashboard_summary(
    request: Request,
    user: dict = Depends(require_role("Tech Lead")),
):
    db = get_db(request)
    tl_user = serialize(await db[USER_COL].find_one({"employeeId": user.get(SSO_ID_FIELD)}))
    if not tl_user:
        raise HTTPException(404, "User not found")

    assignments = await db[ASSIGNMENT_COL].find(
        {"techLeadId": oid(tl_user["_id"])}, {"internId": 1, "buddyId": 1}
    ).to_list(None)
    intern_ids = [a["internId"] for a in assignments]

    today = today_start()
    today_standups, pending_reviews, unassigned_buddy = await asyncio.gather(
        db[STANDUP_COL].count_documents({"internId": {"$in": intern_ids}, "date": today}),
        db[REVIEW_COL].count_documents({"internId": {"$in": intern_ids}, "state": "TL_REVIEW"}),
        db[ASSIGNMENT_COL].count_documents({"internId": {"$in": intern_ids}, "buddyId": None}),
    )

    return {
        "totalInterns":            len(intern_ids),
        "todayStandups":           today_standups,
        "pendingReviews":          pending_reviews,
        "unassignedBuddy":         unassigned_buddy,
        "buddyAssignmentComplete": len(intern_ids) - unassigned_buddy,
    }


# asyncio import needed for gather
import asyncio
