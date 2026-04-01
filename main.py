# main.py
"""
FastAPI application — fully converted to pure sqlite3.
No SQLAlchemy Session or Depends(get_db) anywhere.
All DB calls go through models.py helper functions.
"""


from datetime import datetime
from utils import is_strong_password
from fastapi import FastAPI, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from job_links import generate_redirect_links
from database import create_users_table
from auth import create_user, authenticate_user
from resume_extracter import extract_text
from resume_parser import parse_resume
from job_links import generate_redirect_links
from scheduler import start_scheduler, stop_scheduler
import models
from database import get_connection
import os, json


# ═══════════════════════════════════════════════════════════════════
# APP SETUP
# ═══════════════════════════════════════════════════════════════════

app = FastAPI()

app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SECRET_KEY", "change-this-in-production")
)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

create_users_table()   # creates all tables on every startup — safe, uses IF NOT EXISTS


# ── Start scheduler on startup, stop cleanly on shutdown ──────────
@app.on_event("startup")
async def startup_event():
    start_scheduler()

@app.on_event("shutdown")
async def shutdown_event():
    stop_scheduler()


# ═══════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════

def _current_user(request: Request) -> dict:
    """Return user dict from session email. Returns {} if not logged in."""
    email = request.session.get("user")
    if not email:
        return {}
    return models.get_user_by_email(email) or {}


def _require_login(request: Request):
    """Return user dict or None. Routes redirect to /login if None."""
    user = _current_user(request)
    return user if user else None


# ═══════════════════════════════════════════════════════════════════
# REGISTER
# ═══════════════════════════════════════════════════════════════════

@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    return templates.TemplateResponse("register.html", {
        "request":  request,
        "message":  request.session.pop("message",  None),
        "msg_type": request.session.pop("msg_type", None),
    })




from fastapi import Request, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import models

templates = Jinja2Templates(directory="templates")

@app.post("/register", response_class=HTMLResponse)
async def register(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
):
    # Check duplicate email
    if models.user_exists(email):
        return templates.TemplateResponse("register.html", {
            "request": request,
            "message": "Email already exists",
            "msg_type": "error"
        })

    # Password validation
    valid, msg = is_strong_password(password)
    if not valid:
        return templates.TemplateResponse("register.html", {
            "request": request,
            "message": msg,
            "msg_type": "error"
        })

    # Create user
    models.create_user(email, password, name)

    return templates.TemplateResponse("login.html", {
        "request": request,
        "message": "Registration successful! Please login.",
        "msg_type": "success"
    })


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
        "message":  request.session.pop("message",  None),
        "msg_type": request.session.pop("msg_type", None),
    })


@app.post("/login")
def login_user(
    request:  Request,
    email:    str = Form(...),
    password: str = Form(...),
):
    user_email = authenticate_user(email, password)
    if user_email:
        request.session["user"] = user_email
        return RedirectResponse("/dashboard", status_code=303)

    request.session["message"]  = "Invalid email or password"
    request.session["msg_type"] = "error"
    return RedirectResponse("/login", status_code=303)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


