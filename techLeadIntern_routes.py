"""
techLeadIntern_routes.py
────────────────────────────────────────────────────────────────────────────────
FastAPI router — Tech Lead & Intern feature endpoints.

DROP INTO:  app/routers/techLeadIntern_routes.py

MOUNT in your main FastAPI app:
    from app.routers.techLeadIntern_routes import router as tracker_router
    app.include_router(tracker_router, prefix="/api/intern-tracker", tags=["Intern Tracker"])

DEPENDS ON auth_router.py being in the same package:
    from app.routers.auth_router import get_current_user, require_role

    If your codebase already has its own get_current_user / require_role,
    replace the import on line ~45 with your own.

ENV VARS (same .env as auth_router.py):
    USER_COLLECTION, INTERN_COLLECTION, ASSIGNMENT_COLLECTION,
    STANDUP_COLLECTION, MILESTONE_COLLECTION, REVIEW_COLLECTION, SSO_ID_FIELD

Endpoints
─────────
  Intern  (role = "Intern")
    GET   /intern/me
    GET   /intern/standup/today
    POST  /intern/standup
    GET   /intern/standups
    GET   /intern/progress
    PATCH /intern/milestone/{milestone_id}    ← intern self-updates milestone status
    GET   /intern/streak                      ← current consecutive submission streak
    GET   /intern/compliance
    GET   /intern/feedback

  Tech Lead  (role = "Tech Lead")
    GET   /tech-lead/interns
    GET   /tech-lead/standup-feed
    GET   /tech-lead/reviews
    POST  /tech-lead/reviews/{review_id}/forward
    POST  /tech-lead/assign-buddy
    GET   /tech-lead/buddies
    GET   /tech-lead/dashboard-summary
────────────────────────────────────────────────────────────────────────────────
"""

import asyncio
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from bson import ObjectId
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

# ── Import auth from auth_router (same package) ───────────────────────────────
# If your codebase already exports these, replace this import line:
from auth_router import get_current_user, require_role

load_dotenv()

# ── Collection names ──────────────────────────────────────────────────────────
SSO_ID_FIELD   = os.getenv("SSO_ID_FIELD",              "employeeId")
INTERN_COL     = os.getenv("INTERN_COLLECTION",          "interns")
USER_COL       = os.getenv("USER_COLLECTION",            "users")
ASSIGNMENT_COL = os.getenv("ASSIGNMENT_COLLECTION",      "assignments")
STANDUP_COL    = os.getenv("STANDUP_COLLECTION",         "standups")
MILESTONE_COL  = os.getenv("MILESTONE_COLLECTION",       "milestones")
REVIEW_COL     = os.getenv("REVIEW_COLLECTION",          "reviews")

MILESTONE_STATUSES = {"PENDING", "IN_PROGRESS", "COMPLETED"}

router = APIRouter()


# ── Helpers ───────────────────────────────────────────────────────────────────
def _db(request: Request):
    return request.app.state.db


def _utc_today() -> datetime:
    """Naive UTC midnight — matches how MongoDB stores dates inserted by this router."""
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)


def _strip_tz(dt: datetime) -> datetime:
    """Make a datetime timezone-naive (UTC) so MongoDB range queries work correctly."""
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


def serialize(doc: dict | None) -> dict | None:
    """Recursively convert ObjectId → str so FastAPI can JSON-encode the document."""
    if doc is None:
        return None
    result = {}
    for k, v in doc.items():
        if isinstance(v, ObjectId):
            result[k] = str(v)
        elif isinstance(v, list):
            result[k] = [
                serialize(i) if isinstance(i, dict) else (str(i) if isinstance(i, ObjectId) else i)
                for i in v
            ]
        elif isinstance(v, dict):
            result[k] = serialize(v)
        else:
            result[k] = v
    return result


def oid(s: str) -> ObjectId:
    """String → ObjectId. Raises HTTP 400 on bad format."""
    try:
        return ObjectId(s)
    except Exception:
        raise HTTPException(status_code=400, detail=f"Invalid ObjectId: '{s}'")


def _count_working_days(start: datetime, end: datetime) -> int:
    """Count Mon–Fri days between start and end inclusive. Handles tz-aware or naive."""
    start = _strip_tz(start).replace(hour=0, minute=0, second=0, microsecond=0)
    end   = _strip_tz(end).replace(hour=0, minute=0, second=0, microsecond=0)
    count = 0
    cursor = start
    while cursor <= end:
        if cursor.weekday() < 5:
            count += 1
        cursor += timedelta(days=1)
    return count


