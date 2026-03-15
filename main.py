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
def upload_resume(
    request: Request,
    file: UploadFile = File(...),
    update: str = Form("false"),       # "true" = user wants to update CV
    db: Session = Depends(get_db)
):
    print("Upload route called")

    if "user" not in request.session:
        return JSONResponse({"error": "Not logged in"}, status_code=401)

    user = _get_current_user(request, db)
    if not user:
        return JSONResponse({"error": "User not found"}, status_code=401)

    # ── Block duplicate uploads ────────────────────────────────────
    if _has_resume(user.id, db) and update != "true":
        print(f"⚠️  User {user.id} already has a resume — skipping upload")
        resume = _get_latest_resume(user.id, db)

        # Return existing parsed data from cache
        parsed_file = f"parsed_resumes_{user.id}.json"
        parsed_data = {}
        if os.path.exists(parsed_file):
            with open(parsed_file) as f:
                parsed_data = json.load(f)

        return JSONResponse({
            "message":      "Resume already on file! Showing your saved suggestions.",
            "already_exists": True,
            "skills_found": parsed_data.get("skills", []),
            "parsed": {
                "name":             parsed_data.get("name", user.username),
                "email":            parsed_data.get("email", ""),
                "experience_years": parsed_data.get("experience_years", 0),
                "education":        parsed_data.get("education", []),
            }
        })

    # ── Save file ──────────────────────────────────────────────────
    os.makedirs("uploads", exist_ok=True)
    file_path = os.path.join("uploads", file.filename)
    with open(file_path, "wb") as buf:
        shutil.copyfileobj(file.file, buf)

    # ── Extract + Parse (Gemini with cache) ───────────────────────
    resume_text = extract_text(file_path)
    parsed_data = parse_resume(resume_text)
    print("Parsed:", parsed_data)

    # Save per-user parsed file
    parsed_file = f"parsed_resumes_{user.id}.json"
    with open(parsed_file, "w") as f:
        json.dump(parsed_data, f, indent=4)

    # ── Prepare values ────────────────────────────────────────────
    skills_list     = parsed_data.get("skills", []) or []
    experience_list = parsed_data.get("experience", []) or []
    summary         = parsed_data.get("summary") or ""
    role            = summary or ", ".join(skills_list[:5])

    # ── If updating: delete old resume rows ───────────────────────
    if update == "true":
        db.query(Resume).filter(Resume.user_id == user.id).delete()
        db.commit()
        print(f"🔄 Old resumes deleted for user {user.id}")

    # ── Save new resume row ───────────────────────────────────────
    resume = Resume(
        user_id    = user.id,
        file_path  = file_path,
        role       = role,
        experience = json.dumps(experience_list),
        summary    = summary
    )
    db.add(resume)
    db.commit()
    db.refresh(resume)
    print(f"✅ Resume saved id={resume.id}")

    # ── Scrape jobs + BERT match + save TOP 5 ─────────────────────
    already_applied = _already_applied_urls(user.id, db)
    exp_titles      = [e.get("title", "") for e in experience_list if isinstance(e, dict)]
    resume_bert     = f"{summary} {' '.join(skills_list)} {' '.join(exp_titles)}".strip()

    best_matches = []
    try:
        from models import match_jobs_to_resume
        from job_links import scrape_all_jobs

        GENERIC_SKILLS = {
            'css', 'html', 'linux', 'jupyter', 'github', 'git', 'power bi',
            'microsoft office', 'excel', 'word', 'powerpoint', 'communication',
            'teamwork', 'leadership', 'problem solving', 'ms office', 'windows',
            'agile', 'scrum', 'jira', 'confluence', 'slack', 'zoom'
        }

        ROLE_KEYWORDS = {
            'python': 'Python Developer',
            'django': 'Python Django Developer',
            'fastapi': 'Python Backend Developer',
            'react': 'React Frontend Developer',
            'node': 'Node.js Developer',
            'java': 'Java Developer',
            'spring': 'Java Spring Developer',
            'machine learning': 'Machine Learning Engineer',
            'ml': 'Machine Learning Engineer',
            'deep learning': 'Deep Learning Engineer',
            'nlp': 'NLP Engineer',
            'data science': 'Data Scientist',
            'tensorflow': 'Deep Learning Engineer',
            'pytorch': 'ML Engineer',
            'flutter': 'Flutter Developer',
            'android': 'Android Developer',
            'ios': 'iOS Developer',
            'devops': 'DevOps Engineer',
            'docker': 'DevOps Engineer',
            'kubernetes': 'DevOps Engineer',
            'aws': 'Cloud Engineer',
            'azure': 'Cloud Developer',
            'sql': 'Database Developer',
            'mongodb': 'Backend Developer',
            'opencv': 'Computer Vision Engineer',
            'keras': 'Deep Learning Engineer',
            'data analyst': 'Data Analyst',
            'tableau': 'Data Analyst',
        }
        def build_job_query(skills: list, summary: str = "") -> str:
            """
            Build a smart, role-based job search query from resume skills.
            Priority: summary role > tech skill mapping > top tech skills
            """
        skills_lower = [s.lower() for s in skills]

        # Priority 1: Check summary for explicit role mention
        summary_lower = summary.lower()
        role_hints = ['developer', 'engineer', 'analyst', 'scientist', 
                    'designer', 'architect', 'manager', 'intern']
        for hint in role_hints:
            if hint in summary_lower:
                # Extract role phrase from summary (first 6 words)
                words = summary_lower.split()
                idx = words.index(hint) if hint in words else -1
                if idx >= 0:
                    role_phrase = " ".join(words[max(0, idx-2):idx+1]).title()
                    print(f"🎯 Query from summary: '{role_phrase}'")
                    return role_phrase

        # Priority 2: Map known tech skills to job role
        for skill in skills_lower:
            if skill in ROLE_KEYWORDS:
                role = ROLE_KEYWORDS[skill]
                print(f"🎯 Query from skill mapping: '{role}'")
                return role

    # Priority 3: Filter generic skills, use top 3 tech skills
        tech = [s for s in skills if s.lower() not in GENERIC_SKILLS]
        if tech:
            query = " ".join(tech[:3]) + " Developer"
            print(f"🎯 Query from tech skills: '{query}'")
            return query

        # Fallback
        print("🎯 Query: fallback 'Software Developer'")
        return "Software Developer"
    
        query = build_job_query(skills_list, summary)

        jobs = scrape_all_jobs(query, location="India")
        print(f"📦 Total scraped: {len(jobs)}")

        if jobs:
            jobs    = [j for j in jobs if j.get("url", "") not in already_applied]
            matched = match_jobs_to_resume(resume_bert, jobs)

            # Delete old non-applied suggestions, save fresh top 5
            db.query(JobSuggestion).filter(
                JobSuggestion.user_id    == user.id,
                JobSuggestion.is_applied == False
            ).delete()
            db.commit()

            for item in matched[:5]:
                job   = item.get("job", {})
                score = item.get("similarity", 0)
                url   = job.get("url", "")
                if not url:
                    continue

                db.add(JobSuggestion(
                    user_id        = user.id,
                    title          = job.get("title", ""),
                    company        = job.get("company", ""),
                    platform       = job.get("platform", ""),
                    apply_url      = url,
                    match_score    = score,
                    date_suggested = datetime.utcnow(),
                    is_applied     = False
                ))
                best_matches.append({
                    "name":        job.get("company", ""),
                    "role":        job.get("title", ""),
                    "match_score": round(score * 100),
                    "apply_url":   url
                })

            db.commit()
            print(f"✅ Saved {len(best_matches)} job suggestions")

    except Exception as e:
        print(f"⚠️  Scraper/matcher error: {e}")
        import traceback
        traceback.print_exc()

    return JSONResponse({
        "message":      "Resume uploaded and parsed successfully!",
        "skills_found": skills_list,
        "best_matches": best_matches,
        "parsed": {
            "name":             parsed_data.get("name"),
            "email":            parsed_data.get("email"),
            "experience_years": parsed_data.get("experience_years", 0),
            "education":        parsed_data.get("education", []),
        }
    })


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
            "match_score": round(s.match_score * 100) if s.match_score <= 1 else int(s.match_score),
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







