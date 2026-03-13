# import os
# import json
# import re
# from dotenv import load_dotenv
# from google.genai import Client

# load_dotenv()

# client = Client(api_key=os.getenv("GOOGLE_API_KEY"))

# import time
# from google.genai import errors

# def parse_resume(resume_text):
#     for attempt in range(3):  # retry up to 3 times
#         try:
#             response = client.models.generate_content(
#                 model="gemini-1.5-flash",
#                 contents=your_prompt
#             )
#             return response.text
#         except errors.ClientError as e:
#             if "429" in str(e) and attempt < 2:
#                 print(f"Rate limited. Waiting 60s... (attempt {attempt+1}/3)")
#                 time.sleep(60)
#             else:
#                 raise

import os
import json
import time
from dotenv import load_dotenv
from google import genai
from google.genai import errors

load_dotenv()

client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

def parse_resume(resume_text: str) -> dict:
    """
    Parse resume text using Gemini and return structured JSON.
    Tries multiple models in order, retries on rate limits.
    """

    prompt = f"""
You are an expert resume parser. Extract information from the resume below and return ONLY a valid JSON object — no explanation, no markdown, no code fences.

The JSON must have exactly these keys:
{{
  "name": "full name or null",
  "email": "email address or null",
  "phone": "phone number or null",
  "location": "city/country or null",
  "summary": "professional summary in 2-3 sentences or null",
  "skills": ["skill1", "skill2", "skill3"],
  "experience": [
    {{
      "title": "job title",
      "company": "company name",
      "duration": "e.g. 2020-2022",
      "description": "brief description of role"
    }}
  ],
  "education": [
    {{
      "degree": "degree name",
      "institution": "university/college name",
      "year": "graduation year or null"
    }}
  ],
  "certifications": ["cert1", "cert2"],
  "languages": ["English", "Hindi"],
  "experience_years": 0
}}

Rules:
- skills must be a flat list of strings (e.g. ["Python", "React", "SQL"])
- experience_years should be total years of work experience as an integer
- If a field has no data, use null for strings or [] for lists
- Return ONLY the JSON object, nothing else

Resume Text:
{resume_text}
"""

    # Try models in order until one works
    models_to_try = [
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
        "gemini-1.0-pro",
    ]

    for model_name in models_to_try:
        for attempt in range(2):
            try:
                print(f"🤖 Trying model: {model_name} (attempt {attempt + 1})")
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt
                )

                raw = response.text.strip()

                # Strip markdown code fences if Gemini wraps response
                if raw.startswith("```"):
                    parts = raw.split("```")
                    raw = parts[1] if len(parts) > 1 else parts[0]
                    if raw.startswith("json"):
                        raw = raw[4:]
                    raw = raw.strip()

                parsed = json.loads(raw)
                print(f"✅ Parsed successfully with {model_name}")
                return parsed

            except errors.ClientError as e:
                error_str = str(e)
                if "429" in error_str:
                    wait = 60 * (attempt + 1)
                    print(f"⚠️  Rate limited on {model_name}. Waiting {wait}s...")
                    time.sleep(wait)
                elif "404" in error_str:
                    print(f"⚠️  Model {model_name} not available, trying next...")
                    break  # move to next model
                else:
                    print(f"❌ Gemini API error on {model_name}: {e}")
                    break

            except json.JSONDecodeError as e:
                print(f"❌ JSON parse error: {e}")
                print(f"Raw response: {response.text[:300]}")
                break

            except Exception as e:
                print(f"❌ Unexpected error with {model_name}: {e}")
                break

    print("❌ All models failed. Returning empty resume structure.")
    return _empty_resume()


def _empty_resume() -> dict:
    """Safe empty fallback structure."""
    return {
        "name": None,
        "email": None,
        "phone": None,
        "location": None,
        "summary": None,
        "skills": [],
        "experience": [],
        "education": [],
        "certifications": [],
        "languages": [],
        "experience_years": 0
    }