def _is_weekday() -> bool:
    return datetime.now(timezone.utc).weekday() < 5   # Mon=0 … Sun=6


# ════════════════════════════════════════════════════════════════════════════════
#  INTERN ROUTES
# ════════════════════════════════════════════════════════════════════════════════

@router.get("/intern/me", summary="Intern: own profile + assignment (with manager / TL / buddy names)")
async def get_intern_me(
    request: Request,
    user:    dict = Depends(require_role("Intern")),
):
    db     = _db(request)
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
    rows       = await db[ASSIGNMENT_COL].aggregate(pipeline).to_list(1)
    assignment = serialize(rows[0]) if rows else None

    return {"intern": intern, "assignment": assignment}


@router.get("/intern/standup/today", summary="Intern: has today's standup been submitted?")
async def get_standup_today(
    request: Request,
    user:    dict = Depends(require_role("Intern")),
):
    db     = _db(request)
    intern = serialize(await db[INTERN_COL].find_one({"employeeId": user.get(SSO_ID_FIELD)}))
    if not intern:
        raise HTTPException(404, "Intern profile not found")

    today   = _utc_today()
    standup = serialize(await db[STANDUP_COL].find_one({"internId": oid(intern["_id"]), "date": today}))
    return {"submitted": standup is not None, "standup": standup, "isWeekday": _is_weekday()}


class StandupBody(BaseModel):
    yesterday: str
    today:     str
    blockers:  Optional[str] = ""


@router.post("/intern/standup", status_code=201, summary="Intern: submit daily standup")
async def submit_standup(
    body:    StandupBody,
    request: Request,
    user:    dict = Depends(require_role("Intern")),
):
    if not body.yesterday.strip():
        raise HTTPException(400, "'yesterday' is required")
    if not body.today.strip():
        raise HTTPException(400, "'today' is required")
    if not _is_weekday():
        raise HTTPException(400, "Standups are only for working days (Mon–Fri)")

    db     = _db(request)
    intern = serialize(await db[INTERN_COL].find_one({"employeeId": user.get(SSO_ID_FIELD)}))
    if not intern:
        raise HTTPException(404, "Intern profile not found")

    assignment = await db[ASSIGNMENT_COL].find_one({"internId": oid(intern["_id"])})
    if not assignment or not assignment.get("buddyId"):
        raise HTTPException(400, "No buddy assigned yet — ask your Tech Lead to assign one")

    today = _utc_today()
    doc = {
        "internId":    oid(intern["_id"]),
        "buddyId":     assignment["buddyId"],
        "date":        today,
        "yesterday":   body.yesterday.strip(),
        "today":       body.today.strip(),
        "blockers":    body.blockers.strip() if body.blockers else "",
        "submittedAt": datetime.now(timezone.utc).replace(tzinfo=None),
        "slaStatus":   "PENDING",
    }
    result = await db[STANDUP_COL].find_one_and_update(
        {"internId": oid(intern["_id"]), "date": today},
        {"$set": doc},
        upsert=True,
        return_document=True,
    )
    return {"standup": serialize(result)}


@router.get("/intern/standups", summary="Intern: paginated standup history")
async def get_standup_history(
    request: Request,
    page:    int = Query(1,  ge=1),
    limit:   int = Query(20, ge=1, le=50),
    user:    dict = Depends(require_role("Intern")),
):
    db     = _db(request)
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


@router.get("/intern/progress", summary="Intern: milestones + completion summary")
async def get_progress(
    request: Request,
    user:    dict = Depends(require_role("Intern")),
):
    db     = _db(request)
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


class MilestoneUpdateBody(BaseModel):
    status: str