# # import json
# # from datetime import datetime
# # from fastapi import FastAPI, Request, Form, UploadFile, File, Depends, status
# # from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
# # from fastapi.templating import Jinja2Templates
# # from starlette.middleware.sessions import SessionMiddleware
# # from fastapi.staticfiles import StaticFiles
# # from sqlalchemy.orm import Session
# # from database import create_users_table, engine, get_db
# # from models import Base, User, Resume, JobSuggestion, AppliedJob
# # from auth import create_user, authenticate_user
# # import os
# # import shutil
# # from resume_extracter import extract_text
# # from resume_parser import parse_resume

# # Base.metadata.create_all(bind=engine)

# # app = FastAPI()
# # app.add_middleware(SessionMiddleware, secret_key="supersecretkey")
# # app.mount("/static", StaticFiles(directory="static"), name="static")
# # templates = Jinja2Templates(directory="templates")
# # create_users_table()


# # # ── helpers ────────────────────────────────────────────────────────

# # def _get_current_user(request: Request, db: Session):
# #     """Returns User object from session, or None."""
# #     email = request.session.get("user")
# #     if not email:
# #         return None
# #     return db.query(User).filter(User.email == email).first()


# # def _placeholder_matches(skills: list) -> list:
# #     """Placeholder job matches shown while real scraper is being built."""
# #     role = skills[0] if skills else "Developer"
# #     return [
# #         {"name": "LinkedIn Jobs", "role": f"{role} Engineer",    "match_score": 88, "apply_url": "https://linkedin.com/jobs"},
# #         {"name": "Indeed",        "role": f"Senior {role}",      "match_score": 83, "apply_url": "https://indeed.com"},
# #         {"name": "Naukri",        "role": f"{role} Specialist",   "match_score": 79, "apply_url": "https://naukri.com"},
# #         {"name": "RemoteOK",      "role": f"Remote {role}",      "match_score": 74, "apply_url": "https://remoteok.com"},
# #         {"name": "Wellfound",     "role": f"{role} at Startup",   "match_score": 70, "apply_url": "https://wellfound.com"},
# #     ]


