import json
from datetime import datetime, date
from fastapi import FastAPI, Request, Form, UploadFile, File, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from database import create_users_table, engine, get_db
from models import Base, User, Resume, JobSuggestion, AppliedJob
from auth import create_user, authenticate_user
import os
import shutil
from resume_extracter import extract_text
from resume_parser import parse_resume
from job_links import generate_redirect_links

Base.metadata.create_all(bind=engine)

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="supersecretkey")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
create_users_table()


# ═══════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════

def _get_current_user(request: Request, db: Session):
    email = request.session.get("user")
    if not email:
        return None
    return db.query(User).filter(User.email == email).first()


def _already_applied_urls(user_id: int, db: Session) -> set:
    rows = db.query(AppliedJob).filter(AppliedJob.user_id == user_id).all()
    return {r.apply_url for r in rows if r.apply_url}


def _get_latest_resume(user_id: int, db: Session):
    """Get the most recent resume for a user."""
    return (
        db.query(Resume)
        .filter(Resume.user_id == user_id)
        .order_by(Resume.id.desc())
        .first()
    )


def _has_resume(user_id: int, db: Session) -> bool:
    """Check if user already has a resume uploaded."""
    resume = _get_latest_resume(user_id, db)
    # Has a real resume only if role or summary is not empty
    return resume is not None and (resume.role or resume.summary)


# ═══════════════════════════════════════════════════════════════════
# REGISTER
# ═══════════════════════════════════════════════════════════════════

@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    return templates.TemplateResponse("register.html", {
        "request":  request,
        "message":  request.session.pop("message", None),
        "msg_type": request.session.pop("msg_type", None)
    })


@app.post("/register")
def register_user(request: Request,
                  name: str = Form(...),
                  email: str = Form(...),
                  password: str = Form(...)):
    if not create_user(name, email, password):
        request.session["message"]  = "Email already registered"
        request.session["msg_type"] = "error"
        return RedirectResponse("/register", status_code=303)
    request.session["message"]  = "Registration successful! Please login"
    request.session["msg_type"] = "success"
    return RedirectResponse("/login", status_code=303)


# ═══════════════════════════════════════════════════════════════════
# LOGIN / LOGOUT
# ═══════════════════════════════════════════════════════════════════

@app.get("/")
def home():
    return RedirectResponse("/login")


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {
        "request":  request,
        "message":  request.session.pop("message", None),
        "msg_type": request.session.pop("msg_type", None)
    })


@app.post("/login")
def login_user(request: Request,
               email: str = Form(...),
               password: str = Form(...)):
    user = authenticate_user(email, password)
    if user:
        request.session["user"] = user
        return RedirectResponse("/dashboard", status_code=303)
    request.session["message"]  = "Invalid email or password"
    request.session["msg_type"] = "error"
    return RedirectResponse("/login", status_code=303)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


# ═══════════════════════════════════════════════════════════════════
# DASHBOARD — shows resume info if exists, upload form if not
# ═══════════════════════════════════════════════════════════════════

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    if "user" not in request.session:
        return RedirectResponse("/login", status_code=303)

    user = _get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)

    resume       = _get_latest_resume(user.id, db)
    has_resume   = _has_resume(user.id, db)
    resume_data  = None

    if has_resume and resume:
        # Parse skills from JSON if stored
        skills = []
        try:
            skills = json.loads(resume.experience) if resume.experience else []
            if not isinstance(skills, list):
                skills = []
        except Exception:
            skills = []

        # Load from parsed_resumes.json for richer display
        parsed_file = f"parsed_resumes_{user.id}.json"
        if os.path.exists(parsed_file):
            with open(parsed_file) as f:
                saved = json.load(f)
                skills = saved.get("skills", skills)

        resume_data = {
            "name":             user.username,
            "role":             resume.role or "Professional",
            "summary":          resume.summary or "",
            "skills":           skills[:10],
            "uploaded_at":      resume.created_at.strftime("%d %b %Y") if resume.created_at else "",
        }

    return templates.TemplateResponse("dashboard.html", {
        "request":    request,
        "user":       request.session["user"],
        "has_resume": has_resume,
        "resume":     resume_data,
        "message":    request.session.pop("message", None),
        "msg_type":   request.session.pop("msg_type", None),
    })


# ═══════════════════════════════════════════════════════════════════
# UPLOAD RESUME — blocked if already uploaded (unless update=true)
# ═══════════════════════════════════════════════════════════════════