@router.patch("/intern/milestone/{milestone_id}", summary="Intern: self-update own milestone status")
async def update_milestone_status(
    milestone_id: str,
    body:         MilestoneUpdateBody,
    request:      Request,
    user:         dict = Depends(require_role("Intern")),
):
    """
    Intern can mark their own milestones as IN_PROGRESS or COMPLETED.
    They cannot mark a COMPLETED milestone back to PENDING (prevents gaming).
    """
    if body.status not in MILESTONE_STATUSES:
        raise HTTPException(400, f"Invalid status. Choose from: {', '.join(MILESTONE_STATUSES)}")

    db     = _db(request)
    intern = serialize(await db[INTERN_COL].find_one({"employeeId": user.get(SSO_ID_FIELD)}))
    if not intern:
        raise HTTPException(404, "Intern profile not found")

    milestone = await db[MILESTONE_COL].find_one({
        "_id":      oid(milestone_id),
        "internId": oid(intern["_id"]),
    })
    if not milestone:
        raise HTTPException(404, "Milestone not found or does not belong to you")
    if milestone.get("status") == "COMPLETED" and body.status == "PENDING":
        raise HTTPException(409, "Cannot move a completed milestone back to PENDING")

    now    = datetime.now(timezone.utc).replace(tzinfo=None)
    update = {"status": body.status, "updatedAt": now}
    if body.status == "COMPLETED":
        update["completedAt"] = now

    result = await db[MILESTONE_COL].find_one_and_update(
        {"_id": oid(milestone_id)},
        {"$set": update},
        return_document=True,
    )
    return {"milestone": serialize(result)}


@router.get("/intern/streak", summary="Intern: consecutive daily standup submission streak")
async def get_streak(
    request: Request,
    user:    dict = Depends(require_role("Intern")),
):
    """
    Counts how many consecutive weekdays (going backwards from today) the intern
    submitted a standup. Useful for gamification / compliance nudges.
    """
    db     = _db(request)
    intern = serialize(await db[INTERN_COL].find_one({"employeeId": user.get(SSO_ID_FIELD)}))
    if not intern:
        raise HTTPException(404, "Intern profile not found")

    # Fetch last 60 standup dates (enough for any real streak)
    rows = await db[STANDUP_COL].find(
        {"internId": oid(intern["_id"])},
        {"date": 1},
    ).sort("date", -1).limit(60).to_list(60)

    submitted_dates = {_strip_tz(r["date"]).date() for r in rows}

    streak  = 0
    cursor  = _utc_today().date()
    # If today not submitted yet, start checking from yesterday
    if cursor not in submitted_dates:
        cursor -= timedelta(days=1)

    while True:
        if cursor.weekday() >= 5:       # skip weekends
            cursor -= timedelta(days=1)
            continue
        if cursor not in submitted_dates:
            break
        streak += 1
        cursor -= timedelta(days=1)

    return {"streak": streak, "unit": "working days"}


@router.get("/intern/compliance", summary="Intern: standup compliance percentage since start date")
async def get_compliance(
    request: Request,
    user:    dict = Depends(require_role("Intern")),
):
    db     = _db(request)
    intern = serialize(await db[INTERN_COL].find_one({"employeeId": user.get(SSO_ID_FIELD)}))
    if not intern:
        raise HTTPException(404, "Intern profile not found")

    raw_start = intern.get("startDate") or intern.get("createdAt")
    if raw_start is None:
        raise HTTPException(400, "Intern has no startDate or createdAt field")

    # Handle both datetime objects and ISO strings robustly
    if isinstance(raw_start, datetime):
        start = _strip_tz(raw_start)
    else:
        # Remove timezone suffix so fromisoformat works on Python <3.11
        start = datetime.fromisoformat(str(raw_start).replace("Z", "").split("+")[0].split(".")[0])

    today        = _utc_today()
    working_days = _count_working_days(start, today)

    submitted = await db[STANDUP_COL].count_documents({
        "internId": oid(intern["_id"]),
        "date":     {"$gte": start.replace(hour=0, minute=0, second=0, microsecond=0), "$lte": today},
    })
    compliance = round((submitted / working_days) * 100) if working_days > 0 else 0
    return {"submitted": submitted, "workingDays": working_days, "compliance": compliance}


@router.get("/intern/feedback", summary="Intern: published performance reviews")
async def get_feedback(
    request: Request,
    user:    dict = Depends(require_role("Intern")),
):
    db     = _db(request)
    intern = serialize(await db[INTERN_COL].find_one({"employeeId": user.get(SSO_ID_FIELD)}))
    if not intern:
        raise HTTPException(404, "Intern profile not found")

    pipeline = [
        {"$match": {"internId": oid(intern["_id"]), "state": "PUBLISHED"}},
        {"$lookup": {"from": USER_COL, "localField": "authorBuddyId", "foreignField": "_id",
                     "as": "_author", "pipeline": [{"$project": {"name": 1, "email": 1}}]}},
        {"$addFields": {"authorBuddyId": {"$arrayElemAt": ["$_author", 0]}}},
        {"$project": {"_author": 0}},
        {"$sort": {"publishedAt": -1}},
    ]
    reviews = [serialize(r) for r in await db[REVIEW_COL].aggregate(pipeline).to_list(None)]
    return {"reviews": reviews}


