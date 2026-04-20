# CareerMatch AI

A small FastAPI web app that parses resumes, stores profiles in SQLite, and suggests job matches with links to apply.

## Requirements

- **Python 3.10–3.12** (recommended: **3.12**). Python **3.13** often fails to install pinned packages such as NumPy 2.0.2 from source; use 3.12 until those wheels support your platform.
- macOS, Linux, or Windows

## Setup

From the project root:

```bash
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt
```

The `en_core_web_sm` spaCy model is installed from `requirements.txt` as a wheel URL; no separate `spacy download` step is required.

Installing dependencies can take several minutes and several hundred MB of disk space: `sentence-transformers` pulls **PyTorch** and related packages. The first time you upload a resume and jobs are matched, the app may download the **`all-MiniLM-L6-v2`** embedding model (one-time).

## Configuration (optional)

Create a `.env` file in the project root if you need these features:

| Variable | Purpose |
|----------|---------|
| `SECRET_KEY` | Session cookie signing (defaults to a dev value if unset) |
| `GOOGLE_API_KEY` | Richer resume parsing via Gemini (app falls back without it) |
| `RAPIDAPI_KEY` | JSearch job listings via RapidAPI (subscribe to the API and add your key) |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USER`, `EMAIL_PASSWORD`, `EMAIL_FROM`, `EMAIL_USE_TLS` | Email notifications for job suggestions |

Without API keys, registration, login, uploads, and basic matching still work; some integrations print warnings or use fallbacks.

## Run the server

```bash
source venv/bin/activate          # if not already active
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

You can also run the app directly from the package entrypoint:

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

## Project structure

```text
CareerMatch_AI/
├── app/
│   ├── main.py
│   ├── database.py
│   ├── models.py
│   ├── auth.py
│   ├── scheduler.py
│   └── ... (services and helpers)
├── templates/
├── static/
├── uploads/
└── main.py  # compatibility entrypoint -> app.main:app
```

Open **http://127.0.0.1:8000** — you will be redirected to `/login`. Create an account at `/register`, then sign in and upload a resume from the dashboard.

## Data on disk

- **SQLite:** `users.db` (created on first run)
- **Uploads:** `uploads/`, `static/profile_pics/`, and optional cache JSON files

These paths are ignored by git where appropriate; keep backups if you care about local data.