@app.post("/upload_resume")
async def upload_resume(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):

    print("Upload route called")

    # Step 1: Save file
    os.makedirs("uploads", exist_ok=True)
    file_path = f"uploads/{file.filename}"
    with open(file_path, "wb") as f:
        f.write(await file.read())

    print("🔄 Processing resume...")

    text = extract_text(file_path)
    parsed_data = parse_resume(text)
    skills = parsed_data["skills"]

    print("✅ Skills:", skills)

    from company_matcher import get_best_matching_companies
    from job_links import generate_redirect_links
    from datetime import datetime

    best_matches = get_best_matching_companies(skills, limit=15)
    query = " ".join(skills[:2]) if skills else "developer"
    links = generate_redirect_links(query)

    # ✅ Save to DB
    user = _get_current_user(request, db)
    if user:
        # Save Resume record
        existing_resume = db.query(Resume).filter(Resume.user_id == user.id).first()
        if existing_resume:
            existing_resume.role       = parsed_data.get("summary", "")[:100]
            existing_resume.summary    = parsed_data.get("summary", "")
            existing_resume.experience = json.dumps(skills)
        else:
            db.add(Resume(
                user_id    = user.id,
                role       = parsed_data.get("summary", "")[:100],
                summary    = parsed_data.get("summary", ""),
                experience = json.dumps(skills),
            ))

        # Save parsed resume to file for dashboard display
        parsed_file = f"parsed_resumes_{user.id}.json"
        with open(parsed_file, "w") as f:
            json.dump(parsed_data, f)

        # Clear old unapplied suggestions
        db.query(JobSuggestion).filter(
            JobSuggestion.user_id    == user.id,
            JobSuggestion.is_applied == False
        ).delete()

        # Save new suggestions
        saved = 0
        for job in best_matches:
            apply_url = job.get("apply_url", "")
            if not apply_url:
                continue  # skip jobs with no link
            db.add(JobSuggestion(
            user_id        = user.id,
            title          = job.get("title", ""),
            company        = job.get("company", ""),
            platform       = job.get("platform", ""),
            apply_url      = apply_url,
            match_score    = job.get("match_score", 0.0),    # ← real score
            date_suggested = datetime.utcnow(),
            is_applied     = False
            ))
            saved += 1

        db.commit()
        print(f"💾 Saved {saved} suggestions for user {user.id}")
    else:
        print("⚠️ No logged-in user found — suggestions not saved")

    return {
        "skills": skills,
        "jobs":   best_matches,
        "links":  links
    }


# ═══════════════════════════════════════════════════════════════════
# DELETE RESUME — allows user to remove CV and upload fresh one
# ═══════════════════════════════════════════════════════════════════

@app.post("/delete_resume")
def delete_resume(request: Request, db: Session = Depends(get_db)):
    if "user" not in request.session:
        return JSONResponse({"error": "Not logged in"}, status_code=401)

    user = _get_current_user(request, db)
    if not user:
        return JSONResponse({"error": "User not found"}, status_code=401)

    db.query(Resume).filter(Resume.user_id == user.id).delete()
    db.query(JobSuggestion).filter(
        JobSuggestion.user_id    == user.id,
        JobSuggestion.is_applied == False
    ).delete()
    db.commit()

    # Remove cache file
    parsed_file = f"parsed_resumes_{user.id}.json"
    if os.path.exists(parsed_file):
        os.remove(parsed_file)

    print(f"🗑️  Resume deleted for user {user.id}")
    return JSONResponse({"success": True, "message": "Resume deleted. You can upload a new one."})


# ═══════════════════════════════════════════════════════════════════
# GET SUGGESTIONS
# ═══════════════════════════════════════════════════════════════════

@app.get("/get_suggestions")
def get_suggestions(request: Request, db: Session = Depends(get_db)):
    if "user" not in request.session:
        return JSONResponse([], status_code=401)

    user = _get_current_user(request, db)
    if not user:
        return JSONResponse([])

    applied_urls = _already_applied_urls(user.id, db)

    suggestions = (
        db.query(JobSuggestion)
        .filter(
            JobSuggestion.user_id    == user.id,
            JobSuggestion.is_applied == False
        )
        .order_by(JobSuggestion.match_score.desc())
        .limit(5)
        .all()
    )

    result = []
    for s in suggestions:
        if s.apply_url in applied_urls:
            continue
        result.append({
            "id":          s.id,
            "role":        s.title,
            "company":     s.company,
            "platform":    s.platform,
            "apply_url":   s.apply_url,
            "match_score": round(s.match_score * 100) if s.match_score and s.match_score <= 1 else int(s.match_score or 0),
            "match_label": (
            "🟢 Strong Match"  if (s.match_score or 0) >= 0.6 else
            "🟡 Good Match"    if (s.match_score or 0) >= 0.3 else
            "🔴 Partial Match"
            ),
            "date":        s.date_suggested.strftime("%d %b %Y") if s.date_suggested else ""
        })

    print(f"📋 Returning {len(result)} suggestions for user {user.id}")
    return JSONResponse(result)


