from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Text, Table
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

    id = Column(Integer, primary_key=True, index=True)
    username = Column(Text, unique=True, nullable=False)
    email = Column(String, unique=True, nullable=False)
    password = Column(String, nullable=False)

    resumes = relationship("Resume", back_populates="user")


# -------------------------
# Resume Table
# -------------------------
class Resume(Base):
    __tablename__ = "resumes"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))

    file_path = Column(String, nullable=False)
    role = Column(String)
    experience = Column(String)
    summary = Column(Text)

    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="resumes")
    skills = relationship("Skill", secondary=resume_skills, back_populates="resumes")


# -------------------------
# Skill Table
# -------------------------
class Skill(Base):
    __tablename__ = "skills"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)

    resumes = relationship("Resume", secondary=resume_skills, back_populates="skills")