# # # ── REGISTER ───────────────────────────────────────────────────────

# # @app.get("/register", response_class=HTMLResponse)
# # def register_page(request: Request):
# #     return templates.TemplateResponse("register.html", {
# #         "request":  request,
# #         "message":  request.session.pop("message", None),
# #         "msg_type": request.session.pop("msg_type", None)
# #     })


# # @app.post("/register")
# # def register_user(request: Request,
# #                   name: str = Form(...),
# #                   email: str = Form(...),
# #                   password: str = Form(...)):
# #     if not create_user(name, email, password):
# #         request.session["message"]  = "Email already registered"
# #         request.session["msg_type"] = "error"
# #         return RedirectResponse("/register", status_code=303)
# #     request.session["message"]  = "Registration successful! Please login"
# #     request.session["msg_type"] = "success"
# #     return RedirectResponse("/login", status_code=303)


# # # ── LOGIN / LOGOUT ─────────────────────────────────────────────────

# # @app.get("/")
# # def home():
# #     return RedirectResponse("/login")


# # @app.get("/login", response_class=HTMLResponse)
# # def login_page(request: Request):
# #     return templates.TemplateResponse("login.html", {
# #         "request":  request,
# #         "message":  request.session.pop("message", None),
# #         "msg_type": request.session.pop("msg_type", None)
# #     })


# # @app.post("/login")
# # def login_user(request: Request,
# #                email: str = Form(...),
# #                password: str = Form(...)):
# #     user = authenticate_user(email, password)
# #     if user:
# #         request.session["user"] = user
# #         return RedirectResponse("/dashboard", status_code=303)
# #     request.session["message"]  = "Invalid email or password"
# #     request.session["msg_type"] = "error"
# #     return RedirectResponse("/login", status_code=303)


# # @app.get("/logout")
# # def logout(request: Request):
# #     request.session.clear()
# #     return RedirectResponse("/login", status_code=303)


# # # ── DASHBOARD ──────────────────────────────────────────────────────

# # @app.get("/dashboard", response_class=HTMLResponse)
# # def dashboard(request: Request):
# #     if "user" not in request.session:
# #         return RedirectResponse("/login", status_code=303)
# #     return templates.TemplateResponse("dashboard.html", {
# #         "request": request,
# #         "user":    request.session["user"]
# #     })


# # # ── UPLOAD RESUME ──────────────────────────────────────────────────
# # # dashboard.html uses fetch() and reads the JSON response:
# # #   { "skills_found": [...], "best_matches": [{name, role, match_score, apply_url}] }

# # @app.post("/upload_resume")
# # def upload_resume(
# #     request: Request,
# #     file: UploadFile = File(...),
# #     email: str = Form(None),
# #     db: Session = Depends(get_db)
# # ):
# #     print("Upload route called")

# #     if "user" not in request.session:
# #         return JSONResponse({"error": "Not logged in"}, status_code=401)

# #     user = _get_current_user(request, db)
# #     if not user:
# #         return JSONResponse({"error": "User not found"}, status_code=401)

# #     # Save file
# #     os.makedirs("uploads", exist_ok=True)
# #     file_path = os.path.join("uploads", file.filename)
# #     with open(file_path, "wb") as buf:
# #         shutil.copyfileobj(file.file, buf)

# #     # Extract + parse
# #     resume_text = extract_text(file_path)
# #     parsed_data = parse_resume(resume_text)
# #     print("Parsed:", parsed_data)

# #     with open("parsed_resumes.json", "w") as f:
# #         json.dump(parsed_data, f, indent=4)

# #     # Prepare DB-safe values
# #     skills_list     = parsed_data.get("skills", []) or []
# #     experience_list = parsed_data.get("experience", []) or []
# #     summary         = parsed_data.get("summary") or ""
# #     role            = summary or ", ".join(skills_list[:5])

