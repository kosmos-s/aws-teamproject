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


class BlockedUser(Base):
    __tablename__ = "blocked_users"
    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)


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


class OrcaProject(Base):
    __tablename__ = "orca_projects"
    project_id = Column(Integer, ForeignKey("projects.id"), primary_key=True)
    label = Column(String(120), nullable=False)
    repository_url = Column(String(255), nullable=False)


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


class ChatMessage(Base):
    """Team chat. room='main' (everyone) or 'dm' (sender ↔ recipient)."""
    __tablename__ = "chat_messages"
    id = Column(Integer, primary_key=True)
    room = Column(String(10), nullable=False, index=True)
    sender_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    sender_name = Column(String(80), nullable=False)
    recipient_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    body = Column(Text, nullable=False)
    created = Column(String(40), nullable=False)


class ChatRead(Base):
    """Last message each user has read per room ('main' or 'dm:<peer id>')."""
    __tablename__ = "chat_reads"
    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    room_key = Column(String(40), primary_key=True)
    last_id = Column(Integer, nullable=False, default=0)


class OrcaLinkRequest(Base):
    """Admin request to clone a GitHub repo into Orca and link it to a portal project.
    The web only records the request; a fixed root timer job (deploy/orca-link-worker.py) runs it."""
    __tablename__ = "orca_link_requests"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    repository_url = Column(String(255), nullable=False)
    folder = Column(String(100), nullable=False)
    state = Column(String(20), nullable=False, index=True)
    detail = Column(String(500), nullable=False, default="")
    requested_by = Column(String(80), nullable=False)
    created = Column(String(40), nullable=False)
    finished = Column(String(40), nullable=True)


# --- 2026-11-11 additions. Separate tables instead of ALTERing live ones. ---
class ProjectArchive(Base):
    """A row here means the project is archived (hidden from active lists, kept for history)."""
    __tablename__ = "project_archives"
    project_id = Column(Integer, ForeignKey("projects.id"), primary_key=True)
    archived_by = Column(String(80), nullable=False)
    archived_at = Column(String(40), nullable=False)


class NoteEdit(Base):
    """Last edit of a work note (shown as '수정됨')."""
    __tablename__ = "note_edits"
    note_id = Column(Integer, ForeignKey("work_notes.id"), primary_key=True)
    edited_by = Column(String(80), nullable=False)
    edited_at = Column(String(40), nullable=False)


class TeamGroup(Base):
    """A team / department / club cohort. Each group has its own chat room (room='g<id>')."""
    __tablename__ = "team_groups"
    id = Column(Integer, primary_key=True)
    name = Column(String(80), unique=True, nullable=False)
    description = Column(String(300), nullable=False, default="")
    created = Column(String(40), nullable=False)


class GroupMember(Base):
    __tablename__ = "group_members"
    group_id = Column(Integer, ForeignKey("team_groups.id"), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)


class UserActivity(Base):
    """Last login / last seen and the 'must change password' flag for each account."""
    __tablename__ = "user_activity"
    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    last_login = Column(String(40), nullable=True)
    last_seen = Column(String(40), nullable=True)
    must_change = Column(Integer, nullable=False, default=0)