# ═══════════════════════════════════════════════════════════════════
# MARK APPLIED
# ═══════════════════════════════════════════════════════════════════

@app.post("/mark_applied/{job_id}")
def mark_applied(job_id: int, request: Request, db: Session = Depends(get_db)):
    if "user" not in request.session:
        return JSONResponse({"error": "Not logged in"}, status_code=401)

    user = _get_current_user(request, db)
    if not user:
        return JSONResponse({"error": "User not found"}, status_code=401)

    suggestion = db.query(JobSuggestion).filter(
        JobSuggestion.id      == job_id,
        JobSuggestion.user_id == user.id
    ).first()

    if not suggestion:
        return JSONResponse({"error": "Not found"}, status_code=404)

    suggestion.is_applied = True

    already = db.query(AppliedJob).filter(
        AppliedJob.user_id   == user.id,
        AppliedJob.apply_url == suggestion.apply_url
    ).first()

    if not already:
        db.add(AppliedJob(
            user_id     = user.id,
            title       = suggestion.title,
            company     = suggestion.company,
            platform    = suggestion.platform,
            apply_url   = suggestion.apply_url,
            match_score = suggestion.match_score,
            applied_at  = datetime.utcnow(),
            status      = "applied"
        ))

    db.commit()
    return JSONResponse({"success": True, "job_id": job_id, "redirect_url": "/applied"})


# ═══════════════════════════════════════════════════════════════════
# SUGGESTIONS PAGE
# ═══════════════════════════════════════════════════════════════════

@app.get("/suggestions", response_class=HTMLResponse)
def suggestions_page(request: Request):
    if "user" not in request.session:
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse("suggestions.html", {
        "request": request,
        "user":    request.session["user"]
    })


# ═══════════════════════════════════════════════════════════════════
# APPLIED PAGE
# ═══════════════════════════════════════════════════════════════════

@app.get("/applied", response_class=HTMLResponse)
def applied_page(request: Request, db: Session = Depends(get_db)):
    if "user" not in request.session:
        return RedirectResponse("/login", status_code=303)

    user    = _get_current_user(request, db)
    applied = []

    if user:
        rows = (
            db.query(AppliedJob)
            .filter(AppliedJob.user_id == user.id)
            .order_by(AppliedJob.applied_at.desc())
            .all()
        )
        for a in rows:
            applied.append({
                "title":       a.title,
                "company":     a.company,
                "platform":    a.platform,
                "apply_url":   a.apply_url,
                "status":      a.status,
                "applied_at":  a.applied_at.strftime("%d %b %Y") if a.applied_at else "",
                "match_score": a.match_score
            })

    return templates.TemplateResponse("applied.html", {
        "request": request,
        "user":    request.session["user"],
        "applied": applied
    })


# ═══════════════════════════════════════════════════════════════════
# GET APPLIED (JSON for applied.html fetch)
# ═══════════════════════════════════════════════════════════════════

@app.get("/get_applied")
def get_applied(request: Request, db: Session = Depends(get_db)):
    if "user" not in request.session:
        return JSONResponse([], status_code=401)

    user = _get_current_user(request, db)
    if not user:
        return JSONResponse([])

    rows = (
        db.query(AppliedJob)
        .filter(AppliedJob.user_id == user.id)
        .order_by(AppliedJob.applied_at.desc())
        .all()
    )

    result = []
    for a in rows:
        result.append({
            "role":         a.title,
            "company":      a.company,
            "platform":     a.platform,
            "apply_url":    a.apply_url,
            "status":       a.status,
            "applied_date": a.applied_at.strftime("%d %b %Y") if a.applied_at else "",
            "match_score":  round(a.match_score * 100) if a.match_score and a.match_score <= 1 else int(a.match_score or 0),
        })

    return JSONResponse(result)


# ═══════════════════════════════════════════════════════════════════
# SEND EMAIL
# ═══════════════════════════════════════════════════════════════════

@app.post("/send_best_matches")
async def send_best_matches(request: Request):
    body  = await request.json()
    email = body.get("email", "")
    print(f"📧 Email requested → {email}")
    return JSONResponse({"sent": True})










@app.get("/quick-job-links")
def quick_job_links(query: str, location: str = "India"):
    return generate_redirect_links(query, location)