# #     # Save resume row
# #     resume = Resume(
# #         user_id    = user.id,
# #         file_path  = file_path,
# #         role       = role,
# #         experience = json.dumps(experience_list),   # list → JSON string for SQLite
# #         summary    = summary
# #     )
# #     db.add(resume)
# #     db.commit()
# #     db.refresh(resume)
# #     print(f"✅ Resume saved id={resume.id}")

# #     # Try real matching, fall back to placeholders
# #     best_matches = []
# #     try:
# #         from models import match_jobs_to_resume
# #         from indeed_scraper import scrape_indeed_jobs
# #         query   = skills_list[0] if skills_list else "software developer"
# #         jobs    = scrape_indeed_jobs(query)
# #         matched = match_jobs_to_resume(f"{summary} {' '.join(skills_list)}", jobs)

# #         for item in matched[:5]:
# #             job = item.get("job", {})
# #             score = round(item.get("similarity", 0) * 100)
# #             best_matches.append({
# #                 "name":        job.get("company", "Company"),
# #                 "role":        job.get("title", "Position"),
# #                 "match_score": score,
# #                 "apply_url":   job.get("url", "")
# #             })

# #             # Also persist suggestion to DB so /get_suggestions can return it
# #             already_applied = db.query(AppliedJob).filter(
# #                 AppliedJob.user_id == user.id,
# #                 AppliedJob.apply_url == job.get("url", "")
# #             ).first()

# #             if not already_applied:
# #                 suggestion = JobSuggestion(
# #                     user_id       = user.id,
# #                     title         = job.get("title", ""),
# #                     company       = job.get("company", ""),
# #                     platform      = job.get("platform", ""),
# #                     apply_url     = job.get("url", ""),
# #                     match_score   = item.get("similarity", 0),
# #                     date_suggested= datetime.utcnow()
# #                 )
# #                 db.add(suggestion)

# #         db.commit()

# #     except Exception as e:
# #         print(f"⚠️  Scraper not ready: {e}")
# #         best_matches = _placeholder_matches(skills_list)

# #         # Save placeholder suggestions so the suggestions page isn't empty
# #         _save_placeholder_suggestions(user.id, skills_list, best_matches, db)

# #     return JSONResponse({
# #         "message":      "Resume uploaded successfully",
# #         "skills_found": skills_list,
# #         "best_matches": best_matches,
# #         "parsed": {
# #             "name":             parsed_data.get("name"),
# #             "email":            parsed_data.get("email"),
# #             "experience_years": parsed_data.get("experience_years", 0),
# #             "education":        parsed_data.get("education", []),
# #         }
# #     })


# # def _save_placeholder_suggestions(user_id, skills, matches, db):
# #     """Persist placeholder suggestions to DB so suggestions page shows them."""
# #     for m in matches:
# #         exists = db.query(JobSuggestion).filter(
# #             JobSuggestion.user_id   == user_id,
# #             JobSuggestion.apply_url == m["apply_url"]
# #         ).first()
# #         if not exists:
# #             db.add(JobSuggestion(
# #                 user_id      = user_id,
# #                 title        = m["role"],
# #                 company      = m["name"],
# #                 platform     = m["name"],
# #                 apply_url    = m["apply_url"],
# #                 match_score  = m["match_score"] / 100,
# #                 date_suggested = datetime.utcnow()
# #             ))
# #     db.commit()


# # # ── GET SUGGESTIONS (called by suggestions.html fetch) ─────────────
# # # Returns JSON list of non-applied job suggestions for the logged-in user.
# # # suggestions.html reads: job.id, job.date, job.role, job.company,
# # #                         job.match_score, job.apply_url

# # @app.get("/get_suggestions")
# # def get_suggestions(request: Request, db: Session = Depends(get_db)):
# #     if "user" not in request.session:
# #         return JSONResponse([], status_code=401)

# #     user = _get_current_user(request, db)
# #     if not user:
# #         return JSONResponse([])

# #     # Get applied job URLs so we can exclude them
# #     applied_urls = {
# #         a.apply_url for a in
# #         db.query(AppliedJob).filter(AppliedJob.user_id == user.id).all()
# #     }

# #     suggestions = (
# #         db.query(JobSuggestion)
# #         .filter(
# #             JobSuggestion.user_id    == user.id,
# #             JobSuggestion.is_applied == False
# #         )
# #         .order_by(JobSuggestion.match_score.desc())
# #         .all()
# #     )

