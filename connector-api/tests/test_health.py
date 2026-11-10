import os
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from app.odoo_client import OdooSyncError

TEST_DB_PATH = Path(__file__).parent / "test_connector.db"
if TEST_DB_PATH.exists():
    TEST_DB_PATH.unlink()
os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{TEST_DB_PATH.as_posix()}"

from app.main import app
from app.db import SessionLocal
from app.models import TicketRecord


client = TestClient(app)


@pytest.fixture(autouse=True)
def _clean_db() -> None:
    db = SessionLocal()
    db.query(TicketRecord).delete()
    db.commit()
    db.close()
    yield


def test_health_endpoint() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_receive_ticket_created_and_duplicate() -> None:
    payload = {
        "external_ticket_id": "T-1001",
        "location_code": "LOC-01",
        "issued_at": "2026-11-04T10:00:00Z",
        "currency": "EUR",
        "total_amount": 19.5,
        "items": [
            {"product_sku": "CAF-001", "quantity": 1, "unit_price": 3.5},
            {"product_sku": "SND-010", "quantity": 2, "unit_price": 8.0},
        ],
        "payments": [{"method": "cash", "amount": 19.5}],
    }

    first_response = client.post("/api/v1/tickets", json=payload)
    assert first_response.status_code == 200
    first_body = first_response.json()
    assert first_body["external_ticket_id"] == "T-1001"
    assert first_body["status"] == "created"

    duplicate_response = client.post("/api/v1/tickets", json=payload)
    assert duplicate_response.status_code == 200
    duplicate_body = duplicate_response.json()
    assert duplicate_body["external_ticket_id"] == "T-1001"
    assert duplicate_body["status"] == "duplicate"


def test_sync_single_ticket_success(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "external_ticket_id": "T-2001",
        "location_code": "LOC-01",
        "issued_at": "2026-11-04T10:00:00Z",
        "currency": "EUR",
        "total_amount": 10.0,
        "items": [{"product_sku": "CAF-001", "quantity": 1, "unit_price": 10.0}],
        "payments": [{"method": "card", "amount": 10.0}],
    }

    client.post("/api/v1/tickets", json=payload)

    monkeypatch.setattr("app.sync_service.push_ticket", lambda _payload: None)

    sync_response = client.post("/api/v1/tickets/T-2001/sync")
    assert sync_response.status_code == 200
    assert sync_response.json()["status"] == "sent"


def test_sync_pending_failed_when_odoo_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "external_ticket_id": "T-3001",
        "location_code": "LOC-01",
        "issued_at": "2026-11-04T10:00:00Z",
        "currency": "EUR",
        "total_amount": 12.0,
        "items": [{"product_sku": "SND-010", "quantity": 1, "unit_price": 12.0}],
        "payments": [{"method": "cash", "amount": 12.0}],
    }

    client.post("/api/v1/tickets", json=payload)

    def _fail(_payload: dict) -> None:
        raise OdooSyncError("odoo down")

    monkeypatch.setattr("app.sync_service.push_ticket", _fail)

    sync_response = client.post("/api/v1/sync/pending")
    assert sync_response.status_code == 200
    body = sync_response.json()
    assert body["processed"] == 1
    assert body["failed"] == 1
    assert body["dead_letter"] == 0


def test_sync_pending_moves_to_dead_letter_after_max_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "external_ticket_id": "T-4001",
        "location_code": "LOC-01",
        "issued_at": "2026-11-04T10:00:00Z",
        "currency": "EUR",
        "total_amount": 8.0,
        "items": [{"product_sku": "CAF-001", "quantity": 1, "unit_price": 8.0}],
        "payments": [{"method": "cash", "amount": 8.0}],
    }

    client.post("/api/v1/tickets", json=payload)
    monkeypatch.setenv("SYNC_MAX_RETRIES", "1")

    def _fail(_payload: dict) -> None:
        raise OdooSyncError("odoo down")

    monkeypatch.setattr("app.sync_service.push_ticket", _fail)

    sync_response = client.post("/api/v1/sync/pending")
    assert sync_response.status_code == 200
    body = sync_response.json()
    assert body["processed"] == 1
    assert body["dead_letter"] == 1
    assert body["failed"] == 0


