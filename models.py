from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Text, Table, Float, Boolean
from database import Base
from sqlalchemy.orm import relationship
from datetime import datetime

# -------------------------
# Association Table
# -------------------------
resume_skills = Table(
    "resume_skills",
    Base.metadata,
    Column("resume_id", Integer, ForeignKey("resumes.id")),
    Column("skill_id", Integer, ForeignKey("skills.id"))
)

# -------------------------
# User Table
# -------------------------
class User(Base):
    __tablename__ = "users"

    id       = Column(Integer, primary_key=True, index=True)
    username = Column(Text, unique=True, nullable=False)
    email    = Column(String, unique=True, nullable=False)
    password = Column(String, nullable=False)

    resumes      = relationship("Resume", back_populates="user")
    suggestions  = relationship("JobSuggestion", back_populates="user")
    applied_jobs = relationship("AppliedJob", back_populates="user")


# -------------------------
# Resume Table
# -------------------------
class Resume(Base):
    __tablename__ = "resumes"

    id         = Column(Integer, primary_key=True, index=True)
    user_id    = Column(Integer, ForeignKey("users.id"))
    file_path  = Column(String, nullable=False)
    role       = Column(String)
    experience = Column(Text)        # stored as JSON string
    summary    = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    user   = relationship("User", back_populates="resumes")
    skills = relationship("Skill", secondary=resume_skills, back_populates="resumes")


# -------------------------
# Skill Table
# -------------------------
class Skill(Base):
    __tablename__ = "skills"

    id   = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)

    resumes = relationship("Resume", secondary=resume_skills, back_populates="skills")


# -------------------------
# JobSuggestion Table
# Stores jobs suggested to user (from scraper + BERT match)
# -------------------------
class JobSuggestion(Base):
    __tablename__ = "job_suggestions"

    id           = Column(Integer, primary_key=True, index=True)
    user_id      = Column(Integer, ForeignKey("users.id"))
    title        = Column(String)
    company      = Column(String)
    platform     = Column(String)          # LinkedIn / Indeed / Naukri etc.
    apply_url    = Column(Text)
    match_score  = Column(Float, default=0.0)
    date_suggested = Column(DateTime, default=datetime.utcnow)
    is_applied   = Column(Boolean, default=False)

    user = relationship("User", back_populates="suggestions")


# -------------------------
# AppliedJob Table
# Jobs user clicked "Applied" on — never shown in suggestions again
# -------------------------
class AppliedJob(Base):
    __tablename__ = "applied_jobs"

    id         = Column(Integer, primary_key=True, index=True)
    user_id    = Column(Integer, ForeignKey("users.id"))
    title      = Column(String)
    company    = Column(String)
    platform   = Column(String)
    apply_url  = Column(Text)
    match_score = Column(Float, default=0.0)
    applied_at = Column(DateTime, default=datetime.utcnow)
    status     = Column(String, default="applied")  # applied / interview / offer / rejected

    user = relationship("User", back_populates="applied_jobs")


# -------------------------
# BERT Cosine Matching
# -------------------------
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np

sentence_model = SentenceTransformer('all-MiniLM-L6-v2')

def match_jobs_to_resume(resume_text: str, jobs: list, threshold: float = 0.4) -> list:
    """Match jobs to resume using BERT cosine similarity. Returns top 5."""
    if not resume_text or not jobs:
        return []

    resume_emb = sentence_model.encode(resume_text)
    matches = []

    for job in jobs:
        job_desc = f"{job.get('title', '')} {job.get('description', '')} {job.get('company', '')}"
        job_emb  = sentence_model.encode(job_desc)
        score    = float(cosine_similarity([resume_emb], [job_emb])[0][0])

        matches.append({
            "job":         job,
            "similarity":  score,
            "match_score": f"{score:.0%}"
        })

    return sorted(matches, key=lambda x: x["similarity"], reverse=True)[:5]