# #     result = []
# #     for s in suggestions:
# #         if s.apply_url in applied_urls:
# #             continue
# #         result.append({
# #             "id":          s.id,
# #             "role":        s.title,
# #             "company":     s.company,
# #             "platform":    s.platform,
# #             "apply_url":   s.apply_url,
# #             "match_score": round(s.match_score * 100) if s.match_score <= 1 else int(s.match_score),
# #             "date":        s.date_suggested.strftime("%d %b %Y") if s.date_suggested else ""
# #         })

# #     return JSONResponse(result)


# # # ── MARK APPLIED (called by suggestions.html "Applied ✅" button) ──
# # # Moves job from suggestions → applied_jobs table.
# # # Flags it so it never appears in suggestions again.

# # @app.post("/mark_applied/{job_id}")
# # def mark_applied(job_id: int, request: Request, db: Session = Depends(get_db)):
# #     if "user" not in request.session:
# #         return JSONResponse({"error": "Not logged in"}, status_code=401)

# #     user = _get_current_user(request, db)
# #     if not user:
# #         return JSONResponse({"error": "User not found"}, status_code=401)

# #     suggestion = db.query(JobSuggestion).filter(
# #         JobSuggestion.id      == job_id,
# #         JobSuggestion.user_id == user.id
# #     ).first()

# #     if not suggestion:
# #         return JSONResponse({"error": "Suggestion not found"}, status_code=404)

# #     # Mark suggestion as applied (so it won't show again)
# #     suggestion.is_applied = True

# #     # Save to applied_jobs table for the /applied page
# #     already = db.query(AppliedJob).filter(
# #         AppliedJob.user_id   == user.id,
# #         AppliedJob.apply_url == suggestion.apply_url
# #     ).first()

# #     if not already:
# #         db.add(AppliedJob(
# #             user_id     = user.id,
# #             title       = suggestion.title,
# #             company     = suggestion.company,
# #             platform    = suggestion.platform,
# #             apply_url   = suggestion.apply_url,
# #             match_score = suggestion.match_score,
# #             applied_at  = datetime.utcnow(),
# #             status      = "applied"
# #         ))

# #     db.commit()
# #     print(f"✅ Job {job_id} marked as applied by user {user.id}")
# #     return JSONResponse({"success": True, "job_id": job_id})


# # # ── SUGGESTIONS PAGE ───────────────────────────────────────────────

# # @app.get("/suggestions", response_class=HTMLResponse)
# # def suggestions_page(request: Request):
# #     if "user" not in request.session:
# #         return RedirectResponse("/login", status_code=303)
# #     return templates.TemplateResponse("suggestions.html", {
# #         "request": request,
# #         "user":    request.session["user"]
# #     })


# # # ── APPLIED PAGE ───────────────────────────────────────────────────

# # @app.get("/applied", response_class=HTMLResponse)
# # def applied_page(request: Request, db: Session = Depends(get_db)):
# #     if "user" not in request.session:
# #         return RedirectResponse("/login", status_code=303)

# #     user = _get_current_user(request, db)
# #     applied = []
# #     if user:
# #         rows = (
# #             db.query(AppliedJob)
# #             .filter(AppliedJob.user_id == user.id)
# #             .order_by(AppliedJob.applied_at.desc())
# #             .all()
# #         )
# #         for a in rows:
# #             applied.append({
# #                 "title":      a.title,
# #                 "company":    a.company,
# #                 "platform":   a.platform,
# #                 "apply_url":  a.apply_url,
# #                 "status":     a.status,
# #                 "applied_at": a.applied_at.strftime("%d %b %Y") if a.applied_at else ""
# #             })

# #     return templates.TemplateResponse("applied.html", {
# #         "request": request,
# #         "user":    request.session["user"],
# #         "applied": applied
# #     })


# # # ── SEND BEST MATCHES EMAIL ────────────────────────────────────────

# # @app.post("/send_best_matches")
# # async def send_best_matches(request: Request):
# #     body   = await request.json()
# #     email  = body.get("email", "")
# #     skills = body.get("skills", [])
# #     print(f"📧 Email requested → {email} | skills: {skills}")
# #     # TODO: wire in SendGrid / smtplib
# #     return JSONResponse({"sent": True})


# # # ── RECOMMEND JOBS ─────────────────────────────────────────────────

# # @app.get("/recommend_jobs", response_class=HTMLResponse)
# # def recommend_jobs(request: Request, db: Session = Depends(get_db)):
# #     if "user" not in request.session:
# #         return RedirectResponse("/login", status_code=303)

# #     user = _get_current_user(request, db)
# #     latest_resume = (
# #         db.query(Resume)
# #         .filter(Resume.user_id == user.id)
# #         .order_by(Resume.id.desc())
# #         .first()
# #     ) if user else None

