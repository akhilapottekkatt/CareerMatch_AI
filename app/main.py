# main.py
"""
FastAPI application — fully converted to pure sqlite3.
No SQLAlchemy Session or Depends(get_db) anywhere.
All DB calls go through models.py helper functions.
"""

from datetime import datetime
from fastapi import FastAPI, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.database import create_users_table, sync_admins_from_env
from app.auth import (
    authenticate_user,
    create_password_reset_token,
    delete_pending_reset_tokens_for_user,
    reset_password_with_token,
    validate_password_reset_token,
)
from app.email_notifier import send_password_reset_email
from app.resume_extracter import extract_text
from app.resume_parser import parse_resume
from app.job_links import generate_redirect_links
from app.scheduler import start_scheduler, stop_scheduler
from app import models
from app.database import get_connection
import os, json

# ═══════════════════════════════════════════════════════════════════
# APP SETUP
# ═══════════════════════════════════════════════════════════════════

app = FastAPI()

app.add_middleware(
    SessionMiddleware, secret_key=os.getenv("SECRET_KEY", "change-this-in-production")
)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

create_users_table()  # creates all tables on every startup — safe, uses IF NOT EXISTS
sync_admins_from_env()  # ADMIN_EMAILS / ADMIN_EMAIL → grant is_admin


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


def _template_ctx(request: Request, **kwargs):
    """Merge Jinja context with is_admin for nav (base.html)."""
    u = _current_user(request)
    base = {
        "request": request,
        "is_admin": bool(int(u.get("is_admin") or 0)) if u else False,
    }
    base.update(kwargs)
    return base


def _require_admin(request: Request):
    """Logged-in user with is_admin=1, else None."""
    user = _require_login(request)
    if not user:
        return None
    if not int(user.get("is_admin") or 0):
        return None
    return user


def _ensure_admin(request: Request):
    """
    Returns (admin_user_dict, None) or (None, RedirectResponse).
    Use: admin, redir = _ensure_admin(request); if redir: return redir
    """
    user = _require_login(request)
    if not user:
        return None, RedirectResponse("/login", status_code=303)
    if not int(user.get("is_admin") or 0):
        request.session["message"] = "You do not have access to the admin area."
        request.session["msg_type"] = "error"
        return None, RedirectResponse("/dashboard", status_code=303)
    return user, None


# ═══════════════════════════════════════════════════════════════════
# REGISTER
# ═══════════════════════════════════════════════════════════════════


@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    return templates.TemplateResponse(
        "register.html",
        _template_ctx(
            request,
            message=request.session.pop("message", None),
            msg_type=request.session.pop("msg_type", None),
            active_nav=None,
        ),
    )


@app.post("/register", response_class=HTMLResponse)
async def register(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    repeat_password: str = Form(...),
):
    if password != repeat_password:
        return templates.TemplateResponse(
            "register.html",
            _template_ctx(
                request,
                message="Passwords do not match",
                msg_type="error",
                active_nav=None,
            ),
        )

    # Check duplicate email
    if models.user_exists(email):
        return templates.TemplateResponse(
            "register.html",
            _template_ctx(
                request,
                message="Email already exists",
                msg_type="error",
                active_nav=None,
            ),
        )

    # Create user
    models.create_user(email, password, name)

    return templates.TemplateResponse(
        "login.html",
        _template_ctx(
            request,
            message="Registration successful! Please login.",
            msg_type="success",
            active_nav=None,
        ),
    )


# ═══════════════════════════════════════════════════════════════════
# LOGIN / LOGOUT
# ═══════════════════════════════════════════════════════════════════


@app.get("/")
def home():
    return RedirectResponse("/login")


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(
        "login.html",
        _template_ctx(
            request,
            message=request.session.pop("message", None),
            msg_type=request.session.pop("msg_type", None),
            active_nav=None,
        ),
    )


@app.post("/login")
def login_user(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
):
    user_email = authenticate_user(email, password)
    if user_email:
        request.session["user"] = user_email
        return RedirectResponse("/dashboard", status_code=303)

    request.session["message"] = "Invalid email or password"
    request.session["msg_type"] = "error"
    return RedirectResponse("/login", status_code=303)


@app.get("/forgot-password", response_class=HTMLResponse)
def forgot_password_page(request: Request):
    return templates.TemplateResponse(
        "forgot_password.html",
        _template_ctx(
            request,
            message=request.session.pop("message", None),
            msg_type=request.session.pop("msg_type", None),
            active_nav=None,
        ),
    )


@app.post("/forgot-password")
def forgot_password_submit(request: Request, email: str = Form(...)):
    token, user_id, delivery_email = create_password_reset_token(email)
    if token and user_id and delivery_email:
        base = (os.getenv("APP_BASE_URL") or str(request.base_url).rstrip("/")).rstrip(
            "/"
        )
        reset_url = f"{base}/reset-password?token={token}"
        sent = send_password_reset_email(delivery_email, reset_url)
        if not sent:
            delete_pending_reset_tokens_for_user(user_id)
            request.session["message"] = (
                "We could not send the reset email right now. "
                "Check SMTP settings or try again later."
            )
            request.session["msg_type"] = "error"
            return RedirectResponse("/forgot-password", status_code=303)
    request.session["message"] = (
        "If an account exists for that email, you will receive a password reset link shortly."
    )
    request.session["msg_type"] = "success"
    return RedirectResponse("/login", status_code=303)


@app.get("/reset-password", response_class=HTMLResponse)
def reset_password_page(request: Request, token: str = ""):
    if not token:
        request.session["message"] = "Reset link is invalid or incomplete."
        request.session["msg_type"] = "error"
        return RedirectResponse("/forgot-password", status_code=303)
    if not validate_password_reset_token(token):
        return templates.TemplateResponse(
            "reset_password.html",
            _template_ctx(
                request,
                token="",
                invalid_link=True,
                active_nav=None,
            ),
        )
    return templates.TemplateResponse(
        "reset_password.html",
        _template_ctx(
            request,
            token=token,
            invalid_link=False,
            active_nav=None,
        ),
    )


@app.post("/reset-password")
def reset_password_submit(
    request: Request,
    token: str = Form(...),
    password: str = Form(...),
    repeat_password: str = Form(...),
):
    if not validate_password_reset_token(token):
        request.session["message"] = "This reset link is invalid or has expired."
        request.session["msg_type"] = "error"
        return RedirectResponse("/forgot-password", status_code=303)
    if password != repeat_password:
        return templates.TemplateResponse(
            "reset_password.html",
            _template_ctx(
                request,
                token=token,
                invalid_link=False,
                message="Passwords do not match.",
                msg_type="error",
                active_nav=None,
            ),
        )
    if len(password) < 8:
        return templates.TemplateResponse(
            "reset_password.html",
            _template_ctx(
                request,
                token=token,
                invalid_link=False,
                message="Password must be at least 8 characters.",
                msg_type="error",
                active_nav=None,
            ),
        )
    if reset_password_with_token(token, password):
        request.session["message"] = "Your password was updated. You can sign in now."
        request.session["msg_type"] = "success"
        return RedirectResponse("/login", status_code=303)
    request.session["message"] = "Could not reset password. Please request a new link."
    request.session["msg_type"] = "error"
    return RedirectResponse("/forgot-password", status_code=303)


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

    resume = models.get_latest_resume(user["id"])
    # Only treat as "complete" when user confirmed parsed data (job matching ran)
    confirmed = resume and int(resume.get("profile_confirmed", 1) or 0) == 1
    has_resume = bool(
        confirmed and resume and (resume.get("role") or resume.get("summary"))
    )
    resume_data = None

    pending_resume_json = None
    pend = models.get_pending_resume(user["id"])
    if pend:
        pfile = f"parsed_resumes_{user['id']}_{pend['id']}.json"
        if os.path.exists(pfile):
            with open(pfile) as f:
                pending_resume_json = json.load(f)
            pending_resume_json["resume_id"] = pend["id"]

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
                saved = json.load(f)
                skills = saved.get("skills", skills)

        resume_data = {
            "name": user.get("name", ""),
            "role": resume.get("role", "Professional"),
            "summary": resume.get("summary", ""),
            "skills": skills[:10],
            "uploaded_at": (resume.get("created_at") or "")[:10],
        }

    return templates.TemplateResponse(
        "dashboard.html",
        _template_ctx(
            request,
            user=request.session["user"],
            has_resume=has_resume,
            resume=resume_data,
            pending_resume_json=pending_resume_json,
            message=request.session.pop("message", None),
            msg_type=request.session.pop("msg_type", None),
            active_nav="dashboard",
        ),
    )


# ═══════════════════════════════════════════════════════════════════
# UPLOAD RESUME
# ═══════════════════════════════════════════════════════════════════


@app.post("/upload_resume")
async def upload_resume(
    request: Request, file: UploadFile = File(...), label: str = Form("")
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

    highest_degree = highest_edu.get("degree", "") or parsed_data.get(
        "highest_degree", ""
    )
    institution = highest_edu.get("institution", "") or parsed_data.get(
        "institution", ""
    )
    graduation_year = highest_edu.get("year", "") or parsed_data.get(
        "graduation_year", ""
    )

    name = parsed_data.get("name", "") or user.get("name", "")
    phone = parsed_data.get("phone", "")
    location = parsed_data.get("location", "")

    print(f"✅ Skills   : {skills}")
    print(f"✅ Degree   : {highest_degree}")
    print(f"✅ Exp years: {experience_years}")

    # ── Step 4: Save resume row (pending confirmation — no profile update / no matching yet) ──
    models.deactivate_all_resumes(user["id"])

    resume_id = models.insert_resume(
        user["id"],
        {
            "file_path": file_path,
            "label": label or file.filename,
            "role": summary[:100] if summary else "",
            "summary": summary,
            "experience": json.dumps(skills),
            "highest_degree": highest_degree,
            "institution": institution,
            "graduation_year": graduation_year,
            "experience_years": experience_years,
            "profile_confirmed": 0,
        },
    )

    parsed_file = f"parsed_resumes_{user['id']}_{resume_id}.json"
    with open(parsed_file, "w") as f:
        json.dump(parsed_data, f)

    print(f"💾 Resume #{resume_id} saved — awaiting profile confirmation")

    return {
        "success": True,
        "pending_confirmation": True,
        "resume_id": resume_id,
        "parsed": {
            "name": name,
            "phone": phone,
            "location": location,
            "experience_years": experience_years,
            "highest_degree": highest_degree,
            "institution": institution,
            "graduation_year": graduation_year,
            "summary": summary,
            "skills": skills,
        },
    }


@app.post("/confirm_resume_profile")
async def confirm_resume_profile(request: Request):
    """Apply confirmed profile fields, then run job matching (after upload)."""
    user = _require_login(request)
    if not user:
        return JSONResponse({"error": "Not logged in"}, status_code=401)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    resume_id = body.get("resume_id")
    if not resume_id:
        return JSONResponse({"error": "resume_id required"}, status_code=400)

    resume = models.get_resume_by_id(int(resume_id), user["id"])
    if not resume:
        return JSONResponse({"error": "Resume not found"}, status_code=404)

    if int(resume.get("profile_confirmed", 0) or 0) != 0:
        return JSONResponse(
            {"error": "Profile already confirmed for this resume"}, status_code=400
        )

    name = (body.get("name") or "").strip() or user.get("name", "")
    phone = (body.get("phone") or "").strip()
    location = (body.get("location") or "").strip()
    try:
        experience_years = float(body.get("experience_years", 0) or 0)
    except (TypeError, ValueError):
        experience_years = 0.0
    highest_degree = (body.get("highest_degree") or "").strip()
    institution = (body.get("institution") or "").strip()
    graduation_year = (body.get("graduation_year") or "").strip()
    summary = (body.get("summary") or "").strip() or (resume.get("summary") or "")
    raw_skills = body.get("skills")
    if isinstance(raw_skills, list):
        skills = [str(s).strip() for s in raw_skills if str(s).strip()]
    elif isinstance(raw_skills, str):
        skills = [
            s.strip() for s in raw_skills.replace("\n", ",").split(",") if s.strip()
        ]
    else:
        skills = []
    skills = sorted(set(skills))

    raw_roles = body.get("expected_roles")
    if isinstance(raw_roles, list):
        expected_roles_list = [str(r).strip() for r in raw_roles if str(r).strip()]
    else:
        expected_roles_list = []
    if not expected_roles_list:
        return JSONResponse(
            {
                "error": "Add at least one expected job role on your profile before confirming."
            },
            status_code=400,
        )

    file_path = resume.get("file_path") or ""
    text = ""
    if file_path and os.path.exists(file_path):
        text = extract_text(file_path)

    models.update_resume_record(
        int(resume_id),
        user["id"],
        {
            "role": summary[:100] if summary else resume.get("role", ""),
            "summary": summary,
            "experience": json.dumps(skills),
            "highest_degree": highest_degree,
            "institution": institution,
            "graduation_year": graduation_year,
            "experience_years": experience_years,
            "profile_confirmed": 1,
        },
    )

    updates = {
        "skills": json.dumps(skills),
        "expected_roles": json.dumps(expected_roles_list),
        "experience_years": experience_years,
        "active_resume_id": int(resume_id),
        "highest_degree": highest_degree,
        "institution": institution,
        "graduation_year": graduation_year,
        "phone": phone,
        "location": location,
    }
    models.update_profile(user["id"], updates)

    if name and name != user.get("name"):
        models.update_username(user["id"], name)

    profile = models.get_or_create_profile(user["id"])
    full_profile = {
        "skills": skills,
        "experience_years": experience_years,
        "expected_roles": expected_roles_list,
        "preferred_location": profile.get("preferred_location") or "",
        "job_type": profile.get("job_type") or "",
    }

    from app.company_matcher import get_best_matching_companies_from_profile

    raw_jobs = get_best_matching_companies_from_profile(full_profile, limit=100)
    best_matches = (
        models.match_jobs_to_resume(text, raw_jobs, threshold=0.2) if text else []
    )

    if not best_matches:
        best_matches = raw_jobs[:50]

    q_link = (
        " ".join(expected_roles_list[:2])
        if expected_roles_list
        else (" ".join(skills[:2]) if skills else "developer")
    )
    links = generate_redirect_links(q_link)

    models.delete_unapplied_suggestions(user["id"])
    models.insert_job_suggestions(user["id"], best_matches)

    print(
        f"✅ Profile confirmed for resume #{resume_id} — {len(best_matches)} job matches"
    )

    return {
        "success": True,
        "resume_id": int(resume_id),
        "skills": skills,
        "jobs": best_matches,
        "links": links,
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
    return JSONResponse(
        {"success": True, "message": "Resume deleted. You can upload a new one."}
    )


# ═══════════════════════════════════════════════════════════════════
# GET SUGGESTIONS
# ═══════════════════════════════════════════════════════════════════


@app.get("/get_suggestions")
def get_suggestions(request: Request):
    user = _require_login(request)
    if not user:
        return JSONResponse([], status_code=401)

    suggestions = models.get_all_suggestions(user["id"])

    result = []
    for s in suggestions:
        score = s.get("match_score", 0)
        score_pct = round(score * 100) if score <= 1 else int(score)
        is_applied = int(s.get("is_applied") or 0) == 1
        result.append(
            {
                "id": s["id"],
                "role": s.get("title", ""),
                "company": s.get("company", ""),
                "platform": s.get("platform", ""),
                "apply_url": s.get("apply_url", ""),
                "match_score": score_pct,
                "is_applied": is_applied,
                "status": "applied" if is_applied else "suggested",
                "match_label": (
                    "🟢 Strong Match"
                    if score_pct >= 60
                    else "🟡 Good Match" if score_pct >= 30 else "🔴 Partial Match"
                ),
                "date": (s.get("date_suggested") or "")[:10],
            }
        )

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

    return JSONResponse(
        {"success": True, "job_id": job_id, "redirect_url": "/suggestions"}
    )


# ═══════════════════════════════════════════════════════════════════
# SUGGESTIONS PAGE
# ═══════════════════════════════════════════════════════════════════


@app.get("/suggestions", response_class=HTMLResponse)
def suggestions_page(request: Request):
    if "user" not in request.session:
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(
        "suggestions.html",
        _template_ctx(
            request,
            user=request.session["user"],
            active_nav="suggestions",
        ),
    )


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

    pending_resume_json = None
    pend = models.get_pending_resume(user["id"])
    if pend:
        pfile = f"parsed_resumes_{user['id']}_{pend['id']}.json"
        if os.path.exists(pfile):
            with open(pfile) as f:
                pending_resume_json = json.load(f)
            pending_resume_json["resume_id"] = pend["id"]

    if (
        pending_resume_json
        and isinstance(pending_resume_json.get("skills"), list)
        and len(pending_resume_json["skills"]) > 0
    ):
        skills = pending_resume_json["skills"]

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
        resume_list.append(
            {
                "id": r["id"],
                "label": r.get("label") or f"Resume {r['id']}",
                "role": r.get("role", ""),
                "skills": resume_skills[:5],
                "is_active": r.get("is_active", 0),
                "exp_years": r.get("experience_years", 0),
                "degree": r.get("highest_degree", ""),
                "institution": r.get("institution", ""),
                "uploaded_at": (r.get("created_at") or "")[:10],
            }
        )

    return templates.TemplateResponse(
        "profile.html",
        _template_ctx(
            request,
            user=user,
            profile=profile,
            skills=skills,
            expected_roles=expected_roles,
            resumes=resume_list,
            pending_resume_json=pending_resume_json,
            message=request.session.pop("message", None),
            msg_type=request.session.pop("msg_type", None),
            active_nav="profile",
        ),
    )


# ───────────────────────────────────────────────────────────────────
# POST /profile/update — save basic info + preferences
# ───────────────────────────────────────────────────────────────────


@app.post("/profile/update")
async def update_profile(
    request: Request,
    name: str = Form(...),
    phone: str = Form(""),
    location: str = Form(""),
    experience_years: float = Form(0.0),
    preferred_location: str = Form(""),
    salary_range: str = Form(""),
    job_type: str = Form(""),
    highest_degree: str = Form(""),
    institution: str = Form(""),
    graduation_year: str = Form(""),
):
    user = _require_login(request)
    if not user:
        return JSONResponse({"error": "Not logged in"}, status_code=401)

    models.update_username(user["id"], name)
    models.update_profile(
        user["id"],
        {
            "phone": phone,
            "location": location,
            "experience_years": experience_years,
            "preferred_location": preferred_location,
            "salary_range": salary_range,
            "job_type": job_type,
            "highest_degree": highest_degree,
            "institution": institution,
            "graduation_year": graduation_year,
        },
    )

    request.session["message"] = "Profile updated successfully!"
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
        body = await request.json()
        roles = body.get("roles", [])
    except Exception:
        return JSONResponse({"error": "Bad request"}, status_code=400)

    if not isinstance(roles, list):
        return JSONResponse({"error": "roles must be a list"}, status_code=400)
    roles = [str(r).strip() for r in roles if str(r).strip()]
    if not roles:
        return JSONResponse(
            {
                "error": "Add at least one expected job role. Job search uses this list only.",
                "success": False,
            },
            status_code=400,
        )

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
        body = await request.json()
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
    ext = file.filename.split(".")[-1]
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

    body = await request.json()
    label = body.get("label", f"Resume {resume_id}")
    models.rename_resume(resume_id, user["id"], label)
    return JSONResponse({"success": True, "label": label})


# ═══════════════════════════════════════════════════════════════════
# SEND EMAIL
# ═══════════════════════════════════════════════════════════════════


@app.post("/send_best_matches")
async def send_best_matches(request: Request):
    from app.email_notifier import send_best_jobs_email

    user = _require_login(request)
    if not user:
        return JSONResponse({"error": "Not logged in"}, status_code=401)

    suggestions = models.get_suggestions(user["id"])
    top_jobs = suggestions[:5]

    sent = send_best_jobs_email(
        user.get("email", ""), top_jobs, username=user.get("name")
    )
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
        return JSONResponse(
            {"error": "Resume file not found on disk", "jobs_count": 0}, status_code=404
        )

    text = extract_text(file_path)
    if not text:
        return JSONResponse(
            {"error": "Could not extract text", "jobs_count": 0}, status_code=400
        )

    # Build full profile for matching
    profile = models.get_or_create_profile(user["id"])
    expected_roles = json.loads(profile.get("expected_roles") or "[]")
    if not expected_roles:
        return JSONResponse(
            {
                "error": "Add at least one expected job role on your profile before rematching.",
                "jobs_count": 0,
            },
            status_code=400,
        )

    full_profile = {
        "skills": json.loads(profile.get("skills") or "[]"),
        "experience_years": profile.get("experience_years", 0),
        "expected_roles": expected_roles,
        "preferred_location": profile.get("preferred_location", ""),
        "job_type": profile.get("job_type", ""),
    }

    # Fetch jobs + BERT match
    from app.company_matcher import get_best_matching_companies_from_profile

    raw_jobs = get_best_matching_companies_from_profile(full_profile, limit=100)
    best_matches = models.match_jobs_to_resume(text, raw_jobs, threshold=0.2)
    if not best_matches:
        best_matches = raw_jobs[:50]

    # Replace old suggestions with new ones
    models.delete_unapplied_suggestions(user["id"])
    models.insert_job_suggestions(user["id"], best_matches)

    print(
        f"🔄 Rematched resume #{resume_id} → {len(best_matches)} suggestions for user {user['id']}"
    )
    return JSONResponse({"success": True, "jobs_count": len(best_matches)})


# ═══════════════════════════════════════════════════════════════════
# ADMIN (superuser)
# ═══════════════════════════════════════════════════════════════════


@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request):
    admin, redir = _ensure_admin(request)
    if redir:
        return redir

    stats = models.admin_stats()
    return templates.TemplateResponse(
        "admin/dashboard.html",
        _template_ctx(
            request,
            user=request.session.get("user"),
            active_nav="admin",
            admin_stats=stats,
            message=request.session.pop("message", None),
            msg_type=request.session.pop("msg_type", None),
        ),
    )


@app.get("/admin/users", response_class=HTMLResponse)
def admin_users_page(request: Request):
    admin, redir = _ensure_admin(request)
    if redir:
        return redir

    users = models.list_users_admin()
    return templates.TemplateResponse(
        "admin/users.html",
        _template_ctx(
            request,
            user=request.session.get("user"),
            active_nav="admin_users",
            users=users,
            admin_id=admin["id"],
            message=request.session.pop("message", None),
            msg_type=request.session.pop("msg_type", None),
        ),
    )


@app.post("/admin/users/{target_id}/delete")
def admin_delete_user_route(target_id: int, request: Request):
    admin, redir = _ensure_admin(request)
    if redir:
        return redir

    if target_id == admin["id"]:
        request.session["message"] = (
            "You cannot delete your own account from the admin panel."
        )
        request.session["msg_type"] = "error"
        return RedirectResponse("/admin/users", status_code=303)

    if not models.get_user_by_id(target_id):
        request.session["message"] = "User not found."
        request.session["msg_type"] = "error"
        return RedirectResponse("/admin/users", status_code=303)

    models.admin_delete_user_cascade(target_id)
    request.session["message"] = f"User #{target_id} and related data were removed."
    request.session["msg_type"] = "success"
    return RedirectResponse("/admin/users", status_code=303)


@app.post("/admin/users/{target_id}/toggle-admin")
def admin_toggle_admin_route(target_id: int, request: Request):
    admin, redir = _ensure_admin(request)
    if redir:
        return redir

    target = models.get_user_by_id(target_id)
    if not target:
        request.session["message"] = "User not found."
        request.session["msg_type"] = "error"
        return RedirectResponse("/admin/users", status_code=303)

    if target_id == admin["id"]:
        request.session["message"] = "You cannot change your own admin flag."
        request.session["msg_type"] = "error"
        return RedirectResponse("/admin/users", status_code=303)

    new_val = 0 if int(target.get("is_admin") or 0) else 1
    models.set_user_admin(target_id, new_val)
    request.session["message"] = (
        f"User #{target_id} admin access {'enabled' if new_val else 'disabled'}."
    )
    request.session["msg_type"] = "success"
    return RedirectResponse("/admin/users", status_code=303)


@app.get("/admin/jobs", response_class=HTMLResponse)
def admin_jobs_page(request: Request, page: int = 1, user_id: int | None = None):
    _, redir = _ensure_admin(request)
    if redir:
        return redir

    page = max(1, page)
    per_page = 40
    offset = (page - 1) * per_page
    total = models.admin_count_job_suggestions(user_id)
    jobs = models.admin_list_job_suggestions(
        limit=per_page, offset=offset, user_id=user_id
    )
    total_pages = max(1, (total + per_page - 1) // per_page)

    return templates.TemplateResponse(
        "admin/jobs.html",
        _template_ctx(
            request,
            user=request.session.get("user"),
            active_nav="admin_jobs",
            jobs=jobs,
            page=page,
            total_pages=total_pages,
            total=total,
            filter_user_id=user_id,
            all_users=models.list_users_admin(),
            message=request.session.pop("message", None),
            msg_type=request.session.pop("msg_type", None),
        ),
    )


@app.post("/admin/jobs/{job_id}/delete")
def admin_delete_job_route(job_id: int, request: Request):
    _admin, redir = _ensure_admin(request)
    if redir:
        return redir

    if not models.admin_delete_job_suggestion(job_id):
        request.session["message"] = "Job suggestion not found."
        request.session["msg_type"] = "error"
    else:
        request.session["message"] = f"Suggestion #{job_id} removed."
        request.session["msg_type"] = "success"

    return RedirectResponse("/admin/jobs", status_code=303)


# ═══════════════════════════════════════════════════════════════════
# QUICK JOB LINKS
# ═══════════════════════════════════════════════════════════════════


@app.get("/scheduler-status")
def scheduler_status(request: Request):
    from app.scheduler import _scheduler
    from app import models

    user = _require_login(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    # Get scheduler info (two-phase: fetch → jobs table, then match)
    job_fetch = _scheduler.get_job("hourly_fetch_jobs") if _scheduler else None
    job_match = _scheduler.get_job("hourly_match_users") if _scheduler else None
    next_fetch = str(job_fetch.next_run_time)[:19] if job_fetch else "Not running"
    next_match = str(job_match.next_run_time)[:19] if job_match else "Not running"
    is_running = _scheduler.running if _scheduler else False
    jobs_catalog_count = models.count_jobs_catalog()

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
        recent = conn.execute(
            """
            SELECT title, company, platform, match_score, date_suggested
            FROM job_suggestions
            WHERE user_id = ? AND is_applied = 0
            ORDER BY date_suggested DESC
            LIMIT 5
        """,
            (user["id"],),
        ).fetchall()
        recent_jobs = [dict(r) for r in recent]
    finally:
        conn.close()

    return {
        "scheduler_running": is_running,
        "next_run": next_fetch,
        "next_fetch_run": next_fetch,
        "next_match_run": next_match,
        "jobs_in_catalog": jobs_catalog_count,
        "users": users_data,
        "your_recent_suggestions": recent_jobs,
        "checked_at": datetime.now().strftime("%d %b %Y %H:%M:%S"),
    }


@app.get("/quick-job-links")
def quick_job_links(query: str, location: str = "India"):
    return generate_redirect_links(query, location)
