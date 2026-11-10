from pathlib import Path

from scripts.agora_poller import load_since_cursor, map_agora_ticket_to_connector, save_since_cursor


def test_map_agora_ticket_to_connector() -> None:
    agora_ticket = {
        "id": "AG-1001",
        "store_code": "LOC-01",
        "closed_at": "2026-11-04T20:14:33Z",
        "currency": "EUR",
        "total": 15.4,
        "lines": [{"sku": "CAF-001", "qty": 2, "unit_price": 3.2}],
        "payments": [{"method": "cash", "amount": 15.4}],
    }

    mapped = map_agora_ticket_to_connector(agora_ticket)

    assert mapped["external_ticket_id"] == "AG-1001"
    assert mapped["location_code"] == "LOC-01"
    assert mapped["currency"] == "EUR"
    assert mapped["total_amount"] == 15.4
    assert mapped["items"][0]["product_sku"] == "CAF-001"


def test_state_cursor_roundtrip(tmp_path: Path) -> None:
    state_file = tmp_path / "state.json"
    save_since_cursor(state_file, "2026-11-04T22:00:00Z")
    loaded = load_since_cursor(state_file)
    assert loaded == "2026-11-04T22:00:00Z"
