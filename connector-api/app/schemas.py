from datetime import datetime
from pydantic import BaseModel, Field


class TicketItem(BaseModel):
    product_sku: str = Field(..., min_length=1)
    quantity: float = Field(..., gt=0)
    unit_price: float = Field(..., ge=0)


class TicketPayment(BaseModel):
    method: str = Field(..., min_length=1)
    amount: float = Field(..., ge=0)


class TicketIn(BaseModel):
    external_ticket_id: str = Field(..., min_length=1)
    location_code: str = Field(..., min_length=1)
    issued_at: datetime
    currency: str = Field(..., min_length=3, max_length=3)
    total_amount: float = Field(..., ge=0)
    items: list[TicketItem]
    payments: list[TicketPayment]


class TicketAccepted(BaseModel):
    message: str
    external_ticket_id: str
    status: str


class TicketSyncResult(BaseModel):
    external_ticket_id: str
    status: str
    detail: str | None = None


class PendingSyncResult(BaseModel):
    processed: int
    sent: int
    failed: int
    dead_letter: int


class SyncStatsByLocation(BaseModel):
    location_code: str
    pending: int
    failed: int
    dead_letter: int
    sent: int


class SyncStatsResult(BaseModel):
    pending: int
    failed: int
    dead_letter: int
    sent: int
    total: int
    by_location: list[SyncStatsByLocation]
