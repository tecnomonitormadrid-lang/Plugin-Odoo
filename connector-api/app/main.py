from datetime import datetime

from fastapi import Depends, FastAPI
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_sync_batch_size
from app.db import get_db, init_db
from app.models import TicketRecord
from app.schemas import (
    PendingSyncResult,
    SyncStatsResult,
    TicketAccepted,
    TicketIn,
    TicketSyncResult,
)
from app.sync_service import get_sync_stats, sync_by_external_ticket_id, sync_pending_tickets

app = FastAPI(title="TPV Odoo Connector API", version="0.1.0")


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "connector-api"}


@app.get("/ready")
def ready(db: Session = Depends(get_db)) -> dict[str, str]:
    db.execute(text("SELECT 1"))
    return {"status": "ready"}


@app.post("/api/v1/tickets", response_model=TicketAccepted)
def receive_ticket(ticket: TicketIn, db: Session = Depends(get_db)) -> TicketAccepted:
    existing = db.execute(
        select(TicketRecord).where(TicketRecord.external_ticket_id == ticket.external_ticket_id)
    ).scalar_one_or_none()

    if existing:
        return TicketAccepted(
            message="duplicate ticket ignored",
            external_ticket_id=ticket.external_ticket_id,
            status="duplicate",
        )

    record = TicketRecord(
        external_ticket_id=ticket.external_ticket_id,
        location_code=ticket.location_code,
        issued_at=ticket.issued_at,
        currency=ticket.currency,
        total_amount=ticket.total_amount,
        payload=ticket.model_dump(mode="json"),
        sync_status="pending",
        retry_count=0,
        next_retry_at=None,
    )

    db.add(record)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return TicketAccepted(
            message="duplicate ticket ignored",
            external_ticket_id=ticket.external_ticket_id,
            status="duplicate",
        )

    return TicketAccepted(
        message="ticket accepted",
        external_ticket_id=ticket.external_ticket_id,
        status="created",
    )


@app.post("/api/v1/tickets/{external_ticket_id}/sync", response_model=TicketSyncResult)
def sync_ticket(external_ticket_id: str, db: Session = Depends(get_db)) -> TicketSyncResult:
    status, detail = sync_by_external_ticket_id(db, external_ticket_id)
    return TicketSyncResult(
        external_ticket_id=external_ticket_id,
        status=status,
        detail=detail,
    )


@app.post("/api/v1/sync/pending", response_model=PendingSyncResult)
def sync_pending(limit: int | None = None, db: Session = Depends(get_db)) -> PendingSyncResult:
    effective_limit = limit if limit is not None else get_sync_batch_size()
    summary = sync_pending_tickets(db, limit=effective_limit)
    return PendingSyncResult(**summary)


@app.get("/api/v1/sync/stats", response_model=SyncStatsResult)
def sync_stats(
    location_code: str | None = None,
    issued_from: datetime | None = None,
    issued_to: datetime | None = None,
    db: Session = Depends(get_db),
) -> SyncStatsResult:
    summary = get_sync_stats(
        db,
        location_code=location_code,
        issued_from=issued_from,
        issued_to=issued_to,
    )
    return SyncStatsResult(**summary)
