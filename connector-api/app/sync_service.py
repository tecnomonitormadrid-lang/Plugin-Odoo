from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.config import (
    get_sync_backoff_base_seconds,
    get_sync_backoff_max_seconds,
    get_sync_max_retries,
)
from app.models import TicketRecord
from app.odoo_client import OdooSyncError, push_ticket


def _next_retry_time(retry_count: int) -> datetime:
    base_seconds = get_sync_backoff_base_seconds()
    max_seconds = get_sync_backoff_max_seconds()
    delay_seconds = min(base_seconds * (2 ** max(retry_count - 1, 0)), max_seconds)
    return datetime.now(timezone.utc).replace(microsecond=0) + timedelta(seconds=delay_seconds)


def sync_one_ticket(db: Session, ticket: TicketRecord) -> tuple[str, str | None]:
    if ticket.sync_status == "sent":
        return "sent", None

    if ticket.sync_status == "dead_letter":
        return "dead_letter", "max retries reached"

    try:
        push_ticket(ticket.payload)
    except OdooSyncError as exc:
        ticket.retry_count += 1
        ticket.last_error = str(exc)

        max_retries = get_sync_max_retries()
        if ticket.retry_count >= max_retries:
            ticket.sync_status = "dead_letter"
            ticket.next_retry_at = None
        else:
            ticket.sync_status = "failed"
            ticket.next_retry_at = _next_retry_time(ticket.retry_count)

        db.add(ticket)
        db.commit()
        return ticket.sync_status, str(exc)

    ticket.sync_status = "sent"
    ticket.synced_at = datetime.now(timezone.utc)
    ticket.last_error = None
    ticket.next_retry_at = None
    db.add(ticket)
    db.commit()
    return "sent", None


def sync_by_external_ticket_id(db: Session, external_ticket_id: str) -> tuple[str, str | None]:
    ticket = db.execute(
        select(TicketRecord).where(TicketRecord.external_ticket_id == external_ticket_id)
    ).scalar_one_or_none()

    if ticket is None:
        return "not_found", "ticket not found"

    return sync_one_ticket(db, ticket)


def sync_pending_tickets(db: Session, limit: int) -> dict[str, int]:
    now_utc = datetime.now(timezone.utc)
    pending_tickets = db.execute(
        select(TicketRecord)
        .where(
            or_(
                TicketRecord.sync_status == "pending",
                (TicketRecord.sync_status == "failed")
                & (
                    (TicketRecord.next_retry_at.is_(None))
                    | (TicketRecord.next_retry_at <= now_utc)
                ),
            )
        )
        .order_by(TicketRecord.created_at.asc())
        .limit(limit)
    ).scalars().all()

    processed = 0
    sent = 0
    failed = 0
    dead_letter = 0

    for ticket in pending_tickets:
        processed += 1
        status, _ = sync_one_ticket(db, ticket)
        if status == "sent":
            sent += 1
        elif status == "failed":
            failed += 1
        elif status == "dead_letter":
            dead_letter += 1

    return {
        "processed": processed,
        "sent": sent,
        "failed": failed,
        "dead_letter": dead_letter,
    }


def get_sync_stats(
    db: Session,
    location_code: str | None = None,
    issued_from: datetime | None = None,
    issued_to: datetime | None = None,
) -> dict:
    totals = {"pending": 0, "failed": 0, "dead_letter": 0, "sent": 0}

    filters = []
    if location_code:
        filters.append(TicketRecord.location_code == location_code)
    if issued_from:
        filters.append(TicketRecord.issued_at >= issued_from)
    if issued_to:
        filters.append(TicketRecord.issued_at <= issued_to)

    status_query = (
        select(TicketRecord.sync_status, func.count(TicketRecord.id))
        .group_by(TicketRecord.sync_status)
    )
    if filters:
        status_query = status_query.where(*filters)
    status_rows = db.execute(status_query).all()

    for status, count in status_rows:
        if status in totals:
            totals[status] = int(count)

    by_location_map: dict[str, dict[str, int | str]] = {}
    location_query = (
        select(TicketRecord.location_code, TicketRecord.sync_status, func.count(TicketRecord.id))
        .group_by(TicketRecord.location_code, TicketRecord.sync_status)
    )
    if filters:
        location_query = location_query.where(*filters)
    location_rows = db.execute(location_query).all()

    for location_code, status, count in location_rows:
        if location_code not in by_location_map:
            by_location_map[location_code] = {
                "location_code": location_code,
                "pending": 0,
                "failed": 0,
                "dead_letter": 0,
                "sent": 0,
            }
        if status in {"pending", "failed", "dead_letter", "sent"}:
            by_location_map[location_code][status] = int(count)

    by_location = sorted(by_location_map.values(), key=lambda row: str(row["location_code"]))
    total_count = totals["pending"] + totals["failed"] + totals["dead_letter"] + totals["sent"]

    return {
        "pending": totals["pending"],
        "failed": totals["failed"],
        "dead_letter": totals["dead_letter"],
        "sent": totals["sent"],
        "total": total_count,
        "by_location": by_location,
    }
