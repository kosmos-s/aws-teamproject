from sqlalchemy import Column, Integer, String, Text, ForeignKey, Float
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(80), unique=True, nullable=False)
    password_hash = Column(String(256), nullable=False)
    role = Column(String(20), nullable=False)


class LoginSession(Base):
    __tablename__ = "sessions"
    token_hash = Column(String(64), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    csrf = Column(String(64), nullable=False)
    expires = Column(Float, nullable=False)


class Project(Base):
    __tablename__ = "projects"
    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    description = Column(Text, nullable=False, default="")
    created = Column(String(40), nullable=False)


class Note(Base):
    __tablename__ = "work_notes"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    author = Column(String(80), nullable=False)
    body = Column(Text, nullable=False)
    created = Column(String(40), nullable=False)


class Attachment(Base):
    __tablename__ = "attachments"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    name = Column(String(180), nullable=False)
    key = Column(String(100), nullable=False)
    media_type = Column(String(80), nullable=False)
    size = Column(Integer, nullable=False)


class Event(Base):
    __tablename__ = "operation_events"
    id = Column(Integer, primary_key=True)
    kind = Column(String(30), nullable=False)
    state = Column(String(20), nullable=False)
    created = Column(String(40), nullable=False)
    summary = Column(Text, nullable=False)
