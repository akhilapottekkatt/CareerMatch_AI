


import json
from fastapi import FastAPI, Request, Form, UploadFile, File, Depends, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from database import create_users_table, engine, SessionLocal,get_db
from models import Base, User, Resume
from auth import create_user, authenticate_user
import os
import shutil
from openai import OpenAI
from resume_extracter import extract_text
from resume_parser import parse_resume



Base.metadata.create_all(bind=engine)

app = FastAPI()


app.add_middleware(SessionMiddleware, secret_key="supersecretkey")
app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")


# Create table on startup
create_users_table()


# ---------------- REGISTER ----------------

@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    message = request.session.pop("message", None)
    msg_type = request.session.pop("msg_type", None)
    return templates.TemplateResponse("register.html", {"request": request, "message": message, "msg_type": msg_type})


@app.post("/register")
def register_user(request: Request,
                  name: str = Form(...),
                  email: str = Form(...),
                  password: str = Form(...)):
    
    success = create_user(name,email,password)

    if not success:
        request.session["message"] = "Email already registered"
        request.session["msg_type"] = "error"
        return RedirectResponse("/register", status_code=status.HTTP_303_SEE_OTHER)

    request.session["message"] = "Registration successful ! Please login"
    request.session["msg_type"] = "success"
    return RedirectResponse("/login", status_code= status.HTTP_303_SEE_OTHER)


# ---------------- LOGIN ----------------
@app.get("/")
def home():
    return RedirectResponse("/login")

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    message = request.session.pop("message", None)
    msg_type = request.session.pop("msg_type", None)
    return templates.TemplateResponse("login.html", {"request": request,
                                            "message": message,
                                            "msg_type": msg_type 
                                        })


@app.post("/login")
def login_user(request: Request,
               email: str = Form(...),
               password: str = Form(...)):

    user = authenticate_user(email, password)

    if user:
        request.session["user"] = user
        request.session["message"] = "Login successful!"
        request.session["msg_type"] = "success"
        return RedirectResponse("/dashboard", status_code=303)
    request.session["message"] = "Invalid email or password "
    request.session["msg_type"] = "error"
    return RedirectResponse("/login", status_code=303)


# ---------------- DASHBOARD ----------------

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):

    if "user" not in request.session:
        return RedirectResponse("/login", status_code=303)

    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "user": request.session["user"]}
    )


# ---------------- LOGOUT ----------------

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@app.post("/upload_resume")
def upload_resume(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    print("Upload route called")

    if "user" not in request.session:
        return RedirectResponse("/login", status_code=303)

    email = request.session["user"]
    user = db.query(User).filter(User.email == email).first()

    if not user:
        return RedirectResponse("/login", status_code=303)

    # Save file
    file_path = os.path.join("uploads", file.filename)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # Extract text
    resume_text = extract_text(file_path)

    # AI Parse
    parsed_data = parse_resume(resume_text)

    print("Parsed Data:", parsed_data)

    # Save parsed data to JSON file
    with open("parsed_resumes.json", "w") as f:
        json.dump(parsed_data, f, indent=4)

    # Store in Database
    resume = Resume(
        user_id=user.id,
        file_path=file_path,
        role=parsed_data.get("role", ""),
        experience=parsed_data.get("experience", ""),
        summary=parsed_data.get("summary", "")
    )

    db.add(resume)
    db.commit()

    return {"message": "Resume uploaded successfully"}