# ════════════════════════════════════════════════════════════════════════════════
#  TECH LEAD ROUTES
# ════════════════════════════════════════════════════════════════════════════════

@router.get("/tech-lead/interns", summary="Tech Lead: list all assigned interns with buddy info")
async def get_tl_interns(
    request: Request,
    user:    dict = Depends(require_role("Tech Lead")),
):
    db      = _db(request)
    tl_user = serialize(await db[USER_COL].find_one({"employeeId": user.get(SSO_ID_FIELD)}))
    if not tl_user:
        raise HTTPException(404, "Tech Lead user not found")

    pipeline = [
        {"$match": {"techLeadId": oid(tl_user["_id"])}},
        {"$lookup": {
            "from": INTERN_COL, "localField": "internId", "foreignField": "_id", "as": "_intern",
            "pipeline": [{"$project": {"name": 1, "email": 1, "employeeCode": 1,
                                       "department": 1, "startDate": 1, "endDate": 1, "status": 1}}],
        }},
        {"$lookup": {
            "from": USER_COL, "localField": "buddyId", "foreignField": "_id", "as": "_buddy",
            "pipeline": [{"$project": {"name": 1, "email": 1}}],
        }},
        {"$addFields": {
            "internData": {"$arrayElemAt": ["$_intern", 0]},
            "buddyData":  {"$arrayElemAt": ["$_buddy",  0]},
        }},
    ]
    rows    = await db[ASSIGNMENT_COL].aggregate(pipeline).to_list(None)
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


@router.get("/tech-lead/standup-feed", summary="Tech Lead: standup feed across all assigned interns")
async def get_standup_feed(
    request: Request,
    date:    Optional[str] = Query(None, description="Filter by date YYYY-MM-DD"),
    page:    int = Query(1,  ge=1),
    limit:   int = Query(30, ge=1, le=50),
    user:    dict = Depends(require_role("Tech Lead")),
):
    db      = _db(request)
    tl_user = serialize(await db[USER_COL].find_one({"employeeId": user.get(SSO_ID_FIELD)}))
    if not tl_user:
        raise HTTPException(404, "Tech Lead user not found")

    assignments = await db[ASSIGNMENT_COL].find(
        {"techLeadId": oid(tl_user["_id"])}, {"internId": 1}
    ).to_list(None)
    intern_ids = [a["internId"] for a in assignments]

    filt: dict = {"internId": {"$in": intern_ids}}
    if date:
        try:
            # Parse and keep as naive UTC to match stored dates
            day = datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(400, "date must be YYYY-MM-DD")
        filt["date"] = {"$gte": day, "$lte": day.replace(hour=23, minute=59, second=59)}

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


