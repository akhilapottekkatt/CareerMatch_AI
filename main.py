# from fastapi import FastAPI, File, UploadFile
# import shutil
# import os

# app = FastAPI()

# UPLOAD_FOLDER = "uploads"

# # Create uploads folder if not exist
# if not os.path.exists(UPLOAD_FOLDER):
#     os.makedirs(UPLOAD_FOLDER)


# @app.get("/")
# def home():
#     return {"message": "CareerMatch_AI Server is running!"}


# @app.post("/upload_resume")
# async def upload_resume(file: UploadFile = File(...)):
#     file_path = os.path.join(UPLOAD_FOLDER, file.filename)

#     with open(file_path, "wb") as buffer:
#         shutil.copyfileobj(file.file, buffer)

#     return {"filename": file.filename, "status": "Uploaded Successfully"}


from fastapi import FastAPI, File, UploadFile, Request, Form
import shutil
import os
from job_links import generate_job_links
from resume_parser import extract_text_from_pdf, extract_skills
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from company_matcher import match_companies, send_resume_to_companies
from email_notifier import send_summary_email

app = FastAPI()

templates = Jinja2Templates(directory="templates")

app.mount("/static", StaticFiles(directory="static"), name="static")

UPLOAD_FOLDER = "uploads"

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/upload_resume")
async def upload_resume(
    email: str = Form(...),
    file: UploadFile = File(...),
):
    file_path = os.path.join(UPLOAD_FOLDER, file.filename)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # Extract resume text and detected skills
    resume_text = extract_text_from_pdf(file_path)
    skills = extract_skills(resume_text)

    # Generate job search links based on detected skills
    job_links = generate_job_links(skills)

    # Find up to 5 companies related to the detected skills
    matched_companies = match_companies(skills, limit=5)

    # "Send" resume to those companies (stub implementation)
    sent_companies = send_resume_to_companies(file_path, matched_companies)

    # Notify the user by email with today's companies and job links
    send_summary_email(
        to_email=email,
        skills=skills,
        sent_companies=sent_companies,
        job_links=job_links,
    )

    return {
        "filename": file.filename,
        "skills_found": skills,
        "job_links": job_links,
        "sent_companies": sent_companies,
    }
