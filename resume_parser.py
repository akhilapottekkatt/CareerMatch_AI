from PyPDF2 import PdfReader


def extract_text_from_pdf(file_path: str) -> str:
    """
    Extract text from a PDF resume
    """
    text = ""

    try:
        reader = PdfReader(file_path)
        for page in reader.pages:
            text += page.extract_text() or ""
    except Exception as e:
        print("Error reading PDF:", e)

    return text


def extract_skills(resume_text: str) -> list:
    """
    Extract skills from resume text using predefined skill list
    """
    skills_list = [
        "python", "java", "c", "c++", "sql",
        "html", "css", "javascript",
        "fastapi", "django", "flask",
        "git", "github", "linux",
        "aws", "azure", "docker",
        "machine learning", "data science"
    ]

    resume_text = resume_text.lower()
    found_skills = []

    for skill in skills_list:
        if skill in resume_text:
            found_skills.append(skill)

    return found_skills
 