# #     if not latest_resume:
# #         request.session["message"] = "Please upload resume first"
# #         return RedirectResponse("/dashboard", status_code=303)

# #     matches = []
# #     try:
# #         from models import match_jobs_to_resume
# #         from indeed_scraper import scrape_indeed_jobs
# #         jobs    = scrape_indeed_jobs("software developer")
# #         matches = match_jobs_to_resume(
# #             f"{latest_resume.summary} {latest_resume.role}", jobs
# #         ) if jobs else []
# #     except Exception as e:
# #         print(f"Scraper error: {e}")

# #     return templates.TemplateResponse("jobs.html", {
# #         "request": request,
# #         "matches": matches,
# #         "user":    request.session["user"]
# #     })



# import json
# from datetime import datetime, date
# from fastapi import FastAPI, Request, Form, UploadFile, File, Depends, status
# from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
# from fastapi.templating import Jinja2Templates
# from starlette.middleware.sessions import SessionMiddleware
# from fastapi.staticfiles import StaticFiles
# from sqlalchemy.orm import Session
# from database import create_users_table, engine, get_db
# from models import Base, User, Resume, JobSuggestion, AppliedJob
# from auth import create_user, authenticate_user
# import os
# import shutil
# from resume_extracter import extract_text
# from resume_parser import parse_resume

# Base.metadata.create_all(bind=engine)

# app = FastAPI()
# app.add_middleware(SessionMiddleware, secret_key="supersecretkey")
# app.mount("/static", StaticFiles(directory="static"), name="static")
# templates = Jinja2Templates(directory="templates")
# create_users_table()


# # ── helpers ────────────────────────────────────────────────────────

# def _get_current_user(request: Request, db: Session):
#     email = request.session.get("user")
#     if not email:
#         return None
#     return db.query(User).filter(User.email == email).first()


# def _already_applied_urls(user_id: int, db: Session) -> set:
#     """Return set of URLs this user already applied to — never show again."""
#     rows = db.query(AppliedJob).filter(AppliedJob.user_id == user_id).all()
#     return {r.apply_url for r in rows if r.apply_url}


# def _suggestions_today(user_id: int, db: Session) -> int:
#     """Count how many suggestions were saved for this user today."""
#     today_start = datetime.combine(date.today(), datetime.min.time())
#     return db.query(JobSuggestion).filter(
#         JobSuggestion.user_id       == user_id,
#         JobSuggestion.is_applied    == False,
#         JobSuggestion.date_suggested >= today_start
#     ).count()


# # ── REGISTER ───────────────────────────────────────────────────────

# @app.get("/register", response_class=HTMLResponse)
# def register_page(request: Request):
#     return templates.TemplateResponse("register.html", {
#         "request":  request,
#         "message":  request.session.pop("message", None),
#         "msg_type": request.session.pop("msg_type", None)
#     })


# @app.post("/register")
# def register_user(request: Request,
#                   name: str = Form(...),
#                   email: str = Form(...),
#                   password: str = Form(...)):
#     if not create_user(name, email, password):
#         request.session["message"]  = "Email already registered"
#         request.session["msg_type"] = "error"
#         return RedirectResponse("/register", status_code=303)
#     request.session["message"]  = "Registration successful! Please login"
#     request.session["msg_type"] = "success"
#     return RedirectResponse("/login", status_code=303)


# # ── LOGIN / LOGOUT ─────────────────────────────────────────────────

# @app.get("/")
# def home():
#     return RedirectResponse("/login")


# @app.get("/login", response_class=HTMLResponse)
# def login_page(request: Request):
#     return templates.TemplateResponse("login.html", {
#         "request":  request,
#         "message":  request.session.pop("message", None),
#         "msg_type": request.session.pop("msg_type", None)
#     })


# @app.post("/login")
# def login_user(request: Request,
#                email: str = Form(...),
#                password: str = Form(...)):
#     user = authenticate_user(email, password)
#     if user:
#         request.session["user"] = user
#         return RedirectResponse("/dashboard", status_code=303)
#     request.session["message"]  = "Invalid email or password"
#     request.session["msg_type"] = "error"
#     return RedirectResponse("/login", status_code=303)


# @app.get("/logout")
# def logout(request: Request):
#     request.session.clear()
#     return RedirectResponse("/login", status_code=303)


# # ── DASHBOARD ──────────────────────────────────────────────────────

# @app.get("/dashboard", response_class=HTMLResponse)
# def dashboard(request: Request):
#     if "user" not in request.session:
#         return RedirectResponse("/login", status_code=303)
#     return templates.TemplateResponse("dashboard.html", {
#         "request": request,
#         "user":    request.session["user"]
#     })


# # ── UPLOAD RESUME ──────────────────────────────────────────────────

