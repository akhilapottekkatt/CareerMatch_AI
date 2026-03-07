import os
import json
from google.genai import Client

# Create Gemini client
client = Client(api_key=os.getenv("GOOGLE_API_KEY"))

def parse_resume(text):

    prompt = f"""
    Extract the following information from the resume.

    Return JSON in this format:
    {{
        "role": "",
        "experience": "",
        "summary": ""
    }}

    Resume:
    {text}
    """

    response = client.models.generate_content(
        model="gemini-1.5-flash",
        contents=prompt
    )

    result = response.text

    try:
        parsed_data = json.loads(result)
    except:
        parsed_data = {
            "role": "",
            "experience": "",
            "summary": result
        }

    return parsed_data