# ═══════════════════════════════════════════════════════════════════
# DASHBOARD
# ═══════════════════════════════════════════════════════════════════

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    if "user" not in request.session:
        return RedirectResponse("/login", status_code=303)

    user = _require_login(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    resume     = models.get_latest_resume(user["id"])
    has_resume = bool(resume and (resume.get("role") or resume.get("summary")))
    resume_data = None

    if has_resume:
        skills = []
        try:
            skills = json.loads(resume.get("experience") or "[]")
            if not isinstance(skills, list):
                skills = []
        except Exception:
            skills = []

        # Load richer parsed data from cache file if it exists
        parsed_file = f"parsed_resumes_{user['id']}.json"
        if os.path.exists(parsed_file):
            with open(parsed_file) as f:
                saved  = json.load(f)
                skills = saved.get("skills", skills)

        resume_data = {
            "name":        user.get("username", ""),
            "role":        resume.get("role",    "Professional"),
            "summary":     resume.get("summary", ""),
            "skills":      skills[:10],
            "uploaded_at": (resume.get("created_at") or "")[:10],
        }

    return templates.TemplateResponse("dashboard.html", {
        "request":    request,
        "user":       request.session["user"],
        "has_resume": has_resume,
        "resume":     resume_data,
        "message":    request.session.pop("message",  None),
        "msg_type":   request.session.pop("msg_type", None),
    })


# ═══════════════════════════════════════════════════════════════════
# UPLOAD RESUME
# ═══════════════════════════════════════════════════════════════════



@app.post("/upload_resume")
async def upload_resume(
    request: Request,
    file: UploadFile = File(...),
    label: str = Form("")
):
    # ── Check login ──
    user = _require_login(request)
    if not user:
        return JSONResponse({"error": "Not logged in"}, status_code=401)

    # ── Step 1: Save file ──
    os.makedirs("uploads", exist_ok=True)
    file_path = f"uploads/{file.filename}"

    with open(file_path, "wb") as f:
        f.write(await file.read())

    print("🔄 Processing resume...")

    # ── Step 2: Extract + Parse ──
    text = extract_text(file_path)
    parsed_data = parse_resume(text)

    # ── Step 3: Extract fields ──
    skills = parsed_data.get("skills", [])
    summary = parsed_data.get("summary", "")
    experience_years = float(parsed_data.get("experience_years", 0))

    education = parsed_data.get("education", [])
    highest_edu = education[0] if education else {}

    highest_degree = highest_edu.get("degree", "") or parsed_data.get("highest_degree", "")
    institution = highest_edu.get("institution", "") or parsed_data.get("institution", "")
    graduation_year = highest_edu.get("year", "") or parsed_data.get("graduation_year", "")

    name = parsed_data.get("name", "") or user.get("username", "")
    phone = parsed_data.get("phone", "")
    location = parsed_data.get("location", "")

    print(f"✅ Skills   : {skills}")
    print(f"✅ Degree   : {highest_degree}")
    print(f"✅ Exp years: {experience_years}")

    # ── Step 4: Save Resume ──
    models.deactivate_all_resumes(user["id"])

    resume_id = models.insert_resume(user["id"], {
        "file_path": file_path,
        "label": label or file.filename,
        "role": summary[:100],
        "summary": summary,
        "experience": json.dumps(skills),
        "highest_degree": highest_degree,
        "institution": institution,
        "graduation_year": graduation_year,
        "experience_years": experience_years,
    })

    # models.link_skills_to_resume(resume_id, skills)

    # ── Step 5: Update Profile ──
    profile = models.get_or_create_profile(user["id"])

    updates = {
        "skills": json.dumps(skills),
        "experience_years": experience_years,
        "active_resume_id": resume_id,
    }

    if not profile.get("highest_degree") and highest_degree:
        updates["highest_degree"] = highest_degree

    if not profile.get("institution") and institution:
        updates["institution"] = institution

    if not profile.get("graduation_year") and graduation_year:
        updates["graduation_year"] = graduation_year

    if not profile.get("phone") and phone:
        updates["phone"] = phone

    if not profile.get("location") and location:
        updates["location"] = location

    models.update_profile(user["id"], updates)

    # Update username if needed
    if name and name != user.get("username"):
        models.update_username(user["id"], name)

    # ── Step 6: Save parsed cache ──
    parsed_file = f"parsed_resumes_{user['id']}_{resume_id}.json"
    with open(parsed_file, "w") as f:
        json.dump(parsed_data, f)

    # # ── Step 7: Build profile for matching ──
    profile = models.get_or_create_profile(user["id"])

    full_profile = {
        "skills": json.loads(profile.get("skills") or "[]"),
        "experience_years": profile.get("experience_years", 0),
        "expected_roles": json.loads(profile.get("expected_roles") or "[]"),
        "preferred_location": profile.get("preferred_location", ""),
        "job_type": profile.get("job_type", ""),
    }

    # ── Step 8: Job Matching ──
    from company_matcher import get_best_matching_companies_from_profile

    raw_jobs = get_best_matching_companies_from_profile(full_profile, limit=100)
    best_matches = models.match_jobs_to_resume(text, raw_jobs, threshold=0.2)

    if not best_matches:
        best_matches = raw_jobs[:50]

    links = generate_redirect_links(" ".join(skills[:2]) if skills else "developer")

    # ── Step 9: Save Suggestions ──
    models.delete_unapplied_suggestions(user["id"])
    models.insert_job_suggestions(user["id"], best_matches)

    print(f"💾 Resume #{resume_id} saved with {len(best_matches)} jobs")

    # ── Step 10: Response ──
    return {
        "success": True,
        "resume_id": resume_id,
        "skills": skills,
        "jobs": best_matches,
        "links": links,
        "profile": {
            "name": name,
            "phone": phone,
            "location": location,
            "experience_years": experience_years,
            "highest_degree": highest_degree,
            "institution": institution,
            "graduation_year": graduation_year,
        }
    }


# ═══════════════════════════════════════════════════════════════════
# DELETE RESUME
# ═══════════════════════════════════════════════════════════════════

@app.post("/delete_resume")
def delete_resume(request: Request):
    user = _require_login(request)
    if not user:
        return JSONResponse({"error": "Not logged in"}, status_code=401)

    models.delete_all_resumes(user["id"])


    parsed_file = f"parsed_resumes_{user['id']}.json"
    if os.path.exists(parsed_file):
        os.remove(parsed_file)

    print(f"🗑️  Resume deleted for user {user['id']}")
    return JSONResponse({"success": True, "message": "Resume deleted. You can upload a new one."})


# ═══════════════════════════════════════════════════════════════════
# GET SUGGESTIONS
# ═══════════════════════════════════════════════════════════════════

@app.get("/get_suggestions")
def get_suggestions(request: Request):
    user = _require_login(request)
    if not user:
        return JSONResponse([], status_code=401)

    applied_urls = models.get_applied_urls(user["id"])
    suggestions  = models.get_suggestions(user["id"])

    result = []
    for s in suggestions:
        if s.get("apply_url") in applied_urls:
            continue
        score     = s.get("match_score", 0)
        score_pct = round(score * 100) if score <= 1 else int(score)
        result.append({
            "id":          s["id"],
            "role":        s.get("title",    ""),
            "company":     s.get("company",  ""),
            "platform":    s.get("platform", ""),
            "apply_url":   s.get("apply_url",""),
            "match_score": score_pct,
            "match_label": (
                "🟢 Strong Match" if score_pct >= 60 else
                "🟡 Good Match"   if score_pct >= 30 else
                "🔴 Partial Match"
            ),
            "date": (s.get("date_suggested") or "")[:10],
        })

    print(f"📋 Returning {len(result)} suggestions for user {user['id']}")
    return JSONResponse(result)


# ═══════════════════════════════════════════════════════════════════
# MARK APPLIED
# ═══════════════════════════════════════════════════════════════════

@app.post("/mark_applied/{job_id}")
def mark_applied(job_id: int, request: Request):
    user = _require_login(request)
    if not user:
        return JSONResponse({"error": "Not logged in"}, status_code=401)

    suggestion = models.get_suggestion_by_id(job_id, user["id"])
    if not suggestion:
        return JSONResponse({"error": "Not found"}, status_code=404)

    models.mark_suggestion_applied(job_id, user["id"])

    if not models.already_applied(user["id"], suggestion["apply_url"]):
        models.insert_applied_job(user["id"], suggestion)

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
        "user":    request.session["user"],
    })


