"""Shared test helpers for the unit test layer.

Module-level functions (not fixtures) so they can be imported from both
models/ and services/ test subtrees without pytest fixture scoping
constraints.
"""

from __future__ import annotations

from uuid import uuid4

from app.models.user import User
from sqlalchemy.orm import Session


def make_user(session: Session) -> User:
    """Insert a minimal User row and flush. Returns the persisted User."""
    uid = uuid4().hex[:8]
    user = User(
        id=str(uuid4()),
        username=f"user-{uid}",
        email=f"u-{uid}@test",
        hashed_password="x",
    )
    session.add(user)
    session.flush()
    return user
