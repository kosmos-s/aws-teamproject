from sqlalchemy import Column, Integer, String, Text, ForeignKey, Float, Index
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


# --- 2026-11-12 additions (separate tables, no ALTER on live tables) ---
class AttachmentOwner(Base):
    """Who uploaded an attachment (uploads before this table existed have no row: admin-only delete)."""
    __tablename__ = "attachment_owners"
    attachment_id = Column(Integer, ForeignKey("attachments.id"), primary_key=True)
    uploaded_by = Column(String(80), nullable=False)
    uploaded_at = Column(String(40), nullable=False)


class ChatEdit(Base):
    """Edit/delete marker for a chat message. deleted=1 means the body was cleared."""
    __tablename__ = "chat_edits"
    message_id = Column(Integer, ForeignKey("chat_messages.id"), primary_key=True)
    edited_at = Column(String(40), nullable=False)
    deleted = Column(Integer, nullable=False, default=0)


class ProjectAccess(Base):
    """If a project has rows here, only members of these groups (and admins) can see it in the portal."""
    __tablename__ = "project_access"
    project_id = Column(Integer, ForeignKey("projects.id"), primary_key=True)
    group_id = Column(Integer, ForeignKey("team_groups.id"), primary_key=True)


# --- 2026-11-12 collaboration suite (separate tables, no ALTER) ---
class ChatAttachment(Base):
    __tablename__ = "chat_attachments"
    message_id = Column(Integer, ForeignKey("chat_messages.id"), primary_key=True)
    key = Column(String(100), nullable=False)
    name = Column(String(180), nullable=False)
    media_type = Column(String(80), nullable=False)
    size = Column(Integer, nullable=False)


class ChatReply(Base):
    __tablename__ = "chat_replies"
    message_id = Column(Integer, ForeignKey("chat_messages.id"), primary_key=True)
    reply_to = Column(Integer, ForeignKey("chat_messages.id"), nullable=False)


class ChatReaction(Base):
    __tablename__ = "chat_reactions"
    message_id = Column(Integer, ForeignKey("chat_messages.id"), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    emoji = Column(String(16), primary_key=True)
    created = Column(String(40), nullable=False)


class ChatPin(Base):
    """One pinned message per room ('main', 'g<id>', 'dm:<a>-<b>')."""
    __tablename__ = "chat_pins"
    room_key = Column(String(40), primary_key=True)
    message_id = Column(Integer, ForeignKey("chat_messages.id"), nullable=False)
    pinned_by = Column(String(80), nullable=False)
    pinned_at = Column(String(40), nullable=False)


class Task(Base):
    """Kanban card for a project: todo / doing / done."""
    __tablename__ = "tasks"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    title = Column(String(200), nullable=False)
    status = Column(String(10), nullable=False, default="todo")
    assignee = Column(String(80), nullable=True)
    due = Column(String(10), nullable=True)  # YYYY-MM-DD
    created_by = Column(String(80), nullable=False)
    created = Column(String(40), nullable=False)
    updated = Column(String(40), nullable=False)


class Profile(Base):
    __tablename__ = "profiles"
    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    display_name = Column(String(40), nullable=False, default="")
    team = Column(String(60), nullable=False, default="")
    photo_key = Column(String(100), nullable=True)
    updated = Column(String(40), nullable=False)


class UserTotp(Base):
    """TOTP second factor. enabled=0 while the user is still setting it up."""
    __tablename__ = "user_totp"
    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    secret = Column(String(64), nullable=False)
    enabled = Column(Integer, nullable=False, default=0)
    created = Column(String(40), nullable=False)


class ProjectPolicy(Base):
    __tablename__ = "project_policies"
    project_id = Column(Integer, primary_key=True)
    restricted = Column(Integer, nullable=False, default=1)


class SessionActivity(Base):
    __tablename__ = "session_activity"
    token_hash = Column(String(64), primary_key=True)
    last_active = Column(Float, nullable=False)


class TotpVault(Base):
    __tablename__ = "totp_vault"
    user_id = Column(Integer, primary_key=True)
    encrypted = Column(Text, nullable=False)


class RecoveryCode(Base):
    __tablename__ = "recovery_codes"
    user_id = Column(Integer, primary_key=True)
    code_hash = Column(String(64), primary_key=True)


class UserPreference(Base):
    __tablename__ = "user_preferences"
    user_id = Column(Integer, primary_key=True)
    notify = Column(String(12), nullable=False, default="all")
    sound = Column(Integer, nullable=False, default=1)


class ObjectDeletion(Base):
    __tablename__ = "object_deletions"
    key = Column(String(100), primary_key=True)
    created = Column(Float, nullable=False)
    attempts = Column(Integer, nullable=False, default=0)


class UploadRecord(Base):
    __tablename__ = "upload_records"
    key = Column(String(100), primary_key=True)
    username = Column(String(80), nullable=False, index=True)
    scope = Column(String(40), nullable=False, index=True)
    size = Column(Integer, nullable=False)
    created = Column(Float, nullable=False)


class ChangeNotice(Base):
    __tablename__ = "change_notices"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, nullable=True, index=True)
    kind = Column(String(30), nullable=False)
    title = Column(String(160), nullable=False)
    body = Column(String(2000), nullable=False, default="")
    actor = Column(String(80), nullable=False)
    admin_only = Column(Integer, nullable=False, default=0)
    created = Column(String(40), nullable=False)


class NoticeRead(Base):
    __tablename__ = "notice_reads"
    user_id = Column(Integer, primary_key=True)
    last_id = Column(Integer, nullable=False, default=0)


Index('ix_chat_room_id', ChatMessage.room, ChatMessage.id)
Index('ix_chat_dm_recipient_sender_id', ChatMessage.recipient_id, ChatMessage.sender_id, ChatMessage.id)


class ProjectOwner(Base):
    __tablename__ = 'project_owners'
    project_id = Column(Integer, ForeignKey('projects.id'), primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    assigned_at = Column(String(40), nullable=False)


class ProjectRepository(Base):
    __tablename__ = 'project_repositories'
    project_id = Column(Integer, ForeignKey('projects.id'), primary_key=True)
    repository_url = Column(String(255), nullable=False)
    folder = Column(String(100), nullable=False, unique=True)
    revision = Column(Integer, nullable=False, default=1)
    state = Column(String(30), nullable=False, default='pending')


class ProjectDeployKey(Base):
    __tablename__ = 'project_deploy_keys'
    project_id = Column(Integer, ForeignKey('projects.id'), primary_key=True)
    generation = Column(Integer, nullable=False, default=1)
    public_key = Column(Text, nullable=False, default='')
    fingerprint = Column(String(100), nullable=False, default='')
    state = Column(String(30), nullable=False, default='pending')
    created = Column(String(40), nullable=False)
    verified_at = Column(String(40), nullable=True)


class ProjectJob(Base):
    """Only fixed repository/key operations. No private keys or arbitrary command input."""
    __tablename__ = 'project_jobs'
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, nullable=False, index=True)
    actor_id = Column(Integer, nullable=False)
    revision = Column(Integer, nullable=False)
    kind = Column(String(20), nullable=False)
    generation = Column(Integer, nullable=False, default=0)
    cleanup = Column(Integer, nullable=False, default=0)
    state = Column(String(20), nullable=False, default='pending', index=True)
    detail = Column(String(500), nullable=False, default='')
    created = Column(String(40), nullable=False)
    started = Column(String(40), nullable=True)
    finished = Column(String(40), nullable=True)