# @app.post("/upload_resume")
# def upload_resume(
#     request: Request,
#     file: UploadFile = File(...),
#     email: str = Form(None),
#     db: Session = Depends(get_db)
# ):
#     print("Upload route called")

#     if "user" not in request.session:
#         return JSONResponse({"error": "Not logged in"}, status_code=401)

#     user = _get_current_user(request, db)
#     if not user:
#         return JSONResponse({"error": "User not found"}, status_code=401)

#     # Save file
#     os.makedirs("uploads", exist_ok=True)
#     file_path = os.path.join("uploads", file.filename)
#     with open(file_path, "wb") as buf:
#         shutil.copyfileobj(file.file, buf)

#     # Extract + parse
#     resume_text = extract_text(file_path)
#     parsed_data = parse_resume(resume_text)
#     print("Parsed:", parsed_data)

#     with open("parsed_resumes.json", "w") as f:
#         json.dump(parsed_data, f, indent=4)

#     # Prepare DB values
#     skills_list     = parsed_data.get("skills", []) or []
#     experience_list = parsed_data.get("experience", []) or []
#     summary         = parsed_data.get("summary") or ""
#     role            = summary or ", ".join(skills_list[:5])

#     # Save resume
#     resume = Resume(
#         user_id    = user.id,
#         file_path  = file_path,
#         role       = role,
#         experience = json.dumps(experience_list),
#         summary    = summary
#     )
#     db.add(resume)
#     db.commit()
#     db.refresh(resume)
#     print(f"✅ Resume saved id={resume.id}")

#     # ── Scrape real jobs + BERT match + save TOP 5 only ────────────
#     already_applied = _already_applied_urls(user.id, db)

#     # Build clean resume text for BERT (no JSON brackets)
#     exp_titles  = [e.get("title", "") for e in experience_list if isinstance(e, dict)]
#     resume_bert = f"{summary} {' '.join(skills_list)} {' '.join(exp_titles)}".strip()

#     best_matches = []
#     try:
#         from models import match_jobs_to_resume
#         from job_links import scrape_all_jobs

#         # Use role/skills as search query — more relevant than just first skill
#         query = " ".join(skills_list[:3]) if skills_list else "software developer"
#         print(f"🔍 Searching jobs for: '{query}'")

#         jobs = scrape_all_jobs(query, location="India")
#         print(f"📦 Total scraped: {len(jobs)}")

#         if jobs:
#             # Filter out already-applied jobs
#             jobs = [j for j in jobs if j.get("url", "") not in already_applied]

#             # BERT match — get ranked results
#             matched = match_jobs_to_resume(resume_bert, jobs)

#             # ── Save ONLY TOP 5 to DB ──────────────────────────────
#             # Delete old non-applied suggestions for this user first
#             db.query(JobSuggestion).filter(
#                 JobSuggestion.user_id    == user.id,
#                 JobSuggestion.is_applied == False
#             ).delete()
#             db.commit()

#             saved_count = 0
#             for item in matched[:5]:   # ← ONLY TOP 5
#                 job   = item.get("job", {})
#                 score = item.get("similarity", 0)
#                 url   = job.get("url", "")

#                 if not url:
#                     continue

#                 db.add(JobSuggestion(
#                     user_id        = user.id,
#                     title          = job.get("title", ""),
#                     company        = job.get("company", ""),
#                     platform       = job.get("platform", ""),
#                     apply_url      = url,           # ← REAL scraped URL
#                     match_score    = score,
#                     date_suggested = datetime.utcnow(),
#                     is_applied     = False
#                 ))
#                 saved_count += 1

#                 best_matches.append({
#                     "name":        job.get("company", ""),
#                     "role":        job.get("title", ""),
#                     "match_score": round(score * 100),
#                     "apply_url":   url              # ← REAL URL returned to frontend
#                 })

#             db.commit()
#             print(f"✅ Saved {saved_count} real job suggestions")

#     except Exception as e:
#         print(f"⚠️  Scraper/matcher error: {e}")
#         import traceback
#         traceback.print_exc()

#     return JSONResponse({
#         "message":      "Resume uploaded successfully",
#         "skills_found": skills_list,
#         "best_matches": best_matches,
#         "parsed": {
#             "name":             parsed_data.get("name"),
#             "email":            parsed_data.get("email"),
#             "experience_years": parsed_data.get("experience_years", 0),
#             "education":        parsed_data.get("education", []),
#         }
#     })


# # ── GET SUGGESTIONS ────────────────────────────────────────────────
# # Returns ONLY top 5 non-applied suggestions for today

# @app.get("/get_suggestions")
# def get_suggestions(request: Request, db: Session = Depends(get_db)):
#     if "user" not in request.session:
#         return JSONResponse([], status_code=401)

