import pdfplumber

def extract_text(file_path: str) -> str:
    """Extract text from PDF using pdfplumber."""
    text = ""
    try:
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:  # ← skip None pages
                    text += page_text + "\n"
    except Exception as e:
        print(f"❌ PDF extraction error: {e}")
        return ""

    print(f"✅ Extracted {len(text)} characters from PDF")
    return text.strip()