# ═══════════════════════════════════════════════════════════════════
# APPLIED PAGE
# ═══════════════════════════════════════════════════════════════════

@app.get("/applied", response_class=HTMLResponse)
def applied_page(request: Request):
    if "user" not in request.session:
        return RedirectResponse("/login", status_code=303)

    user    = _require_login(request)
    applied = []

    if user:
        for a in models.get_applied_jobs(user["id"]):
            score = a.get("match_score", 0)
            applied.append({
                "title":       a.get("title",     ""),
                "company":     a.get("company",   ""),
                "platform":    a.get("platform",  ""),
                "apply_url":   a.get("apply_url", ""),
                "status":      a.get("status",    "applied"),
                "applied_at":  (a.get("applied_at") or "")[:10],
                "match_score": round(score * 100) if score <= 1 else int(score),
            })

    return templates.TemplateResponse("applied.html", {
        "request": request,
        "user":    request.session["user"],
        "applied": applied,
    })


@app.get("/get_applied")
def get_applied(request: Request):
    user = _require_login(request)
    if not user:
        return JSONResponse([], status_code=401)

    result = []
    for a in models.get_applied_jobs(user["id"]):
        score = a.get("match_score", 0)
        result.append({
            "role":         a.get("title",    ""),
            "company":      a.get("company",  ""),
            "platform":     a.get("platform", ""),
            "apply_url":    a.get("apply_url",""),
            "status":       a.get("status",   "applied"),
            "applied_date": (a.get("applied_at") or "")[:10],
            "match_score":  round(score * 100) if score <= 1 else int(score),
        })
    return JSONResponse(result)


# ═══════════════════════════════════════════════════════════════════
# PROFILE PAGE
# ═══════════════════════════════════════════════════════════════════

@app.get("/profile", response_class=HTMLResponse)
def profile_page(request: Request):
    if "user" not in request.session:
        return RedirectResponse("/login", status_code=303)

    user = _require_login(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    profile = models.get_or_create_profile(user["id"])
    resumes = models.get_all_resumes(user["id"])

    skills = []
    try:
        skills = json.loads(profile.get("skills") or "[]")
    except Exception:
        pass

    expected_roles = []
    try:
        expected_roles = json.loads(profile.get("expected_roles") or "[]")
    except Exception:
        pass

    resume_list = []
    for r in resumes:
        resume_skills = []
        try:
            resume_skills = json.loads(r.get("experience") or "[]")
        except Exception:
            pass
        resume_list.append({
            "id":          r["id"],
            "label":       r.get("label") or f"Resume {r['id']}",
            "role":        r.get("role",             ""),
            "skills":      resume_skills[:5],
            "is_active":   r.get("is_active",        0),
            "exp_years":   r.get("experience_years", 0),
            "degree":      r.get("highest_degree",   ""),
            "institution": r.get("institution",      ""),
            "uploaded_at": (r.get("created_at") or "")[:10],
        })

    return templates.TemplateResponse("profile.html", {
        "request":        request,
        "user":           user,
        "profile":        profile,
        "skills":         skills,
        "expected_roles": expected_roles,
        "resumes":        resume_list,
        "message":        request.session.pop("message",  None),
        "msg_type":       request.session.pop("msg_type", None),
    })


# ───────────────────────────────────────────────────────────────────
# POST /profile/update — save basic info + preferences
# ───────────────────────────────────────────────────────────────────

@app.post("/profile/update")
async def update_profile(
    request:            Request,
    name:               str   = Form(...),
    phone:              str   = Form(""),
    location:           str   = Form(""),
    experience_years:   float = Form(0.0),
    preferred_location: str   = Form(""),
    salary_range:       str   = Form(""),
    job_type:           str   = Form(""),
    highest_degree:     str   = Form(""),
    institution:        str   = Form(""),
    graduation_year:    str   = Form(""),
):
    user = _require_login(request)
    if not user:
        return JSONResponse({"error": "Not logged in"}, status_code=401)

    models.update_username(user["id"], name)
    models.update_profile(user["id"], {
        "phone":              phone,
        "location":           location,
        "experience_years":   experience_years,
        "preferred_location": preferred_location,
        "salary_range":       salary_range,
        "job_type":           job_type,
        "highest_degree":     highest_degree,
        "institution":        institution,
        "graduation_year":    graduation_year,
    })

    request.session["message"]  = "Profile updated successfully!"
    request.session["msg_type"] = "success"
    return RedirectResponse("/profile", status_code=303)


# ───────────────────────────────────────────────────────────────────
# POST /profile/update_roles
# ───────────────────────────────────────────────────────────────────

@app.post("/profile/update_roles")
async def update_roles(request: Request):
    user = _require_login(request)
    if not user:
        return JSONResponse({"error": "Not logged in"}, status_code=401)
    try:
        body  = await request.json()
        roles = body.get("roles", [])
    except Exception:
        return JSONResponse({"error": "Bad request"}, status_code=400)

    models.update_profile(user["id"], {"expected_roles": json.dumps(roles)})
    return JSONResponse({"success": True, "roles": roles})


# ───────────────────────────────────────────────────────────────────
# POST /profile/update_skills
# ───────────────────────────────────────────────────────────────────

@app.post("/profile/update_skills")
async def update_skills(request: Request):
    user = _require_login(request)
    if not user:
        return JSONResponse({"error": "Not logged in"}, status_code=401)
    try:
        body   = await request.json()
        skills = body.get("skills", [])
    except Exception:
        return JSONResponse({"error": "Bad request"}, status_code=400)

    skills = sorted(set(s.strip() for s in skills if s.strip()))
    models.update_profile(user["id"], {"skills": json.dumps(skills)})
    return JSONResponse({"success": True, "skills": skills})


# ───────────────────────────────────────────────────────────────────
# POST /profile/upload_pic
# ───────────────────────────────────────────────────────────────────

@app.post("/profile/upload_pic")
async def upload_profile_pic(request: Request, file: UploadFile = File(...)):
    user = _require_login(request)
    if not user:
        return JSONResponse({"error": "Not logged in"}, status_code=401)

    os.makedirs("static/profile_pics", exist_ok=True)
    ext      = file.filename.split(".")[-1]
    pic_path = f"static/profile_pics/user_{user['id']}.{ext}"

    with open(pic_path, "wb") as f:
        f.write(await file.read())

    models.update_profile(user["id"], {"profile_pic": f"/{pic_path}"})
    return JSONResponse({"success": True, "pic_url": f"/{pic_path}"})


# ───────────────────────────────────────────────────────────────────
# POST /profile/set_active_resume/{resume_id}
# ───────────────────────────────────────────────────────────────────

@app.post("/profile/set_active_resume/{resume_id}")
def set_active_resume(resume_id: int, request: Request):
    user = _require_login(request)
    if not user:
        return JSONResponse({"error": "Not logged in"}, status_code=401)

    resume = models.get_resume_by_id(resume_id, user["id"])
    if not resume:
        return JSONResponse({"error": "Resume not found"}, status_code=404)

    models.set_active_resume(resume_id, user["id"])

    # Sync profile fields from the newly activated resume
    profile_updates = {
        "active_resume_id": resume_id,
        "experience_years": resume.get("experience_years", 0),
    }
    try:
        skills = json.loads(resume.get("experience") or "[]")
        profile_updates["skills"] = json.dumps(skills)
    except Exception:
        pass
    for field in ("highest_degree", "institution", "graduation_year"):
        if resume.get(field):
            profile_updates[field] = resume[field]

    models.update_profile(user["id"], profile_updates)
    return JSONResponse({"success": True, "active_resume_id": resume_id})


# ───────────────────────────────────────────────────────────────────
# POST /profile/delete_resume/{resume_id}
# ───────────────────────────────────────────────────────────────────

@app.post("/profile/delete_resume/{resume_id}")
def delete_single_resume(resume_id: int, request: Request):
    user = _require_login(request)
    if not user:
        return JSONResponse({"error": "Not logged in"}, status_code=401)

    resume = models.get_resume_by_id(resume_id, user["id"])
    if not resume:
        return JSONResponse({"error": "Resume not found"}, status_code=404)

    if resume.get("file_path") and os.path.exists(resume["file_path"]):
        os.remove(resume["file_path"])

    parsed_file = f"parsed_resumes_{user['id']}_{resume_id}.json"
    if os.path.exists(parsed_file):
        os.remove(parsed_file)

    models.delete_resume(resume_id, user["id"])
    return JSONResponse({"success": True, "deleted_id": resume_id})


# ───────────────────────────────────────────────────────────────────
# POST /profile/rename_resume/{resume_id}
# ───────────────────────────────────────────────────────────────────

@app.post("/profile/rename_resume/{resume_id}")
async def rename_resume(resume_id: int, request: Request):
    user = _require_login(request)
    if not user:
        return JSONResponse({"error": "Not logged in"}, status_code=401)

    body  = await request.json()
    label = body.get("label", f"Resume {resume_id}")
    models.rename_resume(resume_id, user["id"], label)
    return JSONResponse({"success": True, "label": label})


# ═══════════════════════════════════════════════════════════════════
# SEND EMAIL
# ═══════════════════════════════════════════════════════════════════

@app.post("/send_best_matches")
async def send_best_matches(request: Request):
    from email_notifier import send_best_jobs_email

    user = _require_login(request)
    if not user:
        return JSONResponse({"error": "Not logged in"}, status_code=401)

    suggestions = models.get_suggestions(user["id"])
    top_jobs    = suggestions[:10]

    sent = send_best_jobs_email(user.get("email", ""), top_jobs)
    return JSONResponse({"sent": sent})


# ═══════════════════════════════════════════════════════════════════
# REMATCH RESUME — called when user clicks "Set Active" in profile
# Re-runs full job matching using the already-parsed resume file
# ═══════════════════════════════════════════════════════════════════

@app.post("/rematch_resume/{resume_id}")
async def rematch_resume(resume_id: int, request: Request):
    user = _require_login(request)
    if not user:
        return JSONResponse({"error": "Not logged in"}, status_code=401)

    # Get the resume record
    resume = models.get_resume_by_id(resume_id, user["id"])
    if not resume:
        return JSONResponse({"error": "Resume not found"}, status_code=404)

    # Re-extract text from the saved file
    file_path = resume.get("file_path", "")
    if not file_path or not os.path.exists(file_path):
        return JSONResponse({"error": "Resume file not found on disk", "jobs_count": 0}, status_code=404)

    text = extract_text(file_path)
    if not text:
        return JSONResponse({"error": "Could not extract text", "jobs_count": 0}, status_code=400)

    # Build full profile for matching
    profile = models.get_or_create_profile(user["id"])
    full_profile = {
        "skills":             json.loads(profile.get("skills") or "[]"),
        "experience_years":   profile.get("experience_years", 0),
        "expected_roles":     json.loads(profile.get("expected_roles") or "[]"),
        "preferred_location": profile.get("preferred_location", ""),
        "job_type":           profile.get("job_type", ""),
    }

    # Fetch jobs + BERT match
    from company_matcher import get_best_matching_companies_from_profile
    raw_jobs     = get_best_matching_companies_from_profile(full_profile, limit=100)
    best_matches = models.match_jobs_to_resume(text, raw_jobs, threshold=0.2)
    if not best_matches:
        best_matches = raw_jobs[:50]

    # Replace old suggestions with new ones
    models.delete_unapplied_suggestions(user["id"])
    models.insert_job_suggestions(user["id"], best_matches)

    print(f"🔄 Rematched resume #{resume_id} → {len(best_matches)} suggestions for user {user['id']}")
    return JSONResponse({"success": True, "jobs_count": len(best_matches)})





# ═══════════════════════════════════════════════════════════════════
# QUICK JOB LINKS
# ═══════════════════════════════════════════════════════════════════

@app.get("/scheduler-status")
def scheduler_status(request: Request):
    from scheduler import _scheduler
    import models

    user = _require_login(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    # Get scheduler info
    job        = _scheduler.get_job("hourly_refresh") if _scheduler else None
    next_run   = str(job.next_run_time)[:19]           if job else "Not running"
    is_running = _scheduler.running                     if _scheduler else False

    # Get suggestion counts per user
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT
                u.id,
                u.email,
                COUNT(CASE WHEN js.is_applied = 0 THEN 1 END) AS pending,
                COUNT(CASE WHEN js.is_applied = 1 THEN 1 END) AS applied,
                MAX(js.date_suggested)                         AS last_updated
            FROM users u
            LEFT JOIN job_suggestions js ON js.user_id = u.id
            GROUP BY u.id
        """).fetchall()
        users_data = [dict(r) for r in rows]

        # Get last 5 suggestion timestamps for current user
        recent = conn.execute("""
            SELECT title, company, platform, match_score, date_suggested
            FROM job_suggestions
            WHERE user_id = ? AND is_applied = 0
            ORDER BY date_suggested DESC
            LIMIT 5
        """, (user["id"],)).fetchall()
        recent_jobs = [dict(r) for r in recent]
    finally:
        conn.close()

    return {
        "scheduler_running": is_running,
        "next_run":          next_run,
        "users":             users_data,
        "your_recent_suggestions": recent_jobs,
        "checked_at":        datetime.now().strftime("%d %b %Y %H:%M:%S")
    }


@app.get("/quick-job-links")
def quick_job_links(query: str, location: str = "India"):
    return generate_redirect_links(query, location)