def test_sync_stats_endpoint_aggregates_status_and_location() -> None:
    payloads = [
        {
            "external_ticket_id": "T-5001",
            "location_code": "LOC-01",
            "issued_at": "2026-11-04T10:00:00Z",
            "currency": "EUR",
            "total_amount": 5.0,
            "items": [{"product_sku": "A", "quantity": 1, "unit_price": 5.0}],
            "payments": [{"method": "cash", "amount": 5.0}],
        },
        {
            "external_ticket_id": "T-5002",
            "location_code": "LOC-01",
            "issued_at": "2026-11-04T10:05:00Z",
            "currency": "EUR",
            "total_amount": 6.0,
            "items": [{"product_sku": "B", "quantity": 1, "unit_price": 6.0}],
            "payments": [{"method": "cash", "amount": 6.0}],
        },
        {
            "external_ticket_id": "T-5003",
            "location_code": "LOC-02",
            "issued_at": "2026-11-04T10:10:00Z",
            "currency": "EUR",
            "total_amount": 7.0,
            "items": [{"product_sku": "C", "quantity": 1, "unit_price": 7.0}],
            "payments": [{"method": "card", "amount": 7.0}],
        },
    ]

    for payload in payloads:
        response = client.post("/api/v1/tickets", json=payload)
        assert response.status_code == 200

    db = SessionLocal()
    ticket_5001 = db.query(TicketRecord).filter(TicketRecord.external_ticket_id == "T-5001").one()
    ticket_5002 = db.query(TicketRecord).filter(TicketRecord.external_ticket_id == "T-5002").one()
    ticket_5003 = db.query(TicketRecord).filter(TicketRecord.external_ticket_id == "T-5003").one()

    ticket_5001.sync_status = "sent"
    ticket_5002.sync_status = "failed"
    ticket_5003.sync_status = "dead_letter"
    db.commit()
    db.close()

    stats_response = client.get("/api/v1/sync/stats")
    assert stats_response.status_code == 200
    body = stats_response.json()

    assert body["total"] == 3
    assert body["sent"] == 1
    assert body["failed"] == 1
    assert body["dead_letter"] == 1
    assert body["pending"] == 0

    locations = {row["location_code"]: row for row in body["by_location"]}
    assert locations["LOC-01"]["sent"] == 1
    assert locations["LOC-01"]["failed"] == 1
    assert locations["LOC-02"]["dead_letter"] == 1


def test_sync_stats_endpoint_filters_by_location_and_date() -> None:
    payloads = [
        {
            "external_ticket_id": "T-6001",
            "location_code": "LOC-01",
            "issued_at": "2026-11-04T10:00:00Z",
            "currency": "EUR",
            "total_amount": 5.0,
            "items": [{"product_sku": "A", "quantity": 1, "unit_price": 5.0}],
            "payments": [{"method": "cash", "amount": 5.0}],
        },
        {
            "external_ticket_id": "T-6002",
            "location_code": "LOC-02",
            "issued_at": "2026-11-04T12:00:00Z",
            "currency": "EUR",
            "total_amount": 7.0,
            "items": [{"product_sku": "B", "quantity": 1, "unit_price": 7.0}],
            "payments": [{"method": "card", "amount": 7.0}],
        },
    ]

    for payload in payloads:
        response = client.post("/api/v1/tickets", json=payload)
        assert response.status_code == 200

    db = SessionLocal()
    ticket_6001 = db.query(TicketRecord).filter(TicketRecord.external_ticket_id == "T-6001").one()
    ticket_6002 = db.query(TicketRecord).filter(TicketRecord.external_ticket_id == "T-6002").one()
    ticket_6001.sync_status = "sent"
    ticket_6002.sync_status = "failed"
    db.commit()
    db.close()

    by_location = client.get("/api/v1/sync/stats?location_code=LOC-01")
    assert by_location.status_code == 200
    body_location = by_location.json()
    assert body_location["total"] == 1
    assert body_location["sent"] == 1
    assert body_location["failed"] == 0

    by_date = client.get(
        "/api/v1/sync/stats?issued_from=2026-11-04T11:00:00Z&issued_to=2026-11-04T13:00:00Z"
    )
    assert by_date.status_code == 200
    body_date = by_date.json()
    assert body_date["total"] == 1
    assert body_date["failed"] == 1
    assert body_date["sent"] == 0
