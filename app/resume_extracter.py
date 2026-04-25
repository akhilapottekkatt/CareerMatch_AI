import pdfplumber


def extract_text(file_path: str) -> str:
    """
    Extract text from PDF using pdfplumber.

    Returns:
        Extracted text as string
        Returns empty string "" if extraction fails
    """
    text = ""

    try:
        with pdfplumber.open(file_path) as pdf:
            for i, page in enumerate(pdf.pages):
                page_text = page.extract_text()

                if page_text:
                    text += page_text + "\n"
                else:
                    print(f"⚠️ Page {i+1} has no extractable text")

    except Exception as e:
        print(f"❌ PDF extraction error: {e}")
        return ""

    if not text.strip():
        print("⚠️ No text extracted from PDF")
        return ""

    print(f"✅ Extracted {len(text)} characters from PDF")
    return text.strip()
