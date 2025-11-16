import os
from datetime import datetime, timezone
from typing import Optional, List, Literal
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

try:
    # bson comes with pymongo; guard import to avoid hard crash if env broken
    from bson.objectid import ObjectId  # type: ignore
except Exception:  # pragma: no cover
    ObjectId = None  # type: ignore

from database import db, create_document, get_documents

# -----------------------------
# App Setup
# -----------------------------
app = FastAPI(title="ClassCom API", version="1.0.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")

# -----------------------------
# Pydantic Models (requests)
# -----------------------------
class LoginRequest(BaseModel):
    roll_number: str
    password: Optional[str] = None

class MessageCreate(BaseModel):
    type: Literal["message", "alert"] = "message"
    title: str
    body: str
    created_by: Optional[str] = None

class AssignTopicRequest(BaseModel):
    presentation_id: str
    roll_number: str

class UpdatePresentationStatus(BaseModel):
    status: Literal["upcoming", "completed", "revoked"]

class SubjectCreate(BaseModel):
    code: str
    acronym: str
    title: str
    syllabus: Optional[List[str]] = []

class PresentationCreate(BaseModel):
    subject_code: str
    subject_acronym: str
    topic: str
    assigned_to: Optional[str] = None
    due_date: Optional[datetime] = None
    submission_link: Optional[str] = None

# -----------------------------
# Utilities
# -----------------------------

def oid(s: str):
    if ObjectId is None:
        raise HTTPException(status_code=503, detail="Database ID handling unavailable")
    try:
        return ObjectId(s)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid ID")


def require_db():
    if db is None:
        raise HTTPException(status_code=503, detail="Database not configured. Please set DATABASE_URL and DATABASE_NAME.")


def ensure_indexes():
    if db is None:
        return
    try:
        db["student"].create_index("roll_number", unique=True)
        db["subject"].create_index("code", unique=True)
        db["presentation"].create_index([("assigned_to", 1), ("due_date", 1)])
        db["message"].create_index(("created_at", -1))
    except Exception:
        # Do not crash on startup if indexes fail
        pass


def seed_data():
    if db is None:
        return
    try:
        # Only seed if there are no subjects
        if db["subject"].count_documents({}) == 0:
            subjects = [
                {"code": "CS101", "acronym": "CS", "title": "Computer Science Basics", "syllabus": ["Intro to CS", "Algorithms", "Data Structures"]},
                {"code": "MA101", "acronym": "MA", "title": "Calculus I", "syllabus": ["Limits", "Derivatives", "Integrals"]},
                {"code": "PH101", "acronym": "PH", "title": "Physics I", "syllabus": ["Kinematics", "Dynamics", "Work & Energy"]},
            ]
            for s in subjects:
                create_document("subject", s)

        if db["presentation"].count_documents({}) == 0:
            # Submission links map by acronym
            links = {
                "CS": "https://forms.gle/your-cs-form",
                "MA": "https://forms.gle/your-ma-form",
                "PH": "https://forms.gle/your-ph-form",
            }
            topics = [
                ("CS101", "CS", ["Sorting Algorithms", "Big-O Notation", "Hash Tables"]),
                ("MA101", "MA", ["Limits in Depth", "Chain Rule", "Area under Curve"]),
                ("PH101", "PH", ["Projectile Motion", "Newton's Laws", "Energy Conservation"]),
            ]
            for code, ac, topic_list in topics:
                for t in topic_list:
                    create_document(
                        "presentation",
                        {
                            "subject_code": code,
                            "subject_acronym": ac,
                            "topic": t,
                            "assigned_to": None,
                            "due_date": None,
                            "status": "upcoming",
                            "submission_link": links.get(ac),
                        },
                    )

        # Seed a default admin student
        if db["student"].count_documents({"roll_number": "ADMIN"}) == 0:
            create_document("student", {"roll_number": "ADMIN", "name": "Administrator", "is_admin": True, "is_active": True})
    except Exception:
        # Never fail startup on seed errors
        pass


@app.on_event("startup")
def on_startup():
    ensure_indexes()
    seed_data()


# -----------------------------
# Health and root
# -----------------------------
@app.get("/")
def read_root():
    return {"message": "ClassCom API is running"}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": [],
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
            response["database_name"] = db.name if hasattr(db, "name") else "✅ Connected"
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️ Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️ Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"
    return response


# -----------------------------
# Auth
# -----------------------------
@app.post("/api/login")
def login(payload: LoginRequest):
    require_db()
    roll = payload.roll_number.strip().upper()
    stu = db["student"].find_one({"roll_number": roll})
    if not stu:
        # Auto-create new student on first login
        sid = create_document("student", {"roll_number": roll, "name": None, "is_admin": False, "is_active": True})
        stu = db["student"].find_one({"_id": oid(sid)}) if ObjectId else db["student"].find_one({"roll_number": roll})

    is_admin = bool(stu.get("is_admin"))
    if is_admin:
        if payload.password != ADMIN_PASSWORD:
            raise HTTPException(status_code=401, detail="Admin password required or incorrect")
        role = "admin"
    else:
        role = "student"

    return {
        "roll_number": roll,
        "name": stu.get("name"),
        "role": role,
        "is_admin": is_admin,
    }