#     user = _get_current_user(request, db)
#     if not user:
#         return JSONResponse([])

#     applied_urls = _already_applied_urls(user.id, db)

#     # Get top 5 non-applied suggestions ordered by match score
#     suggestions = (
#         db.query(JobSuggestion)
#         .filter(
#             JobSuggestion.user_id    == user.id,
#             JobSuggestion.is_applied == False
#         )
#         .order_by(JobSuggestion.match_score.desc())
#         .limit(5)           # ← ONLY 5
#         .all()
#     )

#     result = []
#     for s in suggestions:
#         if s.apply_url in applied_urls:
#             continue
#         result.append({
#             "id":          s.id,
#             "role":        s.title,
#             "company":     s.company,
#             "platform":    s.platform,
#             "apply_url":   s.apply_url,     # ← real URL
#             "match_score": round(s.match_score * 100) if s.match_score <= 1 else int(s.match_score),
#             "date":        s.date_suggested.strftime("%d %b %Y") if s.date_suggested else ""
#         })

#     print(f"📋 Returning {len(result)} suggestions for user {user.id}")
#     return JSONResponse(result)


# # ── MARK APPLIED ───────────────────────────────────────────────────
# # Moves job to applied table + returns redirect URL to applied page

# @app.post("/mark_applied/{job_id}")
# def mark_applied(job_id: int, request: Request, db: Session = Depends(get_db)):
#     if "user" not in request.session:
#         return JSONResponse({"error": "Not logged in"}, status_code=401)

#     user = _get_current_user(request, db)
#     if not user:
#         return JSONResponse({"error": "User not found"}, status_code=401)

#     suggestion = db.query(JobSuggestion).filter(
#         JobSuggestion.id      == job_id,
#         JobSuggestion.user_id == user.id
#     ).first()

#     if not suggestion:
#         return JSONResponse({"error": "Not found"}, status_code=404)

#     # Mark as applied — won't show in suggestions again
#     suggestion.is_applied = True

#     # Save to applied_jobs table
#     already = db.query(AppliedJob).filter(
#         AppliedJob.user_id   == user.id,
#         AppliedJob.apply_url == suggestion.apply_url
#     ).first()

#     if not already:
#         db.add(AppliedJob(
#             user_id     = user.id,
#             title       = suggestion.title,
#             company     = suggestion.company,
#             platform    = suggestion.platform,
#             apply_url   = suggestion.apply_url,
#             match_score = suggestion.match_score,
#             applied_at  = datetime.utcnow(),
#             status      = "applied"
#         ))

#     db.commit()
#     print(f"✅ Job {job_id} marked applied by user {user.id}")

#     # ← return redirect to /applied page
#     return JSONResponse({
#         "success":      True,
#         "job_id":       job_id,
#         "redirect_url": "/applied"      # frontend will redirect here
#     })


# # ── SUGGESTIONS PAGE ───────────────────────────────────────────────

# @app.get("/suggestions", response_class=HTMLResponse)
# def suggestions_page(request: Request):
#     if "user" not in request.session:
#         return RedirectResponse("/login", status_code=303)
#     return templates.TemplateResponse("suggestions.html", {
#         "request": request,
#         "user":    request.session["user"]
#     })


# # ── APPLIED PAGE ───────────────────────────────────────────────────

# @app.get("/applied", response_class=HTMLResponse)
# def applied_page(request: Request, db: Session = Depends(get_db)):
#     if "user" not in request.session:
#         return RedirectResponse("/login", status_code=303)

#     user    = _get_current_user(request, db)
#     applied = []

#     if user:
#         rows = (
#             db.query(AppliedJob)
#             .filter(AppliedJob.user_id == user.id)
#             .order_by(AppliedJob.applied_at.desc())
#             .all()
#         )
#         for a in rows:
#             applied.append({
#                 "title":      a.title,
#                 "company":    a.company,
#                 "platform":   a.platform,
#                 "apply_url":  a.apply_url,
#                 "status":     a.status,
#                 "applied_at": a.applied_at.strftime("%d %b %Y") if a.applied_at else "",
#                 "match_score": a.match_score
#             })

#     return templates.TemplateResponse("applied.html", {
#         "request": request,
#         "user":    request.session["user"],
#         "applied": applied
#     })


# # ── SEND EMAIL ─────────────────────────────────────────────────────

# @app.post("/send_best_matches")
# async def send_best_matches(request: Request):
#     body   = await request.json()
#     email  = body.get("email", "")
#     skills = body.get("skills", [])
#     print(f"📧 Email requested → {email}")
#     # TODO: wire SendGrid
#     return JSONResponse({"sent": True})