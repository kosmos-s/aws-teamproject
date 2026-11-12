"""Monotonic read cursors, atomically updated on both supported databases."""

from sqlalchemy import func
from .models import ChatRead


def mark_read(db, user_id, key, last_id):
    if db.bind.dialect.name == "mysql":
        from sqlalchemy.dialects.mysql import insert

        q = insert(ChatRead).values(user_id=user_id, room_key=key, last_id=last_id)
        q = q.on_duplicate_key_update(
            last_id=func.greatest(ChatRead.last_id, q.inserted.last_id)
        )
    elif db.bind.dialect.name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert

        q = insert(ChatRead).values(user_id=user_id, room_key=key, last_id=last_id)
        q = q.on_conflict_do_update(
            index_elements=["user_id", "room_key"],
            set_={"last_id": func.max(ChatRead.last_id, q.excluded.last_id)},
        )
    else:
        raise RuntimeError("Unsupported database dialect")
    db.execute(q)