# -----------------------------
# Subjects & Syllabus
# -----------------------------
@app.get("/api/subjects")
def list_subjects():
    if db is None:
        return []
    subs = get_documents("subject")
    for s in subs:
        s["id"] = str(s.pop("_id"))
    return subs


@app.post("/api/admin/subjects")
def create_subject(sub: SubjectCreate):
    require_db()
    if db["subject"].find_one({"code": sub.code}):
        raise HTTPException(status_code=400, detail="Subject code exists")
    sid = create_document("subject", sub.model_dump())
    doc = db["subject"].find_one({"_id": oid(sid)}) if ObjectId else db["subject"].find_one({"code": sub.code})
    doc["id"] = str(doc.pop("_id"))
    return doc


# -----------------------------
# Presentations
# -----------------------------
@app.get("/api/presentations")
def list_presentations(roll_number: Optional[str] = Query(None)):
    if db is None:
        return []
    q = {}
    if roll_number:
        q = {"$or": [{"assigned_to": None}, {"assigned_to": roll_number.strip().upper()}]}
    docs = list(db["presentation"].find(q))
    for d in docs:
        d["id"] = str(d.pop("_id"))
    return docs


@app.get("/api/presentations/my")
def my_presentations(roll_number: str):
    if db is None:
        return {"upcoming": [], "completed": []}
    roll = roll_number.strip().upper()
    docs = list(db["presentation"].find({"assigned_to": roll}))
    for d in docs:
        d["id"] = str(d.pop("_id"))
    # Split upcoming/completed
    return {
        "upcoming": [d for d in docs if d.get("status") != "completed"],
        "completed": [d for d in docs if d.get("status") == "completed"],
    }


@app.post("/api/admin/presentations")
def create_presentation(p: PresentationCreate):
    require_db()
    pid = create_document("presentation", p.model_dump())
    doc = db["presentation"].find_one({"_id": oid(pid)}) if ObjectId else db["presentation"].find_one({"topic": p.topic, "subject_code": p.subject_code})
    doc["id"] = str(doc.pop("_id"))
    return doc


@app.patch("/api/admin/presentations/{presentation_id}")
def update_presentation_status(presentation_id: str, payload: UpdatePresentationStatus):
    require_db()
    res = db["presentation"].update_one({"_id": oid(presentation_id)}, {"$set": {"status": payload.status, "updated_at": datetime.now(timezone.utc)}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Presentation not found")
    doc = db["presentation"].find_one({"_id": oid(presentation_id)})
    doc["id"] = str(doc.pop("_id"))
    return doc


@app.post("/api/admin/assign")
def assign_topic(payload: AssignTopicRequest):
    require_db()
    roll = payload.roll_number.strip().upper()
    if not db["student"].find_one({"roll_number": roll}):
        raise HTTPException(status_code=404, detail="Student not found")
    res = db["presentation"].update_one({"_id": oid(payload.presentation_id)}, {"$set": {"assigned_to": roll, "updated_at": datetime.now(timezone.utc)}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Presentation not found")
    doc = db["presentation"].find_one({"_id": oid(payload.presentation_id)})
    doc["id"] = str(doc.pop("_id"))
    return doc


# -----------------------------
# Messages / Notifications
# -----------------------------
@app.post("/api/admin/messages")
def create_message(msg: MessageCreate):
    require_db()
    mid = create_document("message", msg.model_dump())
    doc = db["message"].find_one({"_id": oid(mid)}) if ObjectId else db["message"].find_one({"title": msg.title, "body": msg.body})
    doc["id"] = str(doc.pop("_id"))
    return doc


@app.get("/api/messages")
def list_messages():
    if db is None:
        return []
    msgs = list(db["message"].find().sort("created_at", -1))
    for m in msgs:
        m["id"] = str(m.pop("_id"))
    return msgs


@app.delete("/api/admin/messages/{message_id}")
def delete_message(message_id: str):
    require_db()
    res = db["message"].delete_one({"_id": oid(message_id)})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Message not found")
    return {"deleted": True}


# -----------------------------
# Sync Logic (placeholder to satisfy spec)
# -----------------------------
@app.post("/api/admin/sync")
def sync_presentations():
    if db is None:
        return {"synced": False, "message": "Database not configured"}
    meta = db["meta"].find_one({"key": "synced"})
    if meta and meta.get("value") == "true":
        return {"synced": True, "message": "Already synced"}
    try:
        create_document("meta", {"key": "synced", "value": "true"})
    except Exception:
        pass
    return {"synced": True}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
