# job_links.py
import PyPDF2

def extract_text_from_pdf(pdf_path: str) -> str:
    """Extract text from a PDF file."""
    text = ""
    try:
        with open(pdf_path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages:
                text += page.extract_text() or ""
    except FileNotFoundError:
        print(f"File not found: {pdf_path}")
    return text

def generate_portal_links():
    # Example portals
    return [
        "https://www.linkedin.com/jobs",
        "https://www.indeed.com/jobs",
        "https://www.naukri.com/jobs"
    ]

def scrape_jobs(resume_text: str):
    # Dummy job scraping logic
    jobs = [
        {"title": "Software Engineer", "company": "ABC Corp"},
        {"title": "Data Analyst", "company": "XYZ Ltd"},
    ]
    # You can add logic here to match resume_text with job descriptions
    return jobs

def generate_job_links(resume_path="uploads/sample_resume.pdf"):
    # Extract text from PDF resume
    resume_text = extract_text_from_pdf(resume_path)

    # Generate job portal links
    portals = generate_portal_links()

    # Scrape/match jobs based on resume text
    jobs = scrape_jobs(resume_text)

    return {"portals": portals, "jobs": jobs}
