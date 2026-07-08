"""Connections: the trust boundary for delegation. Request -> accept makes two
users connected; only connected users can assign each other tasks."""
from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connection import Connection
from app.models.notification import Notification
from app.models.user import User


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    return await db.scalar(select(User).where(User.email == email.strip().lower()))


def _pair(a: uuid.UUID, b: uuid.UUID):
    return or_(
        and_(Connection.requester_id == a, Connection.addressee_id == b),
        and_(Connection.requester_id == b, Connection.addressee_id == a),
    )


async def are_connected(db: AsyncSession, a: uuid.UUID, b: uuid.UUID) -> bool:
    row = await db.scalar(
        select(Connection.id).where(_pair(a, b), Connection.status == "accepted"))
    return row is not None


async def connected_users(db: AsyncSession, user_id: uuid.UUID) -> list[User]:
    conns = list(await db.scalars(select(Connection).where(
        Connection.status == "accepted",
        or_(Connection.requester_id == user_id, Connection.addressee_id == user_id))))
    ids = [c.addressee_id if c.requester_id == user_id else c.requester_id for c in conns]
    if not ids:
        return []
    return list(await db.scalars(select(User).where(User.id.in_(ids))))


async def request(db: AsyncSession, requester: User, email: str) -> dict:
    target = await get_user_by_email(db, email)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "No AARTH user with that email yet — invite them to join.")
    if target.id == requester.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That's you.")
    existing = await db.scalar(select(Connection).where(_pair(requester.id, target.id)))
    if existing is not None:
        if existing.status == "accepted":
            return {"status": "accepted", "message": "Already connected."}
        # Reverse pending? then this request accepts it.
        if existing.status == "pending" and existing.addressee_id == requester.id:
            existing.status = "accepted"
            db.add(Notification(
                user_id=existing.requester_id, kind="connect_accepted",
                title="Connected", body=f"{requester.display_name} accepted your connection."))
            await db.commit()
            return {"status": "accepted", "message": f"Connected with {target.display_name}."}
        return {"status": existing.status, "message": "Request already pending."}
    conn = Connection(requester_id=requester.id, addressee_id=target.id, status="pending")
    db.add(conn)
    db.add(Notification(
        user_id=target.id, kind="connect_request", title="Connection request",
        body=f"{requester.display_name} wants to connect on AARTH."))
    await db.commit()
    return {"status": "pending", "message": f"Request sent to {target.display_name}."}


async def respond(db: AsyncSession, user: User, conn_id: uuid.UUID, action: str) -> dict:
    conn = await db.get(Connection, conn_id)
    if conn is None or user.id not in (conn.requester_id, conn.addressee_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if action == "accept":
        if conn.addressee_id != user.id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the recipient can accept.")
        conn.status = "accepted"
        db.add(Notification(
            user_id=conn.requester_id, kind="connect_accepted", title="Connected",
            body=f"{user.display_name} accepted your connection."))
        await db.commit()
        return {"status": "accepted"}
    if action == "block":
        conn.status = "blocked"
        await db.commit()
        return {"status": "blocked"}
    # decline / remove
    await db.delete(conn)
    await db.commit()
    return {"status": "removed"}


async def list_for_user(db: AsyncSession, user: User) -> dict:
    rows = list(await db.scalars(select(Connection).where(
        or_(Connection.requester_id == user.id, Connection.addressee_id == user.id))))
    other_ids = {(c.addressee_id if c.requester_id == user.id else c.requester_id) for c in rows}
    users = {u.id: u for u in (await db.scalars(select(User).where(User.id.in_(other_ids))))} if other_ids else {}

    def brief(u):
        return {"id": str(u.id), "name": u.display_name, "email": u.email} if u else None

    connected, incoming, outgoing = [], [], []
    for c in rows:
        other = users.get(c.addressee_id if c.requester_id == user.id else c.requester_id)
        item = {"conn_id": str(c.id), "status": c.status, "user": brief(other)}
        if c.status == "accepted":
            connected.append(item)
        elif c.status == "pending" and c.addressee_id == user.id:
            incoming.append(item)
        elif c.status == "pending":
            outgoing.append(item)
    return {"connected": connected, "incoming": incoming, "outgoing": outgoing}