@router.get("/tech-lead/reviews", summary="Tech Lead: reviews waiting for TL sign-off")
async def get_tl_reviews(
    request: Request,
    user:    dict = Depends(require_role("Tech Lead")),
):
    db      = _db(request)
    tl_user = serialize(await db[USER_COL].find_one({"employeeId": user.get(SSO_ID_FIELD)}))
    if not tl_user:
        raise HTTPException(404, "Tech Lead user not found")

    assignments = await db[ASSIGNMENT_COL].find(
        {"techLeadId": oid(tl_user["_id"])}, {"internId": 1}
    ).to_list(None)
    intern_ids = [a["internId"] for a in assignments]

    pipeline = [
        {"$match": {"internId": {"$in": intern_ids}, "state": "TL_REVIEW"}},
        {"$lookup": {"from": INTERN_COL, "localField": "internId",
                     "foreignField": "_id", "as": "_intern",
                     "pipeline": [{"$project": {"name": 1, "email": 1, "employeeCode": 1}}]}},
        {"$lookup": {"from": USER_COL, "localField": "authorBuddyId",
                     "foreignField": "_id", "as": "_author",
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


@router.post("/tech-lead/reviews/{review_id}/forward",
             summary="Tech Lead: approve review and forward to Manager")
async def forward_review(
    review_id: str,
    body:      ForwardReviewBody,
    request:   Request,
    user:      dict = Depends(require_role("Tech Lead")),
):
    db      = _db(request)
    tl_user = serialize(await db[USER_COL].find_one({"employeeId": user.get(SSO_ID_FIELD)}))
    if not tl_user:
        raise HTTPException(404, "Tech Lead user not found")

    review = await db[REVIEW_COL].find_one({"_id": oid(review_id)})
    if not review:
        raise HTTPException(404, "Review not found")
    if review.get("state") != "TL_REVIEW":
        raise HTTPException(409, f"Review is in '{review['state']}' — can only forward from TL_REVIEW")

    owns = await db[ASSIGNMENT_COL].find_one({
        "internId":   review["internId"],
        "techLeadId": oid(tl_user["_id"]),
    })
    if not owns:
        raise HTTPException(403, "This review does not belong to your interns")

    now    = datetime.now(timezone.utc).replace(tzinfo=None)
    stages = review.get("stages", [])
    tl_stage_closed = False
    for stage in stages:
        if stage.get("stage") == "TL_REVIEW" and not stage.get("exitedAt"):
            stage["comment"]  = body.comment.strip() if body.comment else ""
            stage["exitedAt"] = now
            tl_stage_closed   = True
            break
    if not tl_stage_closed:
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


@router.post("/tech-lead/assign-buddy", summary="Tech Lead: assign or re-assign a buddy to an intern")
async def assign_buddy(
    body:    AssignBuddyBody,
    request: Request,
    user:    dict = Depends(require_role("Tech Lead")),
):
    db      = _db(request)
    tl_user = serialize(await db[USER_COL].find_one({"employeeId": user.get(SSO_ID_FIELD)}))
    if not tl_user:
        raise HTTPException(404, "Tech Lead user not found")

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
        raise HTTPException(400, f"'{buddy['name']}' has role '{buddy['role']}', not 'Buddy'")

    now     = datetime.now(timezone.utc).replace(tzinfo=None)
    history = assignment.get("history", [])
    history.append({
        "field": "buddyId", "fromId": assignment.get("buddyId"),
        "toId":  oid(body.buddyUserId), "byUserId": oid(tl_user["_id"]), "at": now,
    })
    new_state = "BUDDY_ASSIGNED" if assignment.get("state") == "TECHLEAD_ASSIGNED" else assignment.get("state")
    result    = await db[ASSIGNMENT_COL].find_one_and_update(
        {"_id": assignment["_id"]},
        {"$set": {"buddyId": oid(body.buddyUserId), "state": new_state,
                  "history": history, "updatedAt": now}},
        return_document=True,
    )

    pipeline = [
        {"$match": {"_id": result["_id"]}},
        {"$lookup": {"from": USER_COL, "localField": "buddyId", "foreignField": "_id", "as": "_buddy",
                     "pipeline": [{"$project": {"name": 1, "email": 1}}]}},
        {"$addFields": {"buddyId": {"$arrayElemAt": ["$_buddy", 0]}}},
        {"$project": {"_buddy": 0}},
    ]
    rows = await db[ASSIGNMENT_COL].aggregate(pipeline).to_list(1)
    return {"assignment": serialize(rows[0]) if rows else serialize(result)}


@router.get("/tech-lead/buddies", summary="Tech Lead: list available Buddy users for assignment")
async def get_buddies(
    request: Request,
    user:    dict = Depends(require_role("Tech Lead")),
):
    db      = _db(request)
    buddies = [
        serialize(b) for b in
        await db[USER_COL].find(
            {"role": "Buddy", "isActive": {"$ne": False}},
            {"name": 1, "email": 1, "employeeId": 1},
        ).sort("name", 1).to_list(None)
    ]
    return {"buddies": buddies}


@router.get("/tech-lead/dashboard-summary", summary="Tech Lead: at-a-glance stats for dashboard")
async def get_dashboard_summary(
    request: Request,
    user:    dict = Depends(require_role("Tech Lead")),
):
    db      = _db(request)
    tl_user = serialize(await db[USER_COL].find_one({"employeeId": user.get(SSO_ID_FIELD)}))
    if not tl_user:
        raise HTTPException(404, "Tech Lead user not found")

    assignments = await db[ASSIGNMENT_COL].find(
        {"techLeadId": oid(tl_user["_id"])}, {"internId": 1, "buddyId": 1}
    ).to_list(None)
    intern_ids = [a["internId"] for a in assignments]

    today = _utc_today()

    # Run all three DB